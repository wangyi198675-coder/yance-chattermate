# YANCE_EXCLUSIVE_CAPABILITY_INTEGRATION_PLAN

# Doctrine gate

This document defines Yance product semantics, not permission to implement custom subsystems. Before any non-UI implementation, apply: `ChatterMate native ? official ChatterMate module/plugin ? latest mature OSS owner ? standard protocol + thin adapter ? minimal Yance glue`. If custom code is still proposed, a `NO_MATURE_UPSTREAM_OWNER_FOUND` receipt is mandatory first.

1. **Person identity** — extend canonical `Customer` with `PersonIdentity`; reuse existing Customer merge pointer and ChannelConversation customer linkage.
2. **Girlfriend Brain** — natural-language intent/scope resolver that delegates to existing agents/workflow/tools/models/channels. It owns no duplicate persistence for contacts/messages/models/memory/send/route.
3. **Reply Brain** — thin orchestration layer over mature generation/model/tool/channel owners. Enforce real 0–3 candidates, optional expansion to 5, no filler, stale invalidation/recompute, no_reply/defer and Truth/Permission/Human-Likeness gates before Composer adoption.
4. **Relationship intelligence** — intelligence tables/projections keyed to Customer, backed by conversation evidence/provenance. Confirmed facts and inference remain distinct.
5. **Persona / Learning** — stable persona + corrections + scoped feedback + promotion/rollback + no-learn-this-turn; final learning side effect is bound to Send & Learn.
6. **Temporal/open-loop intelligence** — important dates, promises, goals, open loops and temporal context keyed to Customer and evidence, not a second Person owner.
7. **Yance presentation** — Vue layer under `frontend/src/yance`, reading mature upstream services through adapters. Primary and secondary frozen authorities define all visible product interactions.
8. **Personal social** — transport adapters only. Business-channel support is kept but never relabeled as personal-account semantics.

Selection rule for every capability: `ChatterMate latest native → latest mature OSS owner → thin Yance adapter → custom only as last resort`.
