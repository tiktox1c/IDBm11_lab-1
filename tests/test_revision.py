"""Регрессии: доступ к документам, экспорт между дисками, проверка Ollama."""
import errno
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from ai_test_generator.config import TEMP, prepare_temp
from ai_test_generator.extraction import extract, Material
from ai_test_generator.exporting import export_test
import ai_test_generator.generation as generation
from test_core import fixture

prepare_temp()


class DocumentPolicyTests(unittest.TestCase):
    def test_external_document_is_forwarded_to_read_only_reader(self):
        external = Path("C:/Учебные материалы/лекция.pdf").resolve()
        with patch("ai_test_generator.extraction.read_pdf", return_value=Material("лекция.pdf", "CPU")) as reader:
            material = extract(external)
        self.assertEqual(material.text, "CPU")
        self.assertEqual(reader.call_args.args[0], external)

    def test_source_cannot_be_overwritten_even_with_valid_docx_name(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            source = Path(folder) / "source.docx"
            source.write_bytes(b"original source")
            test = {"model": "qwen2.5:1.5b", "source_name": source.name,
                    "source_path": str(source), "questions": [fixture()], "warnings": []}
            with self.assertRaisesRegex(ValueError, "исходный"):
                export_test(test, source)
            self.assertEqual(source.read_bytes(), b"original source")

    def test_export_survives_cross_device_rename_and_cleans_temp(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            target = Path(folder) / "result.json"
            before = set(TEMP.iterdir())
            test = {"model": "qwen2.5:1.5b", "source_name": "fixture",
                    "questions": [fixture()], "warnings": []}
            with patch("ai_test_generator.exporting.os.replace", side_effect=OSError(errno.EXDEV, "different disks")):
                export_test(test, target)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["questions"][0]["answer"], 1)
            self.assertEqual(set(TEMP.iterdir()), before)

    def test_extract_does_not_change_docx_bytes(self):
        from docx import Document
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            path = Path(folder) / "source.docx"
            doc = Document()
            doc.add_paragraph("CPU — процессор")
            doc.save(path)
            before = hashlib.sha256(path.read_bytes()).digest()
            extract(path)
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)


class ModelAvailabilityTests(unittest.TestCase):
    def check(self, replies):
        # Сеть замещается на границе HTTP, само принятие решений остаётся настоящим.
        with patch.object(generation, "request_json", side_effect=replies):
            return generation.check_ollama()

    def test_unavailable_server_does_not_trigger_generation(self):
        if not hasattr(generation, "check_ollama"):
            self.fail("Перед генерацией отсутствует отдельная проверка Ollama")
        calls = []

        def request(route, payload=None, timeout=0):
            calls.append((route, timeout))
            raise URLError(ConnectionRefusedError(10061, "refused"))

        with patch.object(generation, "request_json", side_effect=request):
            status = generation.check_ollama()
        self.assertEqual(status.state, "not_running")
        self.assertEqual(len(calls), 1)
        self.assertLessEqual(calls[0][1], 3)

    def test_missing_model_is_not_ready(self):
        if not hasattr(generation, "check_ollama"):
            self.fail("Проверка наличия модели не реализована")
        status = self.check([{"models": [{"name": "another:latest"}]}])
        self.assertEqual(status.state, "missing")

    def test_inference_probe_must_succeed_for_ready_status(self):
        if not hasattr(generation, "check_ollama"):
            self.fail("Пробный вызов модели не реализован")
        status = self.check([{"models": [{"name": "qwen2.5:1.5b"}]},
                             {"done": True, "response": "ОК"}])
        self.assertEqual(status.state, "ready")
        status = self.check([{"models": [{"name": "qwen2.5:1.5b"}]},
                             {"error": "cannot load model"}])
        self.assertEqual(status.state, "connection_error")

    def test_bad_server_response_is_explained_without_traceback(self):
        if not hasattr(generation, "check_ollama"):
            self.fail("Обработка ответа проверки не реализована")
        status = self.check([{"models": None}])
        self.assertEqual(status.state, "connection_error")
        self.assertNotIn("Traceback", status.message)

    def test_windows_connect_timeout_allows_startup_but_read_timeout_does_not(self):
        with patch.object(generation, "request_json", side_effect=URLError(TimeoutError("connect timeout"))):
            self.assertEqual(generation.check_ollama().state, "not_running")
        with patch.object(generation, "request_json", side_effect=TimeoutError("read timeout")):
            self.assertEqual(generation.check_ollama().state, "connection_error")
