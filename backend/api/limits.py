"""Rate limiting, for the endpoints where guessing is the attack.

Signup and login are the two places where an unauthenticated caller can make
the server do expensive work — and where doing it a million times is the point.
Everything else is behind a session, where the account lockout in
`services/auth.py` is the tighter control.

Keyed by client IP. That is imperfect behind a shared NAT and useless against a
botnet, which is why it is not the only defence: the per-account lockout catches
a slow distributed guess that never trips a per-IP limit.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from config import get_settings

limiter = Limiter(
    key_func=get_remote_address,
    headers_enabled=True,
    enabled=get_settings().rate_limits_enabled,
)
