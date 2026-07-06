# Observability metrics and probes

When the runtime is started with **`agloom-runtime serve --obs`**, a small FastAPI app is mounted at **`http://127.0.0.1:<obs-port>/observe`** (default port **8766**).

## Probes

| Route | Role |
| --- | --- |
| **`GET /observe/healthz`** | **Liveness** — process is up and serving HTTP. |
| **`GET /observe/readyz`** | **Readiness** — observability SQLite store answers a trivial query (returns **503** if the DB is broken or locked). |

Use **`healthz`** for “is the sidecar listening?” and **`readyz`** for “can we query stored sessions?” before routing dashboard traffic.

## Prometheus

| Route | Role |
| --- | --- |
| **`GET /observe/metrics`** | Minimal **Prometheus** exposition (`text/plain; version=0.0.4`). Currently exports **`agloom_up`** as a gauge set to **1** when the handler runs. |

Scrape interval: align with your platform defaults (often 15–60s). Expand this endpoint with counters and histograms as you wire more telemetry.

## OpenTelemetry (runtime process)

The runtime accepts **`--otel`** on **`serve`** (stdio and WebSocket). Install optional dependencies:

```bash
pip install 'agloom[otel]'
```

Then either set a collector endpoint, for example:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
agloom-runtime serve --transport=stdio --otel
```

If no OTLP endpoint is set, spans are printed to **stderr** via the console exporter (development only).

## See also

- [Runtime CLI](../runtime/cli.md) — `--obs`, `--obs-port`, `--otel`
- [Deployment](deployment.md) — reverse proxy and health checks
- [Observability API (Python)](observability-python.md) — store and router
