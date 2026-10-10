# ChatterMate → Yance Clean Whole-Product Rebase Design

Date: 2026-10-05

## Authority

- Mother project: ChatterMate.
- Upstream stable baseline: v1.0.25, commit `eea5d62883c7b2130f3466c9c2aad5b1b2bf904e`.
- Primary UI authority: `GLOBAL_UI_DESIGN_01_RC3_FINAL_PRODUCT_RENDER_FIDELITY_PARITY_20261004`, registry SHA-256 `5be68b72e1afc027590cdef271e2cf10cd09140aaff6fee5aca9c1b9c1a50213`.
- Secondary interaction authority: `GLOBAL_UI_DESIGN_01_RC3_SECONDARY_INTERACTION_FINAL_HOLD_CORRECTION_20261005`, registry SHA-256 `fb64957cb15ec0ceefc9b35e3b2af9b86de8cb8faf91017c0a3535133fac58d6`.
- Frozen design coverage is 152/152 capabilities and 100/100 visible interactions. Design coverage is not runtime GREEN.
- Old Yance source/runtime is non-authoritative and is not a default port source.

## Global Engineering Doctrine Override

`YANCE_REBUILD_DOCTRINE = NO_CUSTOM_BY_DEFAULT`. For every non-UI capability the binding acquisition order is: ChatterMate stable native ? official/latest ChatterMate module/plugin ? latest strongest mature OSS subsystem ? standard protocol + thin adapter ? minimal Yance glue only if absolutely unavoidable. Any proposed custom non-UI subsystem requires a prior `NO_MATURE_UPSTREAM_OWNER_FOUND` evidence receipt.

## Architecture

Yance is a clean fork/rebase of ChatterMate, not a reconstruction of the retired Yance runtime. ChatterMate remains the owner of mature backend primitives: conversations, inbox, Customer/People, channels, handoff, agents, models, workflow, knowledge, MCP/tools, notifications, translation, CRM primitives and media/file transport. Yance adds a thin presentation/integration layer plus narrowly-scoped schema/intelligence extensions.

The product surface is a Yance-only presentation layer over mature upstream owners. Enterprise/support-specific ChatterMate presentation is de-presented rather than deleting reusable backend capability. No Frozen authority artifact is copied into executable UI as annotation/spec text.

## Canonical person authority

`Customer` remains the canonical Person owner. Yance adds `PersonIdentity` as a thin identity table linked to Customer and, when applicable, ChannelAccount. It stores typed external identities, provenance, lifecycle state and stale-identity redirect. `ChannelConversation.customer_id` continues to link conversations to the canonical Customer. Person merge/dedupe always selects a surviving Customer; stale PersonIdentity rows redirect to their surviving identity/Customer and never become a second CRM.

## Yance presentation layer

Create a separate `frontend/src/yance` surface with thin adapters into existing services/stores. Core shell surfaces are Home, Conversation, Relationship World, Settings and shared overlays. Conversation preserves the frozen layout contract: left contact rail, center timeline, Reply Brain collapsed by default, Girlfriend Brain off by default, composer `+ / 发送消息… / 真人打字·自然 ▾ / 发送并学习 ▾`, and header order `返回首页 → 联系人 → 人格 → 回复模式 → 模型/推理 → 闺蜜大脑 → Windows controls`.

The first foundation commit only establishes shell structure and routing; it must not present placeholder data as real state or claim runtime capability GREEN.

## Yance-exclusive intelligence

Girlfriend Brain is an intent/scope orchestrator: it decides WHO/WHAT owner to invoke, while mature owners decide HOW. It owns no duplicate contacts/messages/models/memory/send/route stores.

Reply Brain is an adapter over mature generation/orchestration owners. Contract: 0–3 default candidates, real expansion to max 5, no filler, text/voice/image/photo/video/file actions, stale/new-inbound invalidation, recompute, no_reply/defer, Truth/Permission/Human-Likeness gates and final Send & Learn authority through the Composer.

Relationship Intelligence, Persona/Learning and temporal/open-loop intelligence are attached above Customer and message history with provenance. They do not replace Person, channel, conversation or model authorities.

## Personal social boundary

Personal transports implement a transport-only interface: connect, disconnect, reconnect, session status, inbound, outbound, receipt, media, backfill, account identity, route, error and health. Transport does not own Person truth, Relationship truth, Persona, Memory or Brain. Business WhatsApp/Telegram Bot/Facebook Page/Instagram Business capabilities are not relabeled as personal-account GREEN.

## Runtime boundary

This source project declares application runtime requirements only. Windows zero-container packaging, Memurai/PostgreSQL packaging, supervisor, installer, executable lifecycle and crash restart belong to the separate runtime authority.

## Verification

Every production behavior added in this branch receives a failing test first. Upstream history is preserved; changes are small, traceable commits. No production deploy, credential operation, Docker/WSL cleanup or old Yance mutation occurs in this workstream.
