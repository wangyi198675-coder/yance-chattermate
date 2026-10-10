# RELATIONSHIP_MEMORY_BEST_OF_BREED_AUDIT

Date: 2026-10-05

## Decision

**Selected durable relationship/memory owner:** Graphiti 0.30.2.

**Selected Windows-suitable graph backend candidate:** Neo4j Community 2026.09.0. Runtime packaging/service ownership remains entirely with Window 8.

**Canonical source boundaries:** ChatterMate `Customer` remains Person identity authority; `ChatHistory` remains message/history authority. Graphiti stores only derived relationship facts, episodes, temporal validity and provenance linked back to those canonical sources.

| Candidate | Release | License | Windows fit | Strength | Decision |
|---|---|---|---|---|---|
| Graphiti 0.30.2 | 2026-09-08 | Apache-2.0 | Python neutral; backend separate | Temporal facts, episodes, provenance, graph+semantic retrieval | SELECT |
| Neo4j Community 2026.09.0 | 2026-09-21 | GPLv3 | Official native Windows | Mature Cypher/Bolt graph storage, vector/full-text | SELECT as Graphiti graph backend; Window8 packages |
| Mem0 2.2.1 | 2026-09-25 | Apache-2.0 | Cross-platform | Generic agent memory | REJECT primary: less relationship/temporal-specific; risks second memory authority |
| Cognee 1.6.2 | 2026-09-29 | Apache-2.0 | Cross-platform | Broad memory/data graph pipeline | REJECT primary: beta and broader overlapping runtime |
| Letta Code 0.34.2 | 2026-10-04 | Apache-2.0 | Desktop/cross-platform | Stateful agent harness with memory/identity/experience | REJECT: duplicates ChatterMate agent/conversation/identity authority |
| FalkorDBLite 0.10.0 | 2026-05-02 | BSD-3-Clause | Poor: Linux/macOS wheels; Windows via WSL | Embedded graph option | REJECT for zero-container native Windows |

## Ownership decomposition

- Confirmed/stable facts, notes, events, interests, open loops, promises, important dates, relationship stage/history and source-linked episodic recall: Graphiti-derived graph.
- Relationship momentum/risk/temperature/next-best-action: **Yance product semantic only**, computed from Graphiti evidence by the existing ChatterMate model runtime.
- Person merge/dedupe/identity: ChatterMate Customer/People + the already-admitted thin PersonIdentity extension. Graphiti never merges Persons.
- Raw messages: ChatterMate ChatHistory only. Graphiti stores source references/episodes, not a second message store.

## License / maintenance boundary

Graphiti is Apache-2.0. Neo4j Community is GPLv3; the external graph database license and distribution boundary must remain explicit in Window 8. This Phase 2 decision is an owner mapping, **not runtime GREEN**.

## Verdict

`RELATIONSHIP_MEMORY_OWNER = GRAPHITI_0_30_2`

`GRAPH_BACKEND_CANDIDATE = NEO4J_COMMUNITY_2026_09_0`
