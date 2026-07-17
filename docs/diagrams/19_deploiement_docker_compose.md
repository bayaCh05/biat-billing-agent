# Diagram 19 — Docker Compose Deployment

New diagram (2026-07-15) — accompanies the finalized deployment package
(`docker-compose.yml` + `Dockerfile`, combined backend+SPA `app` image,
Mongo healthcheck, `host.docker.internal` for Ollama). Translated to
English 2026-07-16.

Rendered: [`19_deploiement_docker_compose.png`](19_deploiement_docker_compose.png) ·
Live editable source: https://app.eraser.io/workspace/NAh6JeIRqqIfV1Fef6wg?diagram=GmmUJSi7tR1zyBiPGZF8

Paste into Eraser → New Diagram → Cloud Architecture

```
title: "19 - Docker Compose Deployment"
direction: right

Host [label: "Host machine (Mac/Windows/Linux)", icon: monitor, color: "#1A3A5C"] {
  Ollama [label: "Ollama qwen2.5:3b\n(native process, NEVER containerized)", icon: cpu, color: "#804CD7"]
  Browser [label: "Browser (Accountant/Admin/...)", icon: globe, color: "#2E86C1"]
}

DockerCompose [label: "docker compose up -d", icon: box, color: "#1A3A5C"] {
  AppContainer [label: "app\n(multi-stage Dockerfile:\nbuilt React SPA + FastAPI)", icon: package, color: "#2E86C1"]
  MongoContainer [label: "mongo (mongo:7, --auth)", icon: database, color: "#2E86C1"]
  MailhogContainer [label: "mailhog (dev only)", icon: mail, color: "#5D6D7E"]
}

Volumes [label: "Named volumes", icon: hard-drive, color: "#1A3A5C"] {
  BiatData [label: "biat_data\n(SQLite, uploads, ChromaDB)", icon: hard-drive, color: "#5D6D7E"]
  BiatExports [label: "biat_exports", icon: hard-drive, color: "#5D6D7E"]
  MongoData [label: "biat_mongo_data", icon: hard-drive, color: "#5D6D7E"]
}

Browser -> AppContainer: "HTTP :8000 (SPA + /api)"
AppContainer -> MongoContainer: "mongodb://mongo:27017 (authSource=admin)"
AppContainer -> Ollama: "http://host.docker.internal:11434\n(extra_hosts: host-gateway)"
AppContainer -> BiatData
AppContainer -> BiatExports
MongoContainer -> MongoData
MongoContainer -> AppContainer: "healthcheck: mongosh ping\n(depends_on: service_healthy)"
```

> **Note**: a single application container (`app`) serves both the FastAPI
> API and the compiled React SPA (no separate nginx container — the
> `Dockerfile` copies `frontend/dist/` into the backend image at build
> time). Ollama always runs on the host, never in Docker (data residency
> constraint — see `CLAUDE.md`); the `app` container reaches it via
> `host.docker.internal`, with `extra_hosts: host-gateway` so it also works
> on Linux (native on Docker Desktop Mac/Windows).
