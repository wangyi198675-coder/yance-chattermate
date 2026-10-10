# DETERMINISTIC_MEDIA_INTEGRATION_RESULT

Both deterministic owners pass the Phase-3 Wave-B production admission gate behind an independent executable/CLI boundary.

## ImageMagick

- version: `7.1.2-32 Q16-HDRI x64` (build `ad98b24:20260927`)
- official portable artifact SHA-256: `BAC9155ACAC3147C460082282E01646596C054C613C77E6616F7E3AD0ED38E54`
- resize/crop functional smoke: PASS
- security: 7.1.2-32 is the patched version for the Sep-27-2026 EXR heap-overwrite advisory affecting earlier releases.

## FFmpeg

- qualified Windows artifact: `ffmpeg-n9.0.2-22-g46d8f462ee-win64-lgpl-9.0`
- SHA-256: `F09755A07C2F1E9FCC83171604D08023534870693DA53CF4C6ECAC08B95080B9`
- executable identifies `n9.0.2-22-g46d8f462ee-20261004`
- bundled license: LGPL-3.0; captured build flags explicitly disable GPL codec options including x264/x265/fdk-aac
- functional scale/transcode/trim smoke: PASS

Implementation commit: `88679f3e269bf97e918320d8a385255e3bac7098`.

`external_media_cli.py` is intentionally a thin argv/process boundary. It owns no media catalog/store, no queue, no scheduler, no codec/diffusion implementation, and no `FileAttachment` rows. It returns an output path to the existing ChatterMate attachment/send owner and fails closed with `ExternalMediaUnavailable` when a binary/process/output is unavailable.
