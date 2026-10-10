# MEDIA_OWNER_AUDIT

Date: 2026-10-05

| Primitive | Selected mature owner | Version | License | Windows fit / boundary |
|---|---|---|---|---|
| Generative image/video/audio workflow | ComfyUI | 0.38.0 | GPL-3.0 | Windows-capable; packaging/license qualification required |
| Deterministic image edit/convert | ImageMagick | 7.1.2-32 | ImageMagick License | Excellent Windows native |
| Audio/video trim/transcode/mux | FFmpeg | 9.0.2 | LGPL-2.1+ default, GPL-2+ with GPL options | Strong; exact compliant build must be pinned |
| User photo/People/album/tag search | digiKam | 9.1.0 | GPL-2.0+ | Official Windows; read-only integration surface must be qualified |
| Canonical attachment/store/send | ChatterMate | v1.0.25 | Apache-2.0 | Source fit; runtime owned by Window 8 |

## Boundaries

- **No Yance media store.** ChatterMate FileAttachment/file storage remains the adopted-asset authority.
- digiKam is an optional user-managed external media index, never a duplicate Yance library.
- Generated/edited output becomes a ChatterMate attachment only after user/Brain adoption.
- ComfyUI GPL and digiKam GPL distribution boundaries must be reviewed before packaging.

## Rejected alternative

Immich is a strong photo/People/search product, but its AGPL/server/container architecture is a poor match for the zero-container native Windows objective and would create an unnecessary second media-library authority.
