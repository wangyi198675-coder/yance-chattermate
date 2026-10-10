from __future__ import annotations

import asyncio
import base64
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from types import SimpleNamespace
from uuid import UUID, uuid4


BACKEND = Path(__file__).resolve().parents[1]
SERVICE_PATH = BACKEND / "app/services/generative_media.py"


class FakeUploadService:
    calls = []

    @classmethod
    async def store_bytes(cls, content, filename, content_type, org_id):
        cls.calls.append((content, filename, content_type, org_id))
        return {
            "file_url": f"/api/v1/uploads/chat_attachments/{org_id}/{filename}",
            "filename": filename,
            "content_type": content_type,
            "size": len(content),
        }


class FakeRepo:
    attachments = {}
    created = []
    existing = None

    def __init__(self, _db):
        pass

    def get_attachment(self, attachment_id):
        return self.attachments.get(int(attachment_id))

    def create_attachment(self, **kwargs):
        row = SimpleNamespace(id=len(self.created) + 100, **kwargs)
        self.created.append(row)
        return row

    def get_by_filename_and_organization(self, _filename, _organization_id):
        return self.existing


async def fake_load_upload(_stored):
    return b"reference-bytes"


def _package(name, path=None):
    module = types.ModuleType(name)
    if path is not None:
        module.__path__ = [str(path)]
    sys.modules[name] = module
    return module


def load_service():
    for name in [
        "window41_generative_media_under_test",
        "app",
        "app.core",
        "app.core.config",
        "app.models",
        "app.models.file_attachment",
        "app.repositories",
        "app.repositories.file_attachment",
        "app.services",
        "app.services.file_storage",
        "app.services.file_upload_service",
        "openai",
        "runwayml",
    ]:
        sys.modules.pop(name, None)

    app_root = BACKEND / "app"
    _package("app", app_root)
    _package("app.core", app_root / "core")
    _package("app.models", app_root / "models")
    _package("app.repositories", app_root / "repositories")
    _package("app.services", app_root / "services")

    settings = SimpleNamespace(
        SECRET_KEY="window41-test-secret",
        OPENAI_API_KEY="openai-test",
        OPENAI_IMAGE_GENERATION_MODEL="gpt-image-2.5-flare",
        OPENAI_IMAGE_EDIT_MODEL="gpt-image-2.5-sunburst",
        RUNWAYML_API_SECRET="runway-test",
        RUNWAY_VIDEO_GENERATION_MODEL="gen4.5",
        RUNWAY_VIDEO_EDIT_MODEL="aleph2",
    )
    config = types.ModuleType("app.core.config")
    config.settings = settings
    sys.modules["app.core.config"] = config

    model = types.ModuleType("app.models.file_attachment")
    model.FileAttachment = SimpleNamespace
    sys.modules["app.models.file_attachment"] = model

    repo = types.ModuleType("app.repositories.file_attachment")
    repo.FileAttachmentRepository = FakeRepo
    sys.modules["app.repositories.file_attachment"] = repo

    storage = types.ModuleType("app.services.file_storage")
    storage.load_upload = fake_load_upload
    sys.modules["app.services.file_storage"] = storage

    upload = types.ModuleType("app.services.file_upload_service")
    upload.ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
    upload.ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm"}
    upload.MAX_VIDEO_SIZE = 20 * 1024 * 1024
    upload.FileUploadService = FakeUploadService
    sys.modules["app.services.file_upload_service"] = upload

    spec = importlib.util.spec_from_file_location(
        "window41_generative_media_under_test", SERVICE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Window41GenerativeMediaUnit(unittest.TestCase):
    def setUp(self):
        FakeUploadService.calls = []
        FakeRepo.attachments = {}
        FakeRepo.created = []
        FakeRepo.existing = None
        self.service = load_service()
        self.org = uuid4()
        self.user = uuid4()

    def test_openai_result_fail_closed(self):
        good = SimpleNamespace(
            data=[SimpleNamespace(b64_json=base64.b64encode(b"image").decode())]
        )
        self.assertEqual(self.service._openai_result_bytes(good), b"image")
        with self.assertRaises(self.service.GenerativeMediaError):
            self.service._openai_result_bytes(SimpleNamespace(data=[]))
        with self.assertRaises(self.service.GenerativeMediaError):
            self.service._openai_result_bytes(
                SimpleNamespace(data=[SimpleNamespace(b64_json="not-base64!")])
            )

    def test_task_handle_survives_restart_without_job_db_and_is_org_bound(self):
        handle = self.service.make_runway_task_handle(self.org, "task-123")
        # The verifier is stateless: the same handle works after recreating the module.
        reloaded = load_service()
        self.assertEqual(
            reloaded.resolve_runway_task_handle(self.org, handle), "task-123"
        )
        with self.assertRaises(reloaded.GenerativeMediaError):
            reloaded.resolve_runway_task_handle(uuid4(), handle)

    def test_openai_generation_materializes_canonical_fileattachment(self):
        calls = {}

        class Images:
            def generate(self, **kwargs):
                calls.update(kwargs)
                return SimpleNamespace(
                    data=[SimpleNamespace(
                        b64_json=base64.b64encode(b"generated-image").decode()
                    )]
                )

        openai = types.ModuleType("openai")
        openai.OpenAI = lambda api_key: SimpleNamespace(images=Images())
        sys.modules["openai"] = openai

        row = asyncio.run(self.service.generate_openai_image(
            object(),
            organization_id=self.org,
            uploaded_by_user_id=self.user,
            prompt="a small lighthouse",
        ))
        self.assertEqual(calls["model"], "gpt-image-2.5-flare")
        self.assertEqual(row.content_type, "image/png")
        self.assertEqual(FakeUploadService.calls[0][0], b"generated-image")
        self.assertEqual(FakeRepo.created[0], row)

    def test_openai_reference_and_mask_edit_materializes(self):
        FakeRepo.attachments = {
            1: SimpleNamespace(
                id=1, organization_id=self.org, content_type="image/png",
                filename="a.png", file_url="/a.png"
            ),
            2: SimpleNamespace(
                id=2, organization_id=self.org, content_type="image/jpeg",
                filename="b.jpg", file_url="/b.jpg"
            ),
            3: SimpleNamespace(
                id=3, organization_id=self.org, content_type="image/png",
                filename="mask.png", file_url="/mask.png"
            ),
        }
        calls = {}

        class Images:
            def edit(self, **kwargs):
                calls.update(kwargs)
                return SimpleNamespace(
                    data=[SimpleNamespace(
                        b64_json=base64.b64encode(b"edited-image").decode()
                    )]
                )

        openai = types.ModuleType("openai")
        openai.OpenAI = lambda api_key: SimpleNamespace(images=Images())
        sys.modules["openai"] = openai

        row = asyncio.run(self.service.edit_openai_image(
            object(),
            organization_id=self.org,
            uploaded_by_user_id=self.user,
            prompt="keep subject, replace background",
            source_attachment_ids=[1, 2],
            mask_attachment_id=3,
        ))
        self.assertEqual(calls["model"], "gpt-image-2.5-sunburst")
        self.assertEqual(len(calls["image"]), 2)
        self.assertIn("mask", calls)
        self.assertEqual(row.content_type, "image/png")

    def test_runway_generation_uses_text_or_image_native_endpoint(self):
        endpoint_calls = []

        class Endpoint:
            def __init__(self, name):
                self.name = name

            def create(self, **kwargs):
                endpoint_calls.append((self.name, kwargs))
                return SimpleNamespace(id=f"{self.name}-task")

        fake_client = SimpleNamespace(
            text_to_video=Endpoint("text"),
            image_to_video=Endpoint("image"),
            video_to_video=Endpoint("edit"),
        )
        self.service._runway_client = lambda: fake_client

        text_id = asyncio.run(self.service.start_runway_video_generation(
            object(), organization_id=self.org, prompt="waves", ratio="1280:720"
        ))
        self.assertEqual(text_id, "text-task")
        self.assertEqual(endpoint_calls[-1][0], "text")

        FakeRepo.attachments[7] = SimpleNamespace(
            id=7, organization_id=self.org, content_type="image/png",
            filename="ref.png", file_url="/ref.png"
        )

        async def fake_upload(_row):
            return "runway://ephemeral/ref"

        self.service._runway_upload_uri = fake_upload
        image_id = asyncio.run(self.service.start_runway_video_generation(
            object(),
            organization_id=self.org,
            prompt="camera pushes in",
            image_attachment_id=7,
            ratio="1104:832",
        ))
        self.assertEqual(image_id, "image-task")
        self.assertEqual(endpoint_calls[-1][0], "image")
        self.assertEqual(
            endpoint_calls[-1][1]["prompt_image"], "runway://ephemeral/ref"
        )

    def test_runway_video_edit_uses_aleph2(self):
        calls = {}

        class Endpoint:
            def create(self, **kwargs):
                calls.update(kwargs)
                return SimpleNamespace(id="edit-task")

        fake_client = SimpleNamespace(video_to_video=Endpoint())
        self.service._runway_client = lambda: fake_client
        FakeRepo.attachments[9] = SimpleNamespace(
            id=9, organization_id=self.org, content_type="video/mp4",
            filename="clip.mp4", file_url="/clip.mp4"
        )

        async def fake_upload(_row):
            return "runway://ephemeral/clip"

        self.service._runway_upload_uri = fake_upload
        task_id = asyncio.run(self.service.start_runway_video_edit(
            object(),
            organization_id=self.org,
            prompt="make it sunset",
            video_attachment_id=9,
        ))
        self.assertEqual(task_id, "edit-task")
        self.assertEqual(calls["model"], "aleph2")
        self.assertEqual(calls["output_format"], "mp4")

    def test_runway_succeeded_task_materializes_to_fileattachment(self):
        async def fake_task(_task_id):
            return {
                "id": "task-ok",
                "status": "SUCCEEDED",
                "output": ["https://cdn.runway.test/output.mp4"],
            }

        self.service.get_runway_task = fake_task

        class Response:
            headers = {"content-length": "12"}
            content = b"video-output"

            def raise_for_status(self):
                return None

        class Client:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, _url):
                return Response()

        self.service.httpx.AsyncClient = Client
        row = asyncio.run(self.service.materialize_runway_video(
            object(),
            organization_id=self.org,
            uploaded_by_user_id=self.user,
            task_id="task-ok",
        ))
        self.assertEqual(row.content_type, "video/mp4")
        self.assertEqual(row.filename, "runway-task-ok.mp4")
        self.assertEqual(FakeUploadService.calls[-1][0], b"video-output")

    def test_runway_incomplete_task_fails_closed(self):
        async def fake_task(_task_id):
            return {"id": "task-wait", "status": "RUNNING", "output": []}

        self.service.get_runway_task = fake_task
        with self.assertRaises(self.service.ProviderTaskNotReady):
            asyncio.run(self.service.materialize_runway_video(
                object(),
                organization_id=self.org,
                uploaded_by_user_id=self.user,
                task_id="task-wait",
            ))


if __name__ == "__main__":
    unittest.main(verbosity=2)
