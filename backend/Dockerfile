FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    FLUTTER_HOME=/opt/flutter \
    PUB_CACHE=/opt/pub-cache \
    PATH=/opt/flutter/bin:/opt/flutter/bin/cache/dart-sdk/bin:$PATH

WORKDIR /app

# git is not optional: every project workspace is a real repository that the AI
# employees commit to under their own names.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl git libpq-dev unzip xz-utils zip \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system init.defaultBranch main \
    && git config --system --add safe.directory '*'

# Flutter, so employees can analyse, test and build Dart/Flutter projects and QA
# can actually verify them. Pinned to a stable tag for reproducible images.
ARG FLUTTER_VERSION=stable
RUN git clone --depth 1 -b ${FLUTTER_VERSION} https://github.com/flutter/flutter.git ${FLUTTER_HOME} \
    && flutter config --no-analytics --no-cli-animations > /dev/null \
    && flutter precache --universal --linux \
    && flutter --version \
    && chmod -R a+rwX ${FLUTTER_HOME} ${PUB_CACHE}

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .
RUN mkdir -p /data/workspaces

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
