# Eden on the Raspberry Pi

The box is a Raspberry Pi 5 (`aarch64`, Debian 13 trixie, 4 cores, 4GB RAM,
2GB swap) reached at `ssh dd@ssh.handkraftedstore.com`. The application lives
in `~/eden` and runs under Docker Compose.

## How the traffic gets in

The Pi does not listen on its LAN or its public interface at all. A
`cloudflared` container was already running there in **host network mode**,
holding an outbound tunnel to Cloudflare. Both Eden ports bind to `127.0.0.1`,
which that container can reach and nothing else can:

    Cloudflare edge  ──tunnel──▶  cloudflared (host net)  ──▶  127.0.0.1:3000  frontend
                                                          └─▶  127.0.0.1:8000  backend (debug only)

Postgres is not published on any interface.

To finish the wiring, add a public hostname to the tunnel in the Cloudflare
Zero Trust dashboard (Networks → Tunnels → the existing tunnel → Public
Hostnames):

    Subdomain   eden
    Domain      handkraftedstore.com
    Service     HTTP://localhost:3000

Nothing needs to change on the Pi for that; the tunnel picks the route up on
its own.

If the subdomain is not `eden.handkraftedstore.com`, change `PUBLIC_ORIGIN` in
`~/eden/.env.prod` and restart the backend. That value is only a CORS backstop
— the browser talks to the Next server, which talks to the API over the compose
network — but it should still be right.

## Running it

    cd ~/eden
    docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
    docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f

`docker-compose.prod.yml` differs from the development file in the ways that
matter for an unattended machine: no bind-mounted source, no `--reload`, secure
cookies, one run at a time, and no port reachable from off the box.

## Secrets

`~/eden/.env.prod` is mode 600 and is not in the repository. `SECRET_KEY`,
`JWT_SECRET` and the Postgres password were generated on the Pi and have never
been anywhere else. `NVIDIA_API_KEY` is the same key the development machine
uses.

## Updating

There is no git remote, so a deploy is an rsync from the development machine:

    rsync -az --delete \
      --exclude '.git/' --exclude 'node_modules/' --exclude '.next/' \
      --exclude '.venv/' --exclude '__pycache__/' --exclude '.env' \
      ./ dd@ssh.handkraftedstore.com:~/eden/

    ssh dd@ssh.handkraftedstore.com \
      'cd ~/eden && docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build'

The `--exclude '.env'` matters: it stops the development environment file from
landing next to the production one.

## What persists

Three named volumes. `workspace_data` is the one that cannot be lost — it holds
every deliverable and project repository, and a check that cannot read its
artifact cannot be replayed, which is the whole point of the product.

    eden_postgres_data    the database
    eden_workspace_data   DATA_DIR — deliverables and project git repositories
    eden_pub_cache        Dart/Flutter packages, so `pub get` is not run cold

## Notes for this hardware

The backend image is ~3.5GB, most of it the Flutter SDK that lets QA actually
build and test Dart projects rather than take an agent's word for it. The first
build on the Pi takes a long time for that reason.

`RUN_CONCURRENCY` is 1. Four cores shared with Postgres and a Node server do not
want two agent runs at once.
