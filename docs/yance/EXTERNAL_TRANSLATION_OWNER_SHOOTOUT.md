# EXTERNAL_TRANSLATION_OWNER_SHOOTOUT

## Decision

`TRANSLATION_EXECUTION_OWNER = NO_OWNER_SELECTED`

`PHASE3B_TRANSLATION_VERDICT = HOLD_OWNER_PRODUCTION_QUALIFICATION`

Argos Translate 1.11.0 remains rejected and was not patched. No Yance translation engine was created.

## Candidate: CTranslate2 4.8.2 + OPUS-MT / Marian

Runtime admission facts:

- CTranslate2 `4.8.2`, MIT, Production/Stable.
- Windows CPython 3.12 x64 wheel SHA-256: `d94421d565d0de61c032998f737a18942b0f2bef40c0424b1846ec6f67300105`.
- SentencePiece `0.2.2`; Windows CPython 3.12 x64 wheel SHA-256: `7c6e7bf684dc12145bfa685d3060beaea55139134ba848289bee514ed42e7383`.
- Clean private Python 3.12.15 venv install PASS.
- CTranslate2 CPU compute types available: int8, int8_float32, int16, float32.
- Official OPUS-MT converter path works without Transformers/PyTorch at runtime.
- `Helsinki-NLP/opus-mt-en-zh` original Marian archive converted successfully to CTranslate2 int8.

Mandatory integrity pilot failed. With correct Marian target token `>>cmn_Hans<<`, real inference produced usable semantic translation but violated protected content requirements:

1. URL `https://example.com/pay?id=12345` was changed to a form containing whitespace.
2. `$1,234.56` was rewritten to `1234. 56` plus a translated currency word.
3. `@alice` was dropped.
4. emoji was dropped.
5. paragraph structure was flattened.

A second sample preserved another URL and date but still omitted mention/emoji. Therefore the candidate cannot satisfy the required URL/number/currency/mention/emoji/paragraph integrity contract without adding additional custom protection/repair logic. Phase 3B explicitly forbids solving the gate by inventing a Yance translator/tokenizer/sentence splitter, so the OPUS set is not admitted.

The six required OPUS model IDs, revisions, licenses, sizes and published benchmarks are recorded in `TRANSLATION_MODEL_CATALOG.csv`. The remaining five large Marian artifacts were not downloaded after the mandatory en->zh direction produced a decisive integrity failure; this avoids unnecessary qualification/runtime surface while preserving exact candidate evidence.

## Candidate: facebook/m2m100_418M

- Exact revision: `55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636`.
- MIT.
- 101 languages including de/en/zh.
- Hugging Face tree is about 3.88 GB, with ~1.94 GB primary PyTorch weights plus an additional Rust weight copy.
- Public paper/table evidence does not show a decisive Chinese advantage: WMT19 English->Chinese is reported at 33.2 BLEU versus a cited published 38.2 baseline, Chinese->English 29.0 versus 29.1, while German->English improves to 40.1 versus 39.2.
- CTranslate2 supports M2M100, but conversion introduces a materially thicker acquisition/conversion surface than the OPUS runtime that already failed the mandatory integrity pilot.

Result: `REJECTED_SHOOTOUT_NOT_DECISIVELY_SUPERIOR_FOR_YANCE_CORE` for this wave. No 1.94 GB model download was performed merely to chase the gate.

## Candidate: facebook/nllb-200-distilled-600M

- Exact revision: `f8d333a098d19b4fd9a8b18f94170487ad3f821d`.
- License: CC-BY-NC-4.0.
- Model card states research-oriented use and says it is not released for production deployment.

Result: `REJECTED_LICENSE_AND_PRODUCTION_BOUNDARY`.

## Candidate: google/madlad400-3b-mt

- Exact revision: `fa184c675da0b5c9e1c8694fccd4e12e2d422094`.
- Apache-2.0.
- 400+ languages, but current Hugging Face tree is about 15.7 GB; main safetensors weights are about 11.8 GB.

Result: `REJECTED_RUNTIME_SURFACE_FOR_CURRENT_WINDOWS_YANCE` absent evidence of a decisive benefit that justifies this much larger local model/runtime surface.

## Same-language no-op

Same-language no-op remains a product contract: if source and requested target are the same, no translator should run and the draft must remain byte-for-byte unchanged. This does not create a translation engine.

## Integrity outcome

Because no candidate completed all mandatory de/zh/en + integrity gates, there is no production translation owner. Preview remains non-sendable for unadmitted translation, and the native ChatterMate send path remains untouched.
