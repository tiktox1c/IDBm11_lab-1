"""Подробности ошибок остаются в проекте, а не в основном интерфейсе."""
import logging
from logging.handlers import RotatingFileHandler

from .config import LOGS, prepare_temp

logger = logging.getLogger("ai_test_generator")
logger.addHandler(logging.NullHandler())


def configure_logging():
    prepare_temp()
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return
    handler = RotatingFileHandler(LOGS / "app.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def user_message(exc):
    if isinstance(exc, PermissionError):
        return "Нет доступа к файлу. Закройте его в другой программе или выберите другую папку."
    if isinstance(exc, FileNotFoundError):
        return "Файл или папка не найдены. Выберите документ или расположение ещё раз."
    if isinstance(exc, ValueError):
        return str(exc).split("Причина:")[0].strip()
    return "Не удалось выполнить операцию. Проверьте документ и доступ к файлам. Подробности — в logs/app.log."
