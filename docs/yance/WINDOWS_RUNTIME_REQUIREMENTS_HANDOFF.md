# WINDOWS_RUNTIME_REQUIREMENTS_HANDOFF

This is a source/application requirements handoff only. Packaging decisions belong to the Windows Zero-Container Runtime workstream.

## Application requirements inherited from ChatterMate v1.0.25

- Python 3.12+ application runtime for FastAPI backend and workers.
- PostgreSQL 14+ and vector extension compatibility.
- Redis-compatible service where required by rate limiting / multi-process realtime deployment.
- Node build toolchain for Vue/Vite frontend; production runtime may serve built static assets without Node if the runtime authority chooses that topology.
- Persistent writable storage for uploads/media where local storage is selected.
- Outbound HTTPS/DNS access for configured AI providers and connected messaging/integration providers.
- WebSocket/Socket.IO compatible reverse-proxy path for realtime conversations.
- Environment/secret injection for database, encryption/auth secrets, AI provider keys and channel credentials.
- Ability to execute Alembic migrations before/at controlled backend startup.
- Long-running worker process support for upstream worker roles that remain enabled.

## Yance additions in this source workstream

- `PersonIdentity` adds one additive PostgreSQL table and indexes/foreign keys; no extra database product.
- Personal-social adapters may require long-lived authenticated sessions; exact session storage/crypto belongs to each adapter and runtime authority.
- Yance presentation is a Vue/Vite build and does not require a second frontend runtime.

## Explicitly out of scope here

Memurai packaging, PostgreSQL Windows packaging, service supervision, installer, Yance.exe lifecycle, crash restart, update distribution and credential migration are not designed or modified by this source branch.
