"""Reaching the internet, carefully.

Two things make this safe enough to switch on. Egress is default-deny: a company
declares which hosts its agents may reach, and everything else is refused with
the reason. And every fetch is *recorded* — the extracted text is stored under
its own hash, so a citation check later has something real to look the quote up
in. Text that came from outside is never handed to a model as instructions; it
arrives wrapped in an envelope the system prompt describes as data.
"""

import html
import logging
import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Company, Source

from . import blobs

log = logging.getLogger(__name__)

MAX_BYTES = 2_000_000
MAX_TEXT_CHARS = 200_000
TIMEOUT_SECONDS = 20.0
USER_AGENT = "EdenAgent/1.0 (+https://localhost/eden)"

# Hosts a new company may reach before you decide otherwise: documentation,
# standards and package indexes. Not a browser — a reference shelf.
DEFAULT_ALLOWLIST = [
    "*.wikipedia.org",
    "developer.mozilla.org",
    "docs.python.org",
    "peps.python.org",
    "pypi.org",
    "*.readthedocs.io",
    "docs.djangoproject.com",
    "www.postgresql.org",
    "sqlite.org",
    "www.sqlite.org",
    "docs.flutter.dev",
    "api.flutter.dev",
    "dart.dev",
    "pub.dev",
    "developer.apple.com",
    "developer.android.com",
    "www.rfc-editor.org",
    "datatracker.ietf.org",
    "html.duckduckgo.com",
]

SCRIPT_OR_STYLE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")
BLANK_LINES = re.compile(r"\n{3,}")
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)


class EgressRefused(RuntimeError):
    pass


def allowlist_for(company: Company) -> list[str]:
    configured = (company.settings or {}).get("egress_allow")
    if configured is None:
        return list(DEFAULT_ALLOWLIST)
    return list(configured)


def egress_open(company: Company) -> bool:
    """True when a company has deliberately turned the allow-list off."""
    return bool((company.settings or {}).get("egress_open"))


def host_allowed(company: Company, url: str) -> tuple[bool, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False, f"Only http and https are fetchable; this is '{parsed.scheme or 'nothing'}'."
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "That URL has no host."
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".local"):
        return False, "Local addresses are never fetchable from a tool."
    if _is_private_address(host):
        return False, "Private network addresses are never fetchable from a tool."
    if egress_open(company):
        return True, ""
    for pattern in allowlist_for(company):
        if _matches(host, pattern):
            return True, ""
    return False, (
        f"{host} is not on this company's allow-list. "
        "Add it under Connections if the work genuinely needs it."
    )


def _matches(host: str, pattern: str) -> bool:
    pattern = pattern.lower().strip()
    if pattern.startswith("*."):
        suffix = pattern[1:]
        return host == pattern[2:] or host.endswith(suffix)
    return host == pattern


def _is_private_address(host: str) -> bool:
    import ipaddress

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def extract_text(body: str, content_type: str) -> tuple[str, str]:
    """Plain text and a title. Deliberately simple: no JavaScript is executed."""
    if "html" not in content_type:
        return body[:MAX_TEXT_CHARS], ""
    title_match = TITLE.search(body)
    title = html.unescape(title_match.group(1)).strip()[:400] if title_match else ""
    stripped = SCRIPT_OR_STYLE.sub(" ", body)
    stripped = re.sub(r"<br\s*/?>", "\n", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"</(p|div|li|h[1-6]|tr)>", "\n", stripped, flags=re.IGNORECASE)
    text = html.unescape(TAG.sub(" ", stripped))
    text = "\n".join(line.strip() for line in text.splitlines())
    text = BLANK_LINES.sub("\n\n", re.sub(r"[ \t]{2,}", " ", text)).strip()
    return text[:MAX_TEXT_CHARS], title


def fetch(
    db: Session,
    company: Company,
    url: str,
    *,
    project_id: str | None = None,
    work_item_id: str | None = None,
    fetched_by: str | None = None,
) -> Source:
    """Fetch a page and record it, so a later citation can be checked against it."""
    allowed, reason = host_allowed(company, url)
    if not allowed:
        raise EgressRefused(reason)

    with httpx.Client(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,*/*"},
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        final_url = str(response.url)
        # A redirect must not be a way around the allow-list.
        allowed, reason = host_allowed(company, final_url)
        if not allowed:
            raise EgressRefused(f"Redirected to a host that is not allowed. {reason}")
        raw = response.content[:MAX_BYTES]

    content_type = response.headers.get("content-type", "").lower()
    body = raw.decode(response.encoding or "utf-8", errors="replace")
    text, title = extract_text(body, content_type)
    content_hash = blobs.hash_text(text)

    existing = db.scalar(
        select(Source).where(
            Source.company_id == company.id,
            Source.url == final_url,
            Source.content_hash == content_hash,
        )
    )
    if existing:
        return existing

    source = Source(
        created_at=datetime.now(UTC),
        company_id=company.id,
        project_id=project_id,
        work_item_id=work_item_id,
        fetched_by=fetched_by,
        url=final_url[:1000],
        title=(title or urlparse(final_url).path or final_url)[:400],
        content_hash=content_hash,
        text_key=blobs.put_text(text),
        chars=len(text),
        meta={"content_type": content_type, "status": response.status_code},
    )
    db.add(source)
    db.flush()
    return source


RESULT_LINK = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
RESULT_SNIPPET = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)


def search(company: Company, query: str, limit: int = 8) -> list[dict]:
    """A plain HTML search, so this works without a paid search key.

    It is scraping, and scraping breaks. When it does, the caller is told that
    rather than being handed an empty list that looks like "no results".
    """
    endpoint = "https://html.duckduckgo.com/html/"
    allowed, reason = host_allowed(company, endpoint)
    if not allowed:
        raise EgressRefused(reason)

    with httpx.Client(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        response = client.post(endpoint, data={"q": query})
        response.raise_for_status()
        body = response.text

    titles = list(RESULT_LINK.finditer(body))
    snippets = [match.group("snippet") for match in RESULT_SNIPPET.finditer(body)]
    if not titles:
        raise RuntimeError(
            "The search page returned no recognisable results — its markup has probably "
            "changed. Fetch a URL directly instead."
        )

    results = []
    for index, match in enumerate(titles[:limit]):
        href = html.unescape(match.group("href"))
        if href.startswith("//"):
            href = "https:" + href
        results.append(
            {
                "url": urljoin(endpoint, href),
                "title": _plain(match.group("title")),
                "snippet": _plain(snippets[index]) if index < len(snippets) else "",
            }
        )
    return results


def _plain(fragment: str) -> str:
    return html.unescape(TAG.sub("", fragment)).strip()[:400]


def envelope(source: Source, text: str) -> str:
    """Wrap fetched text so the model treats it as data, not as instructions."""
    # The id can be absent if the row has not been flushed yet. The envelope is
    # a safety boundary, so it degrades rather than raising.
    marker = (source.id or "unsaved")[:8]
    return (
        f'<untrusted-source id="{marker}" url="{source.url}">\n'
        f"{text}\n"
        "</untrusted-source>"
    )
