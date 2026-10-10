# GRAPHITI_PRODUCTION_QUALIFICATION_PLAN

Current state: `HOLD_OWNER_PRODUCTION_QUALIFICATION`; **no Wave-C wiring**.

Required fresh gate for Graphiti 0.30.2 + Neo4j Community 2026.09.0:

1. reproducible dependency lock using only upstream-supported dependency declarations/workarounds;
2. clean native Windows install and `import graphiti_core` smoke (known `httpx` packaging problem must be resolved upstream/supported, never by private Yance patch);
3. Neo4j separate-process start/connect/health/restart/persistence;
4. episode ingestion + retrieval/query;
5. `GRAPHITI_AUTHORITY_BOUNDARY_TEST`: Person update, merge, message arrival, fact extraction, conflicting fact, temporal supersession, provenance, delete/update propagation, stale graph, unavailable graph;
6. prove `Customer = Person truth` and `ChatHistory = Message truth` remain functional while Graphiti is stopped;
7. explicit GPLv3 Neo4j separate-process/distribution boundary;
8. update/rollback and security review.

Private Graphiti forks or duplicated Yance graph/memory engines are automatic RED.
