# Roadmap (not normative)

This file collects **directional** ideas that were removed from published architecture pages so user-facing docs stay focused on **what ships today**. Nothing here is a commitment or schedule.

## Web workspace (`agloom_web`)

- Richer session list / resume UX (store already handles `session.resumed`).
- Token and latency dashboards; cost views; model comparison.
- Optional workflow builder (editable graph → invoke).
- Multi-runtime connections from one SPA.
- Collaboration / presence (would extend AGP).
- Hosted control plane and remote runtime provisioning.

## Runtime (`agloom-runtime`)

- Additional worker transports (subprocess, remote HTTP/WS, brokers).
- Redis / Postgres-backed scheduling and registry.
- GPU / embedding / browser automation workers (where security model allows).
- Kubernetes-style scaling and coordination services.

## Observability

- PostgreSQL or columnar backends for high-volume traces.
- Optional OpenTelemetry export and JWT-protected APIs.

## Protocol

- Distributed task routing across multiple runtime nodes while keeping the same AGP envelope shapes.

---

For current behavior, see **Architecture** and **Protocol** sections in MkDocs.
