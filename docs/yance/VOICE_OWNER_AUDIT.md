# VOICE_OWNER_AUDIT

Date: 2026-10-05

## Selected composition

| Primitive | Selected owner | Version | License | Windows fit | Admission |
|---|---|---|---|---|---|
| ASR / voice input | whisper.cpp | 1.9.4 | MIT | Strong native Windows | READY_FOR_WIRING |
| Multilingual TTS / voice clone / streaming | Fun-CosyVoice3 | 0.5B-2512 | Apache-2.0 | Conditional; optional normalization package is Linux-centric | QUALIFICATION_REQUIRED |
| TTS fallback | Chatterbox TTS | 0.1.7 | MIT | Package portable; upstream tested mainly on Debian | FALLBACK_QUALIFICATION |
| Preview / regenerate | Yance product semantic only | N/A | N/A | N/A | delegates to TTS owner |
| Store/send audio | ChatterMate FileAttachment + ChannelAdapter | v1.0.25 | Apache-2.0 | source fit | native |

## Why this avoids custom

whisper.cpp owns transcription. CosyVoice/Chatterbox own speech synthesis and cloning. ChatterMate owns attachment and send. Yance owns only selection, preview, regenerate, permission and adoption semantics.

CosyVoice is not declared runtime GREEN until a target-Windows wiring wave proves installation, text normalization, streaming and selected acceleration path.
