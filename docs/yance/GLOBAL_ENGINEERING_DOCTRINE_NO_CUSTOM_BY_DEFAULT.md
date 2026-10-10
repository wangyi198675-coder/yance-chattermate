# YANCE GLOBAL ENGINEERING DOCTRINE ? NO CUSTOM BY DEFAULT

Effective: 2026-10-05

## Binding rule

`YANCE_REBUILD_DOCTRINE = NO_CUSTOM_BY_DEFAULT`

Every capability must use this acquisition order:

1. ChatterMate latest suitable stable native capability.
2. ChatterMate official/latest mature module or plugin.
3. Latest strongest mature OSS subsystem.
4. Standard protocol plus thin adapter.
5. Minimal Yance glue only when absolutely unavoidable.

No worker may skip directly to a Yance-owned subsystem.

## Mandatory pre-code gate for non-UI subsystems

Before adding any non-UI subsystem implementation, create a `NO_MATURE_UPSTREAM_OWNER_FOUND` evidence receipt that records:

- searched alternatives;
- latest suitable stable versions;
- current maintenance state;
- capability breadth;
- security posture relevant to the use case;
- Windows compatibility;
- license boundary;
- API/extension surface;
- why each candidate is unsuitable;
- why standard protocol + thin adapter cannot satisfy the requirement.

If this receipt cannot be proven, custom implementation is not admitted.

## Authority prohibition

Yance must not create a second Contact DB, CRM, Message Store, Conversation Store, Model Registry, Memory Engine, Persona Engine, Learning Engine, Translation Engine, Workflow Engine, Scheduler, Queue, Media Store, Route owner, Send owner, Account lifecycle owner, or generic event bus. Adapters connect owners; adapters do not become owners.

## Runtime prohibition

Zero-container does not authorize rebuilding infrastructure. PostgreSQL, pgvector, Redis-compatible runtime, ASGI/HTTP serving, process supervision, Windows service management, installer/update engines, backup/restore, logging, credential storage, crash recovery and diagnostics transport must use mature owners wherever possible. Yance runtime is limited to thin orchestration, configuration and branded entry.

## Yance-exclusive semantics

Girlfriend Brain, Reply Brain, Relationship Intelligence, Persona/Learning and Human-Likeness may define Yance product semantics, contracts and projections, but their implementation primitives must be delegated to mature owners wherever possible.

## 152 ledger

`152 = MINIMUM PRODUCT REQUIREMENT LEDGER`, not an old-source migration list. The target is `NEW_YANCE_CAPABILITIES >= 152`, with mature ChatterMate/OSS capabilities absorbed when useful.

## Optimization targets

- `CUSTOM_CODE_SURFACE = MINIMIZED`
- `UPSTREAM_REUSE = MAXIMIZED`
- `CAPABILITY_COUNT = EXPANDED`
- `UPSTREAM_VERSIONS = CURRENT`
- `MAINTENANCE_SURFACE = REDUCED`
- `SHADOW_AUTHORITY = ZERO`
- `DUPLICATE_INFRASTRUCTURE = ZERO`
- `NEW_YANCE_CAPABILITY >= OLD_YANCE`
- `NEW_YANCE_STABILITY > OLD_YANCE`
