from __future__ import annotations

import ast
from pathlib import Path
import unittest


REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
GEN = BACKEND / "app/services/generative_media.py"
DET = BACKEND / "app/services/deterministic_media.py"
API = BACKEND / "app/api/generative_media.py"
EXT = BACKEND / "app/services/external_media_cli.py"
CONFIG = BACKEND / "app/core/config.py"
MAIN = BACKEND / "app/main.py"
WIDGET = BACKEND / "app/api/widget_chat.py"
DELIVERY = BACKEND / "app/services/message_delivery.py"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


class Window41GenerativeMediaContract(unittest.TestCase):
    def test_changed_python_parses(self):
        for path in (GEN, DET, API, EXT, CONFIG, MAIN):
            ast.parse(text(path), filename=str(path))

    def test_fresh_provider_defaults_and_sdk_pins(self):
        config = text(CONFIG)
        requirements = text(BACKEND / "requirements.txt")
        self.assertIn('"gpt-image-2.5-flare"', config)
        self.assertIn('"gpt-image-2.5-sunburst"', config)
        self.assertIn('"gen4.5"', config)
        self.assertIn('"aleph2"', config)
        self.assertIn("openai==3.24.0", requirements)
        self.assertIn("runwayml==5.21.0", requirements)

    def test_openai_outputs_enter_only_canonical_attachment_flow(self):
        source = text(GEN)
        self.assertIn("client.images.generate(", source)
        self.assertIn(".images.edit(**kwargs)", source)
        self.assertIn("FileUploadService.store_bytes(", source)
        self.assertIn("FileAttachmentRepository(db).create_attachment(", source)
        self.assertIn("source_attachment_ids", source)
        self.assertIn("mask_attachment_id", source)
        self.assertNotIn("class GeneratedAsset", source)
        self.assertNotIn("__tablename__", source)

    def test_runway_provider_task_is_async_authority_without_local_queue(self):
        source = text(GEN)
        self.assertIn("client.text_to_video.create(", source)
        self.assertIn("client.image_to_video.create(", source)
        self.assertIn(".video_to_video.create(", source)
        self.assertIn(".uploads.create_ephemeral(", source)
        self.assertIn(".tasks.retrieve(task_id)", source)
        self.assertIn("make_runway_task_handle", source)
        self.assertIn("organization_id", source)
        for forbidden in (
            "asyncio.create_task(",
            "Celery",
            "celery",
            "Queue(",
            "job DB",
            "__tablename__",
        ):
            self.assertNotIn(forbidden, source)

    def test_runway_output_is_materialized_not_exposed_as_provider_url(self):
        service = text(GEN)
        api = text(API)
        self.assertIn('task["status"] != "SUCCEEDED"', service)
        self.assertIn('response = await client.get(output_url)', service)
        self.assertIn("FileUploadService.store_bytes(", service)
        status_block = api[api.index("async def video_task_status"):api.index("@router.post(\"/video/tasks/{task_handle}/materialize\")")]
        self.assertIn('"output_ready"', status_block)
        self.assertNotIn('"output":', status_block)
        self.assertNotIn("output_url", status_block)

    def test_deterministic_tools_stay_thin_and_canonical(self):
        source = text(DET)
        external = text(EXT)
        self.assertIn("image_resize_command(", source)
        self.assertIn("video_transcode_command(", source)
        self.assertIn("FileUploadService.store_bytes(", source)
        self.assertIn("FileAttachmentRepository(db).create_attachment(", source)
        self.assertIn("subprocess.run(argv", external)
        self.assertNotIn("shell=True", external)
        for forbidden in ("YanceMediaManager", "__tablename__", "asyncio.create_task("):
            self.assertNotIn(forbidden, source)

    def test_backend_images_install_deterministic_owners(self):
        for dockerfile in (REPO / "Dockerfile", REPO / "Dockerfile.backend.prod"):
            source = text(dockerfile)
            self.assertIn("imagemagick", source)
            self.assertIn("ffmpeg", source)

    def test_preview_adopt_send_authority_remains_window36_native(self):
        widget = text(WIDGET)
        delivery = text(DELIVERY)
        self.assertIn("adopt_attachments(", widget)
        self.assertIn("deliver_to_customer(", widget)
        self.assertIn("get_adapter(channel)", delivery)
        self.assertIn("adapter.send_media(", delivery)
        self.assertIn('"provider_delivery"', delivery)
        self.assertIn('"external_message_id"', delivery)
        source = text(GEN) + text(DET) + text(API)
        for forbidden in (
            "send_to_messenger",
            "send_to_whatsapp",
            "send_to_telegram",
            "ChannelAdapter.send_media",
            "adapter.send_media",
            "YanceMediaManager",
        ):
            self.assertNotIn(forbidden, source)

    def test_no_second_asset_or_delivery_owner_added(self):
        source = text(GEN) + text(DET) + text(API)
        for forbidden in (
            "GeneratedAsset",
            "MediaAsset",
            "AssetRepository",
            "DeliveryEngine",
            "MediaQueue",
            "polling daemon",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
