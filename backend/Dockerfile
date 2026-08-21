FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /app

# git is not optional here: every project workspace is a real repository that
# the AI employees commit to under their own names.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl git libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system init.defaultBranch main \
    && git config --system --add safe.directory '*'

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .
RUN mkdir -p /data/workspaces

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
