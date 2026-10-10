"""Thin CLI boundary for admitted deterministic media owners.

ImageMagick and FFmpeg own transformation mechanics. This module only builds
fixed argv forms, executes an explicitly configured binary, and returns the
result path for the existing ChatterMate FileAttachment flow.
"""
from pathlib import Path
import shutil
import subprocess
from typing import Sequence


class ExternalMediaUnavailable(RuntimeError):
    pass


def image_resize_command(binary: str, source: Path, destination: Path, width: int, height: int) -> list[str]:
    return [binary, str(source), "-resize", f"{int(width)}x{int(height)}", str(destination)]


def image_crop_command(binary: str, source: Path, destination: Path, width: int, height: int, x: int, y: int) -> list[str]:
    return [binary, str(source), "-crop", f"{int(width)}x{int(height)}+{int(x)}+{int(y)}", "+repage", str(destination)]


def image_convert_command(binary: str, source: Path, destination: Path) -> list[str]:
    return [binary, str(source), str(destination)]


def audio_normalize_command(binary: str, source: Path, destination: Path) -> list[str]:
    """Deterministic speech-decode fallback through the admitted FFmpeg owner."""
    return [
        binary, "-hide_banner", "-nostdin", "-y", "-i", str(source),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destination),
    ]


def video_trim_command(binary: str, source: Path, destination: Path, start_seconds: float, duration_seconds: float) -> list[str]:
    return [binary, "-hide_banner", "-nostdin", "-y", "-ss", str(start_seconds), "-i", str(source), "-t", str(duration_seconds), "-c", "copy", str(destination)]


def video_transcode_command(binary: str, source: Path, destination: Path, video_codec: str, audio_codec: str) -> list[str]:
    return [binary, "-hide_banner", "-nostdin", "-y", "-i", str(source), "-c:v", video_codec, "-c:a", audio_codec, str(destination)]


def resolve_external_binary(binary: str) -> str:
    """Resolve a configured owner without invoking a shell."""
    explicit = Path(binary)
    if explicit.is_file():
        return str(explicit)
    resolved = shutil.which(binary)
    if resolved:
        return resolved
    raise ExternalMediaUnavailable(f"external media owner unavailable: {binary}")


def run_external_media(command: Sequence[str], timeout_seconds: int = 120) -> Path:
    if not command:
        raise ExternalMediaUnavailable("external media command is empty")
    resolved = resolve_external_binary(command[0])
    argv = list(command)
    argv[0] = resolved
    binary = Path(resolved)
    destination = Path(argv[-1]) if len(argv) > 1 else None
    try:
        subprocess.run(argv, check=True, capture_output=True, text=True, timeout=timeout_seconds)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExternalMediaUnavailable(f"external media owner failed: {binary.name}") from exc
    if destination is None or not destination.is_file():
        raise ExternalMediaUnavailable("external media owner produced no output artifact")
    return destination
