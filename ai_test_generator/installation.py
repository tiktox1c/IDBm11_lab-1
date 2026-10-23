"""Локальные пути офлайн-установки; без изменения переменных Windows."""
import configparser
import hashlib
import json
from pathlib import Path
import re
from .config import ROOT

MODEL_MANIFEST=Path('manifests/registry.ollama.ai/library/qwen2.5/1.5b')

def installed_paths(root=None):
    path=Path(root or ROOT)/'installation.ini'
    if not path.is_file():return {}
    try:
        parser=configparser.ConfigParser(interpolation=None)
        parser.read_string(path.read_text('utf-8-sig'))
        result={}
        for key in ('ollama','models'):
            value=parser.get('paths',key,fallback='').strip()
            candidate=Path(value)
            if value and candidate.is_absolute():result[key]=candidate
        return result
    except (OSError,UnicodeError,configparser.Error):return {}

def model_files(folder,verify=False):
    """Only this model's manifest and referenced blobs, including nested manifests."""
    root=Path(folder);manifest=root/MODEL_MANIFEST
    data=json.loads(manifest.read_text('utf-8'));seen=set();files=[MODEL_MANIFEST]
    def walk(value,depth=0):
        if depth>4 or not isinstance(value,dict):raise ValueError('Неверная структура модели')
        entries=([value['config']] if 'config' in value else [])+value.get('layers',[])
        if not entries:raise ValueError('Нет файлов модели')
        for entry in entries:
            digest=entry.get('digest','')
            if not re.fullmatch(r'sha256:[0-9a-f]{64}',digest):raise ValueError('Неверный SHA256 модели')
            name=Path('blobs')/digest.replace(':','-');path=root/name
            if name in seen:continue
            seen.add(name)
            if len(seen)>32:raise ValueError('Слишком много файлов модели')
            if not path.is_file() or path.stat().st_size!=entry.get('size'):raise ValueError('Файл модели отсутствует или повреждён')
            if verify:
                h=hashlib.sha256()
                with path.open('rb') as stream:
                    for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
                if h.hexdigest()!=digest[7:]:raise ValueError('Контрольная сумма модели не совпадает')
            files.append(name)
            if 'manifest' in entry.get('mediaType',''):walk(json.loads(path.read_text('utf-8')),depth+1)
    walk(data)
    return files

def model_present(folder):
    try:return bool(model_files(folder))
    except (OSError,ValueError,TypeError,KeyError,AttributeError):return False
