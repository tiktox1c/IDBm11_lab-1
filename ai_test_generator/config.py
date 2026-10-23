import os
import sys
from pathlib import Path
import tempfile

ROOT = Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent.parent
TEMP = ROOT / "temp"
OUTPUT = ROOT / "output"
LOGS = ROOT / "logs"
MODEL = "qwen2.5:1.5b"
MODEL_LABEL = "Qwen2.5 1.5B"
TYPES = {
    "choice": "Один ответ из четырёх",
    "sequence": "Последовательность",
    "matching": "Соответствие",
    "short": "Краткий ответ",
}


def prepare_temp():
    for directory in (TEMP, OUTPUT, LOGS):
        directory.mkdir(exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(TEMP)
    tempfile.tempdir = str(TEMP)
