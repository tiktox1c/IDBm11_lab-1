"""Запуск только установленной Ollama. Без загрузки моделей и остановки процессов."""
import os
from pathlib import Path
import shutil
import subprocess
import time

from .config import ROOT, LOGS, prepare_temp
from .diagnostics import logger
from .installation import installed_paths, model_present
from .generation import check_ollama, ModelStatus


def find_ollama():
    selected=installed_paths(ROOT).get('ollama')
    if selected and selected.is_file():return str(selected)
    executable = shutil.which("ollama")
    if executable:
        return executable
    project_installation = ROOT / "tools" / "Ollama" / "ollama.exe"
    if project_installation.is_file():
        return str(project_installation)
    # Только стандартное место установки; обхода дисков и системных папок нет.
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidate = Path(local) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.is_file():
            return str(candidate)
    return None


class OllamaRuntime:
    def __init__(self):
        self.process = None

    def ensure_ready(self, progress=lambda message: None):
        progress("Проверяем нейросеть…")
        settings=installed_paths(ROOT)
        status = check_ollama(probe=False)
        if status.state=='missing' and settings.get('models') and model_present(settings['models']):
            return ModelStatus('connection_error',
                'Ollama уже работает, но использует другую папку и не видит комплектную модель. '
                'Закройте Ollama через значок в области уведомлений и нажмите «Повторить подключение». '
                'Приложение запустит её с выбранной при установке папкой модели. Другой сервер не запускается.')
        if status.state != "not_running":
            return check_ollama() if status.state == "ready" else status
        if self.process is None or self.process.poll() is not None:
            executable = find_ollama()
            if executable is None:
                return ModelStatus("not_found")
            prepare_temp()
            environment = os.environ.copy()
            environment["OLLAMA_HOST"] = "127.0.0.1:11434"
            environment["OLLAMA_NO_CLOUD"] = "1"
            if settings.get("models"):
                environment["OLLAMA_MODELS"] = str(settings["models"])
            try:
                with (LOGS / "ollama.log").open("ab") as log:
                    self.process = subprocess.Popen(
                        [executable, "serve"], cwd=ROOT, env=environment,
                        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                logger.info("Запущена Ollama, PID=%s", self.process.pid)
            except OSError:
                logger.exception("Не удалось запустить установленную Ollama")
                return ModelStatus("connection_error")
        progress("Запуск нейросети — ожидаем локальный API до 20 секунд…")
        deadline = time.monotonic() + 20
        while (remaining := deadline - time.monotonic()) > 0:
            status = check_ollama(probe=False, timeout=min(2, remaining))
            # Только при запуске нашего сервера API может кратковременно
            # отвечать HTTP 500 до завершения инициализации. Общий срок — 20 с.
            if status.state not in ("not_running","connection_error"):
                return check_ollama() if status.state == "ready" else status
            if self.process.poll() is not None:
                logger.error("Ollama завершилась при запуске, код=%s", self.process.returncode)
                return ModelStatus("connection_error")
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
        logger.error("API Ollama не стал доступен за 20 секунд")
        return ModelStatus("connection_error")


    def pull_model(self, progress=lambda message: None):
        """Вызывается только после явного согласия в интерфейсе, модель фиксирована."""
        import json
        from urllib.request import Request, urlopen
        from .config import MODEL
        status=self.ensure_ready(progress)
        if status.state=='ready':return status
        if status.state!='missing':raise ValueError(status.message)
        request=Request('http://127.0.0.1:11434/api/pull',data=json.dumps({'model':MODEL,'stream':True}).encode(),headers={'Content-Type':'application/json'})
        try:
            with urlopen(request,timeout=90) as response:
                for line in response:
                    if not line.strip():continue
                    event=json.loads(line)
                    if event.get('error'):raise ValueError('Ollama не загрузила модель: '+event['error'])
                    total,done=event.get('total',0),event.get('completed',0)
                    progress('Загрузка модели: '+(f'{done*100/total:.0f}%' if total else str(event.get('status','ожидание'))))
        except (OSError,ValueError) as exc:
            raise ValueError('Не удалось завершить загрузку модели. Проверьте интернет, свободное место и состояние Ollama. Повторите загрузку; уже скачанные слои Ollama обычно сохраняет.') from exc
        return self.ensure_ready(progress)
