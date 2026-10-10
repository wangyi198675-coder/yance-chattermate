from pathlib import Path
import importlib
import sys
import types
import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_APP_ROOT = _BACKEND_ROOT / "app"
for name, path in {"app": _APP_ROOT, "app.services": _APP_ROOT / "services"}.items():
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]
        sys.modules[name] = pkg


def test_imagemagick_commands_are_narrow_argv_only(tmp_path):
    m=importlib.import_module("app.services.external_media_cli")
    src=tmp_path/"in.png"; dst=tmp_path/"out.png"
    cmd=m.image_resize_command("magick.exe", src, dst, 320, 240)
    assert cmd == ["magick.exe", str(src), "-resize", "320x240", str(dst)]
    assert m.image_crop_command("magick.exe", src, dst, 10, 20, 3, 4) == ["magick.exe", str(src), "-crop", "10x20+3+4", "+repage", str(dst)]


def test_ffmpeg_commands_are_narrow_argv_only(tmp_path):
    m=importlib.import_module("app.services.external_media_cli")
    src=tmp_path/"in.mp4"; dst=tmp_path/"out.mp4"
    assert m.video_trim_command("ffmpeg.exe", src, dst, 1.25, 3.5) == ["ffmpeg.exe", "-hide_banner", "-nostdin", "-y", "-ss", "1.25", "-i", str(src), "-t", "3.5", "-c", "copy", str(dst)]
    assert m.video_transcode_command("ffmpeg.exe", src, dst, "libx264", "aac")[-5:] == ["-c:v", "libx264", "-c:a", "aac", str(dst)]


def test_external_media_execution_fails_closed_when_binary_missing(tmp_path):
    m=importlib.import_module("app.services.external_media_cli")
    with pytest.raises(m.ExternalMediaUnavailable):
        m.run_external_media([str(tmp_path/"missing.exe"), "--version"])


def test_adapter_has_no_store_queue_or_shell_execution():
    source=(Path(__file__).parents[1]/"app/services/external_media_cli.py").read_text(encoding="utf-8-sig")
    for forbidden in ["shell=True", "FileAttachment(", "create_task(", "Queue(", "redis", "celery"]:
        assert forbidden not in source
