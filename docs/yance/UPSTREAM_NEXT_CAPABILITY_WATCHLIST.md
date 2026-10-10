# UPSTREAM_NEXT_CAPABILITY_WATCHLIST

Date: 2026-10-05

Production baseline remains ChatterMate v1.0.25 / `eea5d62883c7b2130f3466c9c2aad5b1b2bf904e`. The following are **UPSTREAM_NEXT**, not silently backported.

| Item | Current upstream evidence | Why watch | Policy |
|---|---|---|---|
| Unified app-identified Customer upsert | main `068789b` (2026-09-28) | Cleaner canonical Customer path | Wait next stable; selective backport candidate only if materially required |
| Concurrent identify / metadata rewrite protection | main `cdb37a9` | Stronger identity concurrency semantics | Wait next stable or separately tested minimal backport |
| Known-email lead capture behavior | main `8ecff98` | Avoid asking for already-known identity | Wait next stable |
| Knowledge `www` apex fallback | main `78a81bc` | Better website ingest resilience | Wait next stable |
| Disabled-handover truth wording fix | main `4404e61` | Better product-truth semantics | Wait next stable |
| Hosted dashboard support-chat UI | main `ded0979` | Support-oriented presentation, not primary Yance | Do not backport for Yance |
| Agno framework modernization | ChatterMate pins `agno==1.7.6`; current Agno audited at 3.1.1 (2026-10-02) | Security/API/provider maturity and MCP compatibility | High-priority upstream dependency watch; no unilateral Yance upgrade |
| MCP Python SDK 2.x | ChatterMate pins `mcp<2`; MCP 2.0.0 stable 2026-07-28 | New SDK line but tied to Agno compatibility | Upgrade only with ChatterMate/tested dependency wave |
| Baileys v7 | v7.0.0 still RC; selected v6.7.24 stable | Breaking protocol/client changes | Wait formal stable + live qualification |
| digiKam 9.2 | Planned/newer work line after 9.1 | Natural-language media search improvements | Wait formal release; never depend on unreleased feature |
| Graphiti 0.30.x | selected 0.30.2 | Fast-moving retrieval/graph improvements | Pin stable and qualification-test upgrades |
| CosyVoice Windows path | selected capability owner | Windows normalization/install friction | Watch upstream portability; no custom TTS engine |

`SELECTIVE_UPSTREAM_BACKPORTS_IMPLEMENTED = 0`
