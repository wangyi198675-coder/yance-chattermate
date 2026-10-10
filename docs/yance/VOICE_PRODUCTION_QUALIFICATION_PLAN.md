# VOICE_PRODUCTION_QUALIFICATION_PLAN

No Wave-D integration in this batch.

Qualification order:

1. `whisper.cpp 1.9.4`: exact Windows artifact/source provenance, ASR accuracy smoke, streaming/input formats, CPU/GPU fallback, crash/unavailable behavior.
2. `CosyVoice3 Fun-CosyVoice3-0.5B-2512`: native Windows install, model provenance/hash/license, multilingual/zero-shot clone/stream/preview/regenerate, GPU/CPU/resource behavior.
3. if CosyVoice is not mature on Windows, qualify `Chatterbox 0.1.7` as the mature fallback instead of patching/forking CosyVoice.
4. all generated audio returns only as an artifact for ChatterMate `FileAttachment`/send; no second media store.
5. capture update/rollback and security/advisory state before admission.

No Yance ASR/TTS/voice-cloning engine is permitted.
