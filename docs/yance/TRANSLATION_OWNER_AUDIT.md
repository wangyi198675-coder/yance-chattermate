# TRANSLATION_OWNER_AUDIT

Date: 2026-10-05

## Selected owner composition

- **Translation:** Argos Translate 1.11.0 — MIT/CC0, stable local Python translation primitive.
- **Language detection / integrity signal:** Lingua 2.2.0 — Apache-2.0, Production/Stable, Windows wheels available.
- **Canonical original text:** ChatterMate ChatHistory.
- **Durable contact-language fact / provenance when appropriate:** Graphiti.
- **Final send:** ChatterMate ChannelAdapter/message delivery.

## Yance-owned semantic only

`final draft → translate → preview → integrity validation → fail closed → native send`

Yance does not own a translation engine. Integrity checks include source/target detection consistency, empty/truncated output checks and explicit failure propagation.

## Alternative rejected

LibreTranslate is capable but wraps Argos in an additional AGPL network service. Direct Argos + Lingua is thinner for this private zero-container Windows product and avoids an unnecessary translation server authority.

`TRANSLATION_ENGINE_OWNER = ARGOS_TRANSLATE_1_11_0`

`LANGUAGE_DETECTION_OWNER = LINGUA_2_2_0`
