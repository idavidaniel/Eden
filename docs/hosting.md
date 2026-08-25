# Putting Eden on the internet

Two processes with very different needs, so they go to different places.

| | What it is | Where it can go |
| --- | --- | --- |
| **Frontend** | Next.js 16, server-rendered, no state of its own | Firebase App Hosting, Vercel, anywhere that runs Next |
| **Backend** | FastAPI, a background thread, and a disk it must keep | Fly.io, a VM, or Cloud Run with care |
| **Database** | Postgres **with pgvector** | Cloud SQL, Neon, Supabase, Fly Postgres |

## What actually constrains the backend

Read this before picking a host, because three of these rule out the obvious
answer.

**It has a clock.** A daemon thread ticks every five seconds to lease queued
work. On a platform that suspends the container between requests — Cloud Run
without CPU always allocated, any scale-to-zero tier — that thread stops, and
the company silently does nothing until somebody loads a page. It needs an
always-on instance.

**It has a disk it must keep.** `DATA_DIR` holds the git workspaces and the
content-addressed blob store. Every deliverable's check result is pinned to the
hash of bytes in that store. On ephemeral disk, every artifact reads as *"the
content is gone"* on re-verification — which is technically correct and
completely useless. This is around 350 MB today and grows with the work.

**It streams.** The activity feed and per-task logs are server-sent events held
open for minutes. Anything that buffers responses or caps request duration low
will break the live UI.

**Postgres is not optional, and neither is pgvector.** Memory retrieval uses a
`vector` column with an HNSW index. Without the extension the app still runs —
retrieval falls back to word matching and says so in the interface — but you
have turned off the thing the memory system exists for.

## The backend, ranked

**Fly.io** — the closest fit. Docker-native so the existing image goes up
unchanged, volumes are real block storage, machines stay running, and Fly
Postgres has pgvector. Roughly $5–15/month for a small machine plus a volume.

**A VM (Compute Engine e2-small, Hetzner, DigitalOcean)** — the simplest thing
that certainly works. `docker compose up -d` and you are done, because that is
what the project already is. Persistent disk, always on, no platform quirks to
work around. ~$15/month, and you own the patching.

**Cloud Run** — workable, and worth it only if you want everything inside GCP
next to Cloud SQL. It needs all three of:
- `--min-instances=1`, or the clock stops between requests;
- `--cpu-always-allocated` (CPU is throttled outside a request otherwise, which
  is exactly when the clock wants to run);
- a volume for `DATA_DIR`. GCS FUSE works but is slow for git; Filestore is
  faster and pricier.

Container runner profiles (`ENABLE_RUNNER_PROFILES`) cannot work on Cloud Run at
all — there is no Docker socket. Leave them off, or use a VM.

**Not suitable:** Firebase App Hosting (Next.js and Angular only), Vercel
functions, Lambda, or anything else with a request timeout and no disk.

## The frontend

**Firebase App Hosting** if you are already on Firebase — it builds Next.js from
a repository and serves it. Set `API_URL` to the backend's address; the browser
never talks to the backend directly, it goes through `/api/backend/*` in the
Next server, so the backend needs no CORS entry for the browser origin.

**Vercel** is the other obvious choice and needs no explanation.

Either way, set on the backend:

```
COOKIE_SECURE=true            # cookies travel in the clear without it
COOKIE_DOMAIN=.your-domain    # only if the API is on a different host
CORS_ORIGINS=https://your-frontend
JWT_SECRET=<a long random string, different from SECRET_KEY>
SECRET_KEY=<a long random string; changing it makes sealed secrets unreadable>
```

`SECRET_KEY` deserves a warning of its own: it seals connector credentials and
every TOTP secret. Change it after people have set up two-factor and none of
them can sign in, because their secrets no longer decrypt.

## The database

```bash
# Schema only — what a new deployment usually wants.
python scripts/migrate_to.py 'postgresql://user:pass@host:5432/eden'

# Schema and the rows currently in the local database.
python scripts/migrate_to.py 'postgresql://…' --copy-data
```

It creates the `vector` extension, runs the Alembic chain, and — with
`--copy-data` — copies the tables in dependency order and resets the sequences.
It deliberately does not touch `DATA_DIR`; copy that directory yourself if the
existing deliverables should survive the move.

### What is already provisioned on Firebase

The Firebase project is **`eden-4d85e`** (`.firebaserc` points at it). Running
`firebase_init` with `provision_cloudsql` and then `firebase deploy --only
dataconnect` created a real, running Cloud SQL for PostgreSQL instance:

    instance   eden-fdc
    region     us-east4
    database   fdcdb          (Data Connect's own; leave it alone)

`firebase dataconnect:sql:setup` completed against it, which is proof the
instance is up and reachable from Google's side.

**Data Connect itself is not the thing we want.** It is a GraphQL layer that
manages its own schema from `.gql` files and expects to own the database. Eden
is a SQLAlchemy application with its own migration chain. `dataconnect/` is kept
in the repo only because it is what provisions and holds the Cloud SQL instance;
nothing in `backend/` or `frontend/` imports it.

### Finishing the Cloud SQL connection

Three things remain, and all three need the Cloud SQL Admin API — neither the
Firebase MCP plugin nor the Firebase CLI exposes them, so they are done in the
console at <https://console.cloud.google.com/sql/instances/eden-fdc> or with
`gcloud` (not installed on this machine).

1. **Create the application database and user.**

       gcloud sql databases create eden --instance=eden-fdc
       gcloud sql users create eden_app --instance=eden-fdc --password=<password>

2. **Make it reachable.** The instance has no public route to a laptop or to a
   non-GCP host. Either enable a public IP and add an authorised network, or —
   better — run the Cloud SQL Auth Proxy next to the backend:

       gcloud sql instances patch eden-fdc --assign-ip \
           --authorized-networks=<your.ip.address>/32

3. **Enable pgvector**, once connected:

       CREATE EXTENSION IF NOT EXISTS vector;

Then set `DATABASE_URL` and run the migration:

    DATABASE_URL=postgresql://eden_app:<password>@<host>:5432/eden \
        python scripts/migrate_to.py --copy-data

**It needs billing enabled** on the GCP project — there is no free tier for
Cloud SQL, and the Data Connect no-cost trial covers Data Connect, not an
arbitrary Postgres client.

### Without GCP billing

**Neon** — serverless Postgres, pgvector on the free tier, a connection string
you can paste straight into `DATABASE_URL`. The easiest way to have this running
today.

**Supabase** — also free, also pgvector, and gives you a SQL console.

Both scale to zero, which is fine for the database: it is the *backend* that
must stay awake, not Postgres.
