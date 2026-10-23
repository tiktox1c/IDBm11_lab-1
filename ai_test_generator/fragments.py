"""Смысловые фрагменты одного документа с номерами страниц, без смешения файлов."""
import re


def build_fragments(text, limit=1400):
    result = []
    page = None
    sections = re.split(r"(\[Страница\s+\d+\])", text)
    for section in sections:
        marker = re.fullmatch(r"\[Страница\s+(\d+)\]", section)
        if marker:
            page = int(marker.group(1))
            continue
        if not section.strip():
            continue
        section = re.sub(r"([А-Яа-яЁё])-\s*\n\s*([а-яё])", r"\1\2", section)
        # Разбиваем по абзацам/законченным предложениям, а длинные строки — по словам.
        units = []
        for paragraph in re.split(r"\n\s*\n", section.strip()):
            if len(paragraph) <= limit:
                units.append(paragraph.strip())
            else:
                units.extend(re.split(r"(?<=[.!?;])\s+(?=[А-ЯA-Z0-9])|(?<=\n)", paragraph))
        buffer = ''
        for unit in units:
            unit = unit.strip()
            if not unit:
                continue
            first_line = unit.splitlines()[0].strip()
            is_heading = bool(re.match(r'(?:Глава|Раздел|Тема)\s+\d|\d+\.\d+(?:\.\d+)*\.?\s', first_line, re.I)
                              or (len(first_line) > 8 and first_line.isupper()))
            if buffer and is_heading:
                result.append({'id':len(result)+1, 'text':buffer, 'pages':[page] if page else []})
                buffer = ''
            pieces = []
            while len(unit) > limit:
                end = unit.rfind(' ', 0, limit + 1)
                if end <= 0:
                    end = limit
                pieces.append(unit[:end])
                unit = unit[end:].lstrip()
            pieces.append(unit)
            for piece in pieces:
                if buffer and len(buffer) + len(piece) + 2 > limit:
                    result.append({'id': len(result)+1, 'text': buffer, 'pages': [page] if page else []})
                    buffer = ''
                buffer = (buffer + '\n\n' + piece).strip()
        if buffer:
            result.append({'id': len(result)+1, 'text': buffer, 'pages': [page] if page else []})
    return result


def order_evidence(text):
    if re.search(r'\bэтап(?:ы|а|ов)?\b|\bшаг(?:и|а|ов)?\b|\bсначала\b|\bзатем\b|после\s+(?:этого|чего)|последовательность\s+(?:действий|шагов|этапов)', text, re.I):
        return True
    action_bullets = re.findall(r'(?:^|\n)\s*[•*-]\s+[А-Яа-яЁё]+(?:ть|ти|чь)\b', text)
    if len(action_bullets) >= 3 and re.search(r'алгоритм|процесс|порядок', text, re.I):
        return True
    numbered = re.findall(r'(?:^|\n)\s*([1-6])[.)]\s+([^\n]+)', text)
    return (len(numbered) >= 3 and [int(n) for n, _ in numbered[:3]] == [1, 2, 3]
            and all(re.search(r'\b[А-Яа-яЁё]+(?:ть|ти|чь|ние)\b', line) for _, line in numbered[:3]))


def matching_evidence(text):
    relations = len(re.findall(r'\s[—–-]\s|\bэто\b|предназначен|называется|означает|выполняет|обеспечивает|планирует|решает\s+задач|формирует', text, re.I))
    rows = [line for line in text.splitlines() if '|' in line]
    return relations >= 3 or len(rows) >= 3


def fragment_score(fragment, kind):
    value = fragment['text']
    facts = len(re.findall(r'—|\s–\s|\bэто\b|называ|являет|состоит|позвол|обеспеч|предназнач|функци|использ|применя', value, re.I))
    if kind == 'sequence':
        score = 12 * order_evidence(value) + len(re.findall(r'\b[1-6][.)]|сначала|затем|потом|этап|шаг', value, re.I))
        score += 3 * len(re.findall(r'(?:^|\n)\s*[•*-]\s+[А-Яа-яЁё]+(?:ть|ти|чь)\b', value))
    elif kind == 'matching':
        score = facts * 2 + value.count('|') + len(re.findall(r'\n\s*[•–—-]', value))
    else:
        score = facts * 2 + min(len(value), 900) / 900
    # Библиография и титульный лист не являются предпочтительным учебным материалом.
    if re.search(r'список\s+литературы|ISBN|https?://', value, re.I):
        score -= 10
    return score


def rank_fragments(fragments, kind):
    return sorted(fragments, key=lambda f: fragment_score(f, kind), reverse=True)


def focus_fact(fragment, offset=0):
    """Одному вопросу о факте достаточно одного содержательного абзаца, а не всей страницы."""
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', fragment['text']) if len(p.strip()) >= 90]
    candidates = []
    for paragraph in paragraphs:
        definitions=[s.strip() for s in re.split(r'(?<=[.!?])\s+(?=[А-ЯЁA-Z])',paragraph)
                     if re.search(r'\s[—–]\s',s) and 30<=len(s.strip())<=800]
        if len(definitions)>=2:
            candidates.extend(definitions)
            continue
        if len(paragraph) > 800:
            sentences = re.split(r'(?<=[.!?])\s+(?=[А-ЯЁ])', paragraph)
            for index, sentence in enumerate(sentences):
                value = sentence
                if len(value) < 120 and index + 1 < len(sentences):
                    value += ' ' + sentences[index + 1]
                if 90 <= len(value) <= 800:
                    candidates.append(value)
        else:
            candidates.append(paragraph)
    if not candidates:
        return fragment['text']
    candidates.sort(key=lambda p: fragment_score({'text':p}, 'short'), reverse=True)
    return candidates[offset % len(candidates)]


def focus_process(fragment):
    value = fragment['text']
    for paragraph in re.split(r'\n\s*\n',value):
        if len(re.findall(r'(?:^|\n)\s*[1-6][.)]\s+',paragraph)) >= 3 and order_evidence(paragraph):
            return paragraph.strip()
    bullets = list(re.finditer(r'(?:^|\n)\s*[•*-]\s+[А-Яа-яЁё]+(?:ть|ти|чь)\b', value))
    if len(bullets) >= 3 and order_evidence(value):
        start = value.rfind('\n\n', 0, bullets[0].start())
        end = value.find('\n\n', bullets[-1].end())
        return value[max(0, start):end if end >= 0 else len(value)].strip()
    return value


def focus_matching(fragment):
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n',fragment['text'])
                  if matching_evidence(p)]
    return min(paragraphs,key=len) if paragraphs else fragment['text']
