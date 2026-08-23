"""Wiki tools — the built-in equivalent of Confluence."""

from sqlalchemy import select

from models import Document, DocumentVersion
from services import events
from services.identity import slugify

from .base import Tool, ToolContext, obj, string


def list_pages(ctx: ToolContext, space: str = "") -> str:
    query = select(Document).where(Document.company_id == ctx.company.id).order_by(Document.title)
    if space:
        query = query.where(Document.space == space)
    pages = list(ctx.db.scalars(query))
    if not pages:
        return "The wiki is empty."
    return "\n".join(f"[{p.space}] {p.title} (slug: {p.slug}, v{p.version})" for p in pages)


def read_page(ctx: ToolContext, slug: str) -> str:
    page = ctx.db.scalar(
        select(Document).where(Document.company_id == ctx.company.id, Document.slug == slug)
    )
    if not page:
        return f"No page with slug '{slug}'."
    return f"# {page.title}\n\n{page.body}"


def write_page(ctx: ToolContext, title: str, body: str, space: str = "General") -> str:
    """Create a page, or publish a new version of an existing one."""
    slug = slugify(title, "page")
    page = ctx.db.scalar(
        select(Document).where(Document.company_id == ctx.company.id, Document.slug == slug)
    )
    if page:
        page.version += 1
        page.body = body
        page.author_id = ctx.employee.id
        action = f"updated to v{page.version}"
    else:
        page = Document(
            company_id=ctx.company.id,
            project_id=ctx.project.id if ctx.project else None,
            space=space or "General",
            title=title[:240],
            slug=slug,
            body=body,
            author_id=ctx.employee.id,
            version=1,
        )
        action = "created"
    ctx.db.add(page)
    ctx.db.flush()
    ctx.db.add(
        DocumentVersion(
            document_id=page.id,
            version=page.version,
            body=body,
            author_id=ctx.employee.id,
            author_label=ctx.actor,
        )
    )
    events.record(
        ctx.db,
        company_id=ctx.company.id,
        project_id=ctx.project.id if ctx.project else None,
        run_id=ctx.run.id if ctx.run else None,
        employee_id=ctx.employee.id,
        actor=ctx.actor,
        kind="wiki.published",
        summary=f"{action} wiki page '{page.title}'",
        payload={"document_id": page.id, "slug": page.slug, "version": page.version},
    )
    return f"Wiki page '{page.title}' {action} (slug: {page.slug})."


TOOLS = [
    Tool(
        name="list_wiki_pages",
        group="wiki",
        description="List the company's wiki pages.",
        parameters=obj({"space": string("Optional space filter")}, required=[]),
        read_only=True,
        handler=list_pages,
    ),
    Tool(
        name="read_wiki_page",
        group="wiki",
        description="Read a wiki page by slug.",
        parameters=obj({"slug": string("Page slug")}),
        read_only=True,
        handler=read_page,
    ),
    Tool(
        name="write_wiki_page",
        group="wiki",
        description=(
            "Publish a prose wiki page - a spec, decision record or guide. "
            "Creates it, or adds a version when the title already exists. "
            "Not a place for source code: code belongs in the workspace."
        ),
        parameters=obj(
            {
                "title": string("Page title"),
                "body": string("Markdown body"),
                "space": string("Space, e.g. Engineering or Product"),
            },
            required=["title", "body"],
        ),
        handler=write_page,
    ),
]
