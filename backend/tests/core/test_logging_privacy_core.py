import importlib.util
import io
import logging
import os
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch


LOGGER_PATH = Path(__file__).resolve().parents[2] / 'app' / 'core' / 'logger.py'
_ORIGINAL_LOG_RECORD_FACTORY = logging.getLogRecordFactory()


def _load_logger_module():
    spec = importlib.util.spec_from_file_location('window140_logger_under_test', LOGGER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError('Unable to load logger module for focused privacy tests')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _DangerousObject:
    def __repr__(self):
        return "SECRET_CANARY_FROM_REPR"


class LoggingPrivacyCoreTests(unittest.TestCase):
    def setUp(self):
        logging.setLogRecordFactory(_ORIGINAL_LOG_RECORD_FACTORY)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(
            os.environ,
            {
                "LOCALAPPDATA": self.temp_dir.name,
                "ENVIRONMENT": "production",
            },
            clear=False,
        )
        self.env_patch.start()
        os.environ.pop("LOG_LEVEL", None)
        self.logger_module = _load_logger_module()

    def tearDown(self):
        root = logging.getLogger()
        for handler in list(root.handlers):
            if getattr(handler, "_yance_application_handler", False):
                root.removeHandler(handler)
                handler.close()
        self.logger_module._configured = False
        logging.setLogRecordFactory(_ORIGINAL_LOG_RECORD_FACTORY)
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def _owned_handlers(self):
        return [
            handler
            for handler in logging.getLogger().handlers
            if getattr(handler, "_yance_application_handler", False)
        ]

    def _flush(self):
        for handler in self._owned_handlers():
            handler.flush()

    def _log_text(self):
        self._flush()
        path = Path(self.temp_dir.name) / "Yance" / "logs" / "app.log"
        return path.read_text(encoding="utf-8")

    def test_production_defaults_to_info_and_clamps_debug(self):
        logger = self.logger_module.get_logger("app.window140.default")
        self.assertEqual(logging.getLogger().level, logging.INFO)

        logger.debug("DEBUG_CANARY")
        logger.info("info event")
        text = self._log_text()
        self.assertNotIn("DEBUG_CANARY", text)
        self.assertIn("info event", text)

        os.environ["LOG_LEVEL"] = "DEBUG"
        self.logger_module = _load_logger_module()
        self.logger_module.get_logger("app.window140.clamped")
        self.assertEqual(logging.getLogger().level, logging.INFO)

    def test_development_allows_debug_but_keeps_redaction(self):
        os.environ["ENVIRONMENT"] = "development"
        os.environ["LOG_LEVEL"] = "DEBUG"
        self.logger_module = _load_logger_module()

        logger = self.logger_module.get_logger("app.window140.dev")
        logger.debug("Authorization: Bearer DEV_SECRET_CANARY")
        text = self._log_text()

        self.assertEqual(logging.getLogger().level, logging.DEBUG)
        self.assertNotIn("DEV_SECRET_CANARY", text)
        self.assertIn("[REDACTED]", text)

    def test_fixed_localappdata_root_is_independent_of_cwd(self):
        cwd = os.getcwd()
        other_cwd = Path(self.temp_dir.name) / "arbitrary-cwd"
        other_cwd.mkdir()
        try:
            os.chdir(other_cwd)
            logger = self.logger_module.get_logger("app.window140.cwd")
            logger.info("cwd independent")
            self._flush()
        finally:
            os.chdir(cwd)

        expected = Path(self.temp_dir.name) / "Yance" / "logs" / "app.log"
        self.assertTrue(expected.is_file())
        self.assertFalse((other_cwd / "logs" / "app.log").exists())

    def test_handler_graph_is_single_idempotent_and_rotating(self):
        for index in range(20):
            self.logger_module.get_logger(f"app.window140.{index}")

        handlers = self._owned_handlers()
        self.assertEqual(len(handlers), 2)

        file_handlers = [
            handler for handler in handlers if isinstance(handler, RotatingFileHandler)
        ]
        console_handlers = [
            handler
            for handler in handlers
            if type(handler) is logging.StreamHandler
        ]

        self.assertEqual(len(file_handlers), 1)
        self.assertEqual(len(console_handlers), 1)
        self.assertEqual(file_handlers[0].maxBytes, 10 * 1024 * 1024)
        self.assertEqual(file_handlers[0].backupCount, 5)

    def test_raw_application_logger_is_covered_by_root_redaction(self):
        self.logger_module.get_logger("app.window140.bootstrap")
        raw_logger = logging.getLogger("app.window140.raw")
        raw_logger.info("Authorization: Bearer RAW_LOGGER_SECRET_CANARY")
        text = self._log_text()

        self.assertNotIn("RAW_LOGGER_SECRET_CANARY", text)
        self.assertIn("[REDACTED]", text)

    def test_preexisting_root_handler_only_receives_privacy_safe_record(self):
        logging.setLogRecordFactory(_ORIGINAL_LOG_RECORD_FACTORY)
        capture = io.StringIO()
        handler = logging.StreamHandler(capture)
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            self.logger_module = _load_logger_module()
            logger = self.logger_module.get_logger("app.window150.root-bypass")
            logger.warning("Authorization: Bearer ROOT_BYPASS_CANARY")
            handler.flush()

            text = capture.getvalue()
            self.assertNotIn("ROOT_BYPASS_CANARY", text)
            self.assertIn("[REDACTED]", text)
        finally:
            root.removeHandler(handler)
            handler.close()

    def test_preexisting_named_handler_only_receives_privacy_safe_record(self):
        logging.setLogRecordFactory(_ORIGINAL_LOG_RECORD_FACTORY)
        capture = io.StringIO()
        handler = logging.StreamHandler(capture)
        named = logging.getLogger("app.window150.named-bypass")
        named.addHandler(handler)
        named.setLevel(logging.NOTSET)
        named.propagate = True
        try:
            self.logger_module = _load_logger_module()
            logger = self.logger_module.get_logger(named.name)
            logger.error("password=NAMED_BYPASS_CANARY")
            handler.flush()

            text = capture.getvalue()
            self.assertNotIn("NAMED_BYPASS_CANARY", text)
            self.assertIn("[REDACTED]", text)
        finally:
            named.removeHandler(handler)
            handler.close()

    def test_repeated_import_keeps_single_record_factory_and_owned_output(self):
        self.logger_module.get_logger("app.window150.first")
        first_factory = logging.getLogRecordFactory()

        self.logger_module = _load_logger_module()
        logger = self.logger_module.get_logger("app.window150.second")
        second_factory = logging.getLogRecordFactory()

        self.assertIs(first_factory, second_factory)
        self.assertTrue(
            getattr(second_factory, "_yance_privacy_record_factory", False)
        )
        self.assertEqual(len(self._owned_handlers()), 2)

        logger.info("WINDOW150_SINGLE_OUTPUT_MARKER")
        self.assertEqual(self._log_text().count("WINDOW150_SINGLE_OUTPUT_MARKER"), 1)

    def test_redaction_filter_is_idempotent_across_multiple_handlers(self):
        privacy_filter = self.logger_module.PrivacyRedactionFilter()
        record = logging.LogRecord(
            "app.window140.idempotence",
            logging.ERROR,
            __file__,
            1,
            "operation=%s error=%s status=%d",
            ("PRIVATE_DYNAMIC_CANARY", RuntimeError("PRIVATE_EXCEPTION_CANARY"), 500),
            None,
        )

        self.assertTrue(privacy_filter.filter(record))
        first_args = record.args
        self.assertTrue(privacy_filter.filter(record))
        self.assertEqual(record.args, first_args)

        rendered = record.getMessage()
        self.assertNotIn("PRIVATE_DYNAMIC_CANARY", rendered)
        self.assertNotIn("PRIVATE_EXCEPTION_CANARY", rendered)
        self.assertIn("[REDACTED]", rendered)
        self.assertIn("<RuntimeError>", rendered)
        self.assertIn("status=500", rendered)

    def test_secret_cookie_ciphertext_nested_and_unknown_object_fail_closed(self):
        logger = self.logger_module.get_logger("app.window140.secrets")
        logger.info(
            "safe diagnostic %s %s",
            {
                "authorization": "Bearer AUTH_SECRET_CANARY",
                "encrypted_api_key": "CIPHERTEXT_CANARY",
                "nested": {
                    "cookie": "session=COOKIE_CANARY",
                    "status": 200,
                },
            },
            _DangerousObject(),
        )
        text = self._log_text()

        for canary in (
            "AUTH_SECRET_CANARY",
            "CIPHERTEXT_CANARY",
            "COOKIE_CANARY",
            "SECRET_CANARY_FROM_REPR",
        ):
            self.assertNotIn(canary, text)
        self.assertIn("[REDACTED]", text)
        self.assertIn("<_DangerousObject>", text)

    def test_urls_dsns_and_private_absolute_paths_are_sanitized(self):
        logger = self.logger_module.get_logger("app.window140.urls")
        logger.info(
            "dsn=postgresql://dbuser:DB_PASS_CANARY@localhost/yance?sslmode=require "
            "ordinary=https://urluser:URL_PASS_CANARY@example.test/path?view=1#fragment "
            "signed=https://storage.example.test/file?X-Amz-Signature=SIGNED_CANARY&token=TOKEN_CANARY"
        )
        logger.info(
            r"path=C:\Users\USER CANARY\private attachment.txt status=200"
        )
        text = self._log_text()

        for canary in (
            "dbuser",
            "DB_PASS_CANARY",
            "urluser",
            "URL_PASS_CANARY",
            "SIGNED_CANARY",
            "TOKEN_CANARY",
            "USER CANARY",
            "attachment.txt",
        ):
            self.assertNotIn(canary, text)
        self.assertIn("https://example.test/path", text)
        self.assertIn("[REDACTED_URL]", text)
        self.assertIn("[REDACTED_PATH] status=200", text)

    def test_unlabelled_dynamic_strings_are_fail_closed(self):
        logger = self.logger_module.get_logger("app.window140.dynamic")
        logger.info("received value=%s status=%d", "UNLABELLED_PRIVATE_CANARY", 202)
        text = self._log_text()

        self.assertNotIn("UNLABELLED_PRIVATE_CANARY", text)
        self.assertIn("received value=[REDACTED] status=202", text)

    def test_static_customer_and_media_labels_are_never_logged(self):
        logger = self.logger_module.get_logger("app.window150.customer-media")
        logger.info("customer=CUSTOMER_STATIC_CANARY status=200")
        logger.info("media=MEDIA_STATIC_CANARY status=201")
        text = self._log_text()

        self.assertNotIn("CUSTOMER_STATIC_CANARY", text)
        self.assertNotIn("MEDIA_STATIC_CANARY", text)
        self.assertIn("customer=[REDACTED] status=200", text)
        self.assertIn("media=[REDACTED] status=201", text)

    def test_never_log_context_redacts_message_prompt_provider_form_and_media_bodies(self):
        logger = self.logger_module.get_logger("app.window140.neverlog")
        logger.info("message body=%s status=%d", "MESSAGE_BODY_CANARY", 200)
        logger.info("prompt=%s", "PROMPT_CANARY")
        logger.warning(
            "provider payload=%s status=%d",
            {"arbitrary_field": "PROVIDER_PAYLOAD_CANARY"},
            502,
        )
        logger.error("form data=%s", {"field": "FORM_INPUT_CANARY"})
        logger.info("transcript=%s", "TRANSCRIPT_CANARY")
        text = self._log_text()

        for canary in (
            "MESSAGE_BODY_CANARY",
            "PROMPT_CANARY",
            "PROVIDER_PAYLOAD_CANARY",
            "FORM_INPUT_CANARY",
            "TRANSCRIPT_CANARY",
        ):
            self.assertNotIn(canary, text)
        self.assertIn("status=200", text)
        self.assertIn("status=502", text)

    def test_exception_rendering_keeps_class_not_private_text_or_trace_path(self):
        logger = self.logger_module.get_logger("app.window140.exception")
        try:
            raise RuntimeError(
                r"EXCEPTION_SECRET_CANARY C:\Users\EXCEPTION_USER_CANARY\private.txt"
            )
        except RuntimeError:
            logger.exception("operation failed")

        text = self._log_text()
        self.assertIn("<RuntimeError>", text)
        self.assertNotIn("EXCEPTION_SECRET_CANARY", text)
        self.assertNotIn("EXCEPTION_USER_CANARY", text)
        self.assertNotIn("private.txt", text)


class FrontendProductionPrivacyConfigTests(unittest.TestCase):
    def test_all_production_build_seams_remove_log_debug_info(self):
        repo_root = Path(__file__).resolve().parents[3]
        paths = (
            repo_root / "frontend" / "vite.config.ts",
            repo_root / "frontend" / "vite.widget.config.ts",
            repo_root / "frontend" / "vite.widget.docker.config.ts",
            repo_root / "frontend" / "scripts" / "build-webclient-prod.ts",
        )
        expected = "['console.log', 'console.debug', 'console.info']"

        for path in paths:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn(expected, text)

        main_config = paths[0].read_text(encoding="utf-8")
        self.assertIn("command === 'build'", main_config)
        self.assertIn("mode === 'prod'", main_config)
        self.assertIn("mode === 'production'", main_config)
        self.assertIn("yance-service-worker-production-console-privacy", main_config)
        self.assertIn("buildPlugins:", main_config)


if __name__ == "__main__":
    unittest.main()
