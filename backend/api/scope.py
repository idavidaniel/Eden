"""Whose request this is, available anywhere without threading it through.

`get_company` is called from about forty places. Adding a `caller` argument to
every one of them would work right up until somebody adds the forty-first and
forgets — and the failure mode of forgetting is silently serving another
tenant's data, which is the bug this whole change exists to prevent.

So the caller is resolved once per request by a dependency and put in a
contextvar. `get_company` reads it and refuses if it is not there. A new route
that reads a company gets scoping whether or not its author thought about it;
one that genuinely has no caller fails loudly rather than leaking.

Contextvars are per-task, so concurrent requests never see each other's caller.
"""

from contextvars import ContextVar

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from db import get_db

from .deps import Caller, optional_agent, optional_user

_caller: ContextVar[Caller | None] = ContextVar("eden_caller", default=None)


async def bind_caller(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Resolve who is calling, if anyone, and make it available for this request.

    Deliberately does not raise on an anonymous request: some routes are public,
    and a global dependency that 401s would take them down with it. Refusal
    happens where the data is, in `get_company`.

    `async` on purpose. A sync dependency runs in a threadpool, so the token
    returned by `set` belongs to a different context than the one `reset` runs
    in, and resetting it raises. Setting it here, in the request's own task,
    also means a sync route handler still sees it: anyio copies the context
    into the worker thread.
    """
    found: Caller | None = None
    person = optional_user(request, authorization, db)
    if person:
        found = Caller(tenant_id=person.tenant_id, user=person)
    else:
        agent = optional_agent(request, authorization, db)
        if agent:
            found = Caller(tenant_id=agent.tenant_id, agent=agent)

    token = _caller.set(found)
    try:
        yield found
    finally:
        _caller.reset(token)


def caller() -> Caller | None:
    return _caller.get()


def require_caller() -> Caller:
    found = _caller.get()
    if found is None:
        raise HTTPException(
            status_code=401,
            detail="Sign in, or send an agent token.",
            headers={"WWW-Authenticate": 'Bearer realm="eden"'},
        )
    return found
