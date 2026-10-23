"""Сценарии запуска установленной Ollama; настоящие процессы не создаются."""
import unittest
import os
import subprocess
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch


class RuntimeTests(unittest.TestCase):
    def test_project_installation_is_found_without_path_changes(self):
        from ai_test_generator.config import TEMP
        from ai_test_generator.ollama_runtime import find_ollama
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            executable = Path(folder) / "tools" / "Ollama" / "ollama.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"fixture, never executed")
            with patch("ai_test_generator.ollama_runtime.ROOT", Path(folder)), \
                 patch("ai_test_generator.ollama_runtime.shutil.which", return_value=None):
                self.assertEqual(find_ollama(), str(executable))

    def runtime(self):
        try:
            from ai_test_generator.ollama_runtime import OllamaRuntime
            return OllamaRuntime()
        except ImportError:
            self.fail("Автоматическое подключение и запуск Ollama ещё не реализованы")

    def status(self, state):
        from ai_test_generator.generation import ModelStatus
        return ModelStatus(state)

    def test_existing_server_is_reused(self):
        runtime = self.runtime()
        with patch("ai_test_generator.ollama_runtime.check_ollama", return_value=self.status("ready")), \
             patch("ai_test_generator.ollama_runtime.subprocess.Popen") as spawn:
            result = runtime.ensure_ready()
        self.assertEqual(result.state, "ready")
        spawn.assert_not_called()

    def test_stopped_server_started_hidden_then_ready(self):
        runtime = self.runtime()
        process = Mock()
        process.poll.return_value = None
        with patch("ai_test_generator.ollama_runtime.check_ollama", side_effect=[self.status("not_running"), self.status("ready"), self.status("ready")]), \
             patch("ai_test_generator.ollama_runtime.find_ollama", return_value="ollama.exe"), \
             patch("ai_test_generator.ollama_runtime.subprocess.Popen", return_value=process) as spawn:
            result = runtime.ensure_ready()
        self.assertEqual(result.state, "ready")
        self.assertEqual(spawn.call_args.args[0], ["ollama.exe", "serve"])
        self.assertEqual(spawn.call_args.kwargs["env"]["OLLAMA_HOST"], "127.0.0.1:11434")
        self.assertIs(runtime.process, process)
        if os.name == "nt":
            self.assertEqual(spawn.call_args.kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_not_installed_provides_instruction_without_spawn(self):
        runtime = self.runtime()
        with patch("ai_test_generator.ollama_runtime.check_ollama", return_value=self.status("not_running")), \
             patch("ai_test_generator.ollama_runtime.find_ollama", return_value=None), \
             patch("ai_test_generator.ollama_runtime.subprocess.Popen") as spawn:
            result = runtime.ensure_ready()
        self.assertEqual(result.state, "not_found")
        self.assertIn("Установите Ollama", result.message)
        spawn.assert_not_called()

    def test_missing_model_never_downloaded_or_started(self):
        runtime = self.runtime()
        with patch("ai_test_generator.ollama_runtime.check_ollama", return_value=self.status("missing")), \
             patch("ai_test_generator.ollama_runtime.subprocess.Popen") as spawn:
            result = runtime.ensure_ready()
        self.assertEqual(result.state, "missing")
        self.assertIn("ollama pull qwen2.5:1.5b", result.message)
        spawn.assert_not_called()

    def test_retry_recovers_after_connection_error(self):
        runtime = self.runtime()
        with patch("ai_test_generator.ollama_runtime.check_ollama", side_effect=[self.status("connection_error"), self.status("ready"), self.status("ready")]):
            self.assertEqual(runtime.ensure_ready().state, "connection_error")
            self.assertEqual(runtime.ensure_ready().state, "ready")

    def test_start_failure_is_explained(self):
        runtime = self.runtime()
        with patch("ai_test_generator.ollama_runtime.check_ollama", return_value=self.status("not_running")), \
             patch("ai_test_generator.ollama_runtime.find_ollama", return_value="ollama.exe"), \
             patch("ai_test_generator.ollama_runtime.subprocess.Popen", side_effect=OSError("denied")):
            result = runtime.ensure_ready()
        self.assertEqual(result.state, "connection_error")
        self.assertNotIn("denied", result.message)

    def test_startup_deadline_does_not_wait_for_generation_timeout(self):
        runtime = self.runtime()
        runtime.process = Mock()
        runtime.process.poll.return_value = None
        with patch("ai_test_generator.ollama_runtime.check_ollama", return_value=self.status("not_running")), \
             patch("ai_test_generator.ollama_runtime.time.monotonic", side_effect=[100, 101, 121, 122]), \
             patch("ai_test_generator.ollama_runtime.time.sleep"), \
             patch("ai_test_generator.ollama_runtime.subprocess.Popen") as spawn:
            result = runtime.ensure_ready()
        self.assertEqual(result.state, "connection_error")
        spawn.assert_not_called()
        runtime.process.terminate.assert_not_called()
