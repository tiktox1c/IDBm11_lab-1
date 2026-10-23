"""Реальные последовательные испытания: один PDF — один независимый тест, без mock."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time
import subprocess

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ai_test_generator.config import prepare_temp
from ai_test_generator.diagnostics import configure_logging
from ai_test_generator.extraction import extract
from ai_test_generator.generation import generate_test, check_ollama
from ai_test_generator.validation import validate_test

IMPLEMENTATION = hashlib.sha256(b''.join((ROOT / 'ai_test_generator' / name).read_bytes()
    for name in ('config.py','generation.py','validation.py','fragments.py','extraction.py'))).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, default=ROOT / 'text')
    parser.add_argument('--output', type=Path, default=ROOT / 'output' / 'pdf_checks')
    parser.add_argument('--only', help='Номера частей через запятую; по умолчанию все PDF')
    args = parser.parse_args()
    prepare_temp()
    configure_logging()
    args.output.mkdir(parents=True, exist_ok=True)
    status = check_ollama()
    if status.state != 'ready':
        raise SystemExit(status.message)
    import re
    number = lambda p: int(re.search(r'-(\d+)\.pdf$', p.name, re.I).group(1)) if re.search(r'-(\d+)\.pdf$', p.name, re.I) else 0
    paths = sorted(args.folder.glob('*.pdf'), key=number)
    if args.only:
        wanted = {int(v) for v in args.only.split(',')}
        paths = [p for p in paths if number(p) in wanted]
    if len(paths) > 1 and all(number(p) for p in paths):
        # Каждый документ обрабатывается в отдельном свежем процессе — никакого
        # общего текста/состояния LLM между PDF. Проверки выполняются последовательно.
        for path in paths:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--folder', str(args.folder),
                            '--output', str(args.output), '--only', str(number(path))], check=True)
        reports = [json.loads(p.read_text(encoding='utf-8')) for p in args.output.glob('*.json') if p.name != 'summary.json']
        summary = {'files':len(reports), 'average_seconds':round(sum(r['seconds'] for r in reports)/len(reports),3),
                   'rows':[{k:v for k,v in row.items() if k != 'test'} for row in reports]}
        (args.output / 'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        return
    for index, path in enumerate(paths, 1):
        print(json.dumps({'event':'start', 'file':path.name, 'index':index, 'total':len(paths)}, ensure_ascii=True), flush=True)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        started = time.monotonic()
        try:
            material = extract(path)
            result = generate_test(material)
            if result['questions']:
                validate_test(result)
            counts = Counter(q['type'] for q in result['questions'])
            row = {'file':path.name, 'model':result['model'], 'characters':len(material.text), 'seconds':round(time.monotonic()-started, 3),
                   'implementation_sha256':IMPLEMENTATION,
                   'counts':dict(counts), 'review_required':sum(bool(q.get('review_required')) for q in result['questions']),
                   'text_supported':sum(q.get('grounding_status') == 'text_supported' for q in result['questions']),
                   'attempts':len(result['attempts']), 'errors':list(dict.fromkeys(a['reason'] for a in result['attempts'] if a['status'] in ('rejected','refused','unavailable'))),
                   'source_unchanged':before == hashlib.sha256(path.read_bytes()).hexdigest(), 'sha256':before,
                   'test':result}
        except Exception as exc:
            row = {'file':path.name, 'seconds':round(time.monotonic()-started,3), 'error':repr(exc),
                   'implementation_sha256':IMPLEMENTATION,
                   'source_unchanged':before == hashlib.sha256(path.read_bytes()).hexdigest(), 'sha256':before}
        (args.output / (path.stem + '.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in row.items() if k not in ('test','sha256','errors')},ensure_ascii=True),flush=True)
    reports = [json.loads(p.read_text(encoding='utf-8')) for p in args.output.glob('*.json') if p.name != 'summary.json']
    summary = {'files':len(reports), 'average_seconds':round(sum(r['seconds'] for r in reports)/len(reports),3) if reports else None,
               'rows':[{k:v for k,v in row.items() if k != 'test'} for row in reports]}
    (args.output / 'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
