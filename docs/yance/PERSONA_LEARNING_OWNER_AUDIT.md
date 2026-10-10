# PERSONA_LEARNING_OWNER_AUDIT

Date: 2026-10-05

## Decision

The current Persona must remain **ChatterMate `Agent.instructions`**. Yance may define Send & Learn, no-learn-this-turn, correction, scope and promotion semantics, but must not create a Persona database or generic learning engine.

For revision history and rollback, select **SQLAlchemy-Continuum 1.8.0** as a narrow history primitive attached to existing canonical Agent rows.

| Candidate | Release | License | Windows/API fit | Role | Decision |
|---|---|---|---|---|---|
| ChatterMate Agent.instructions | 2026-09-23 | Apache-2.0 | Native source owner | Canonical current Persona state | SELECT primary |
| SQLAlchemy-Continuum 1.8.0 | 2026-09-29 | BSD-3-Clause | OS-independent SQLAlchemy instrumentation | Version/history/rollback mechanics over selected Agent fields | SELECT primitive |
| SQLAlchemy-History 2.1.6 | 2026-08-26 | Apache-2.0 AND BSD-3-Clause | OS-independent; asyncio/alembic extras | Alternative SQLAlchemy history/versioning | REJECT only because Continuum is selected; remains fallback |
| Langfuse 4.47.0 | 2026-09-29 | MIT core; enterprise boundary separate | API/SDK plus substantial self-host runtime | Prompt management/version/labels/rollback platform | REJECT as owner: introduces second prompt registry/runtime |
| Letta Code 0.34.2 | 2026-10-04 | Apache-2.0 | Windows desktop; Node/Bun; App Server/SDK | Stateful agent/memory/persona runtime | REJECT: duplicates ChatterMate agent authority |

## Learning evidence

- Successful send: ChatterMate `ChatHistory` + channel `SendResult`.
- Positive/negative explicit feedback: ChatterMate `Rating` and candidate interaction evidence.
- Current-turn correction / do-not-learn: transient Yance semantics; do not persist unless explicit promotion succeeds.
- Promotion target: canonical `Agent.instructions`.
- Rollback/review: Continuum revision history; current state never moves into a new registry.
- Truth/provenance input: Graphiti-derived evidence + ChatterMate guardrails.

## Rejected duplicate-owner pattern

Langfuse prompt management is mature, but making it the active Persona registry would introduce independent prompt state and substantial runtime surface. Letta now owns too much of the agent/conversation/memory stack to fit the thin-owner boundary.

`PERSONA_CURRENT_OWNER = CHATTERMATE_AGENT`

`PERSONA_VERSIONING_PRIMITIVE = SQLALCHEMY_CONTINUUM_1_8_0`
