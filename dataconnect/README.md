# Why this directory exists

Eden does not use Firebase Data Connect.

Data Connect is a GraphQL layer that generates and owns a Postgres schema from
the `.gql` files here. Eden is a SQLAlchemy application with its own Alembic
migration chain, so the two cannot both own the database.

What this directory is for is the one useful side effect: running

    firebase deploy --only dataconnect

provisions and keeps alive the Cloud SQL for PostgreSQL instance `eden-fdc` in
`us-east4`, which is the instance Eden's own database lives on. The schema and
connector below are the untouched Data Connect starter example; they exist
because the product requires *some* schema, and they live in their own database
(`fdcdb`) where they cannot collide with Eden's.

Nothing in `backend/` or `frontend/` imports any of this. See
`docs/hosting.md` for how the backend actually connects.
