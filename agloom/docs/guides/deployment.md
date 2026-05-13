# Production deployment

agloom is two moving parts: the **Python `agloom` package** (library + `agloom-runtime` AGP bridge) and your **client** (npm `agloom-cli`, or `agloom_web`, or a custom AGP client).

## Environment variables (checklist)

| Variable                                                 | When                                                                                                           |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, … | Upstream LLM (see [LLM resolution](llm-resolution.md); CLI table under **agloom CLI → Models** on ReadTheDocs) |
| `AGLOOM_RUNTIME`                                         | Non-default path to the Python entrypoint for the bridge                                                       |
| `AGLOOM_PROVIDER` / `AGLOOM_MODEL`                       | Optional defaults for auto-detect / library                                                                    |
| `VITE_AGP_WS_URL`                                        | **Web** build: WebSocket URL for `agloom-runtime --transport=ws`                                               |
| `AWS_*` / `GOOGLE_APPLICATION_CREDENTIALS`               | Bedrock / Vertex / cloud IAM providers                                                                         |

Keep secrets out of images: mount env files or use your orchestrator’s secret store.

## Docker image (library + runtime)

Example multi-stage **Dockerfile** (adjust extras for your providers):

```dockerfile
FROM python:3.12-slim AS base
WORKDIR /app
RUN pip install --no-cache-dir 'agloom[openai,groq]' uvicorn

# Ship only what you need; add extras per provider (see pyproject optional-dependencies).
ENV PYTHONUNBUFFERED=1

COPY agloom.yaml /app/agloom.yaml

EXPOSE 8765
# WebSocket AGP bridge — bind behind TLS terminator / reverse proxy.
CMD ["agloom-runtime", "serve", "--transport=ws", "--host", "0.0.0.0", "--port", "8765", "--store", "sqlite", "--store-path", "/data/agp_events.db"]
```

Mount **`/data`** as a volume if you use SQLite EventStore replay.

## docker-compose (sketch)

```yaml
services:
  runtime:
    image: your-registry/agloom-runtime:latest
    ports:
      - "8765:8765"
    env_file: .env.prod
    volumes:
      - agp-events:/data

  web:
    build: ./agloom_web
    ports:
      - "3000:80"
    environment:
      VITE_AGP_WS_URL: wss://api.example.com/agp-ws

volumes:
  agp-events: {}
```

Terminate TLS at **nginx**, **Caddy**, or a cloud LB; forward WebSocket upgrades to port **8765**.

## Reverse proxy & auth

- **WebSocket**: enable `Upgrade` and `Connection` headers; increase **read timeouts** for long streams.
- **Auth**: terminate JWT / session cookies at the proxy; pass `Authorization: Bearer <token>` only if you enabled **`agloom-runtime --ws-token`** (see [Runtime CLI](../runtime/cli.md)).
- **Health**: when observability is enabled (`--obs`), poll **`GET /observe/healthz`** (liveness) and **`GET /observe/readyz`** (readiness / DB ping) on the observability port (default **8766** with `--obs-port`), or expose them behind the same proxy.

## Observability HTTP surface

With **`agloom-runtime serve --obs`**:

| Route                  | Purpose                                                                       |
| ---------------------- | ----------------------------------------------------------------------------- |
| `GET /observe/healthz` | Liveness JSON `{ "status": "ok" }`                                            |
| `GET /observe/readyz`  | Readiness JSON or **503** if the observability store is unavailable           |
| `GET /observe/metrics` | Minimal Prometheus text (`agloom_up`)                                         |
| Other `/observe/*`     | Sessions, replay, metrics — see [Observability](../features/observability.md) |

## Static web (`agloom_web`)

Build with **`npm run build`** and serve **`dist/`** from any static host. The browser connects **outbound** to the WebSocket URL baked into **`VITE_AGP_WS_URL`**. Use **wss:** in production.

## Operational notes

- **SQLite**: single-writer; scale out by **one runtime per tenant** or migrate EventStore to a shared backend later.
- **Backups**: snapshot the SQLite files (`agp_events.db`, `.agloom/graph_store.sqlite`, session DBs) per your RPO.
- **Rate limits**: enforce at API gateway; agloom does not replace upstream LLM quotas.

## See also

- [Runtime architecture](../runtime/architecture.md)
- [Runtime CLI](../runtime/cli.md) — `serve` flags, `--ws-token`, `--obs`
- [Protocol (AGP)](../protocol/agp.md)
