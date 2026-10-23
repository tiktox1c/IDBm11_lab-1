"""Независимая проверка структуры и простых признаков опоры на источник."""
import re
from difflib import SequenceMatcher

from .config import TYPES
from .fragments import order_evidence, matching_evidence


def normalized(value):
    return " ".join(re.findall(r"(?<!\w)[+-]?\d+(?:[.,]\d+)?|\w+", value.casefold().replace("ё", "е")))


def present(value, source):
    return f" {normalized(value)} " in f" {normalized(source)} "


def text(value, label):
    if not isinstance(value, str) or not value.strip() or not normalized(value):
        raise ValueError(f"{label}: требуется непустой текст.")


def question_body(value):
    """Служебный заголовок модели не меняет тип следующей инструкции."""
    value=re.sub(r'^\s*\d+\s*[:.)]\s*','',value)
    return re.sub(r'^\s*(?:задание|вопрос|тест)(?:\s*№?\s*\d+)?\s*[:.)]\s*','',value,flags=re.I)


def unique_list(values, minimum, maximum, label):
    if not isinstance(values, list) or not minimum <= len(values) <= maximum:
        raise ValueError(f"{label}: требуется от {minimum} до {maximum} элементов.")
    for item in values:
        text(item, label)
    for index,value in enumerate(values):
        positions=[i+1 for i,item in enumerate(values) if normalized(item)==normalized(value)]
        if len(positions)>1:
            raise ValueError(f'{label}: повторяется «{value[:80]}» (позиции {", ".join(map(str,positions))}). '
                             'Замените повторяющиеся элементы разными.')


def lexical_tokens(value):
    stop = {'который', 'которые', 'также', 'этого', 'этот', 'такой', 'такое', 'между',
            'является', 'могут', 'может', 'какой', 'какие', 'какая', 'сколько', 'называется',
            'почему', 'когда', 'через', 'данных', 'вопрос', 'ответ'}
    return {v for v in normalized(value).split() if len(v) > 2 and v not in stop}


def overlap(left, right):
    a, b = lexical_tokens(left), lexical_tokens(right)
    if not a:
        return 0.0
    return sum(any(x == y or (len(x) > 5 and len(y) > 5 and x[:5] == y[:5]) for y in b) for x in a) / len(a)


def assess_grounding(q, facts):
    """Третий уровень: источник и признаки подтверждения, а не вымышленная семантическая гарантия."""
    text(q.get('source_quote'), 'Подтверждающие сведения')
    text(q.get('source_excerpt'), 'Фрагмент источника')
    quote, source = q['source_quote'], q['source_excerpt']
    question_words = {'выберите','расположите','сопоставьте','назовите','укажите','какой','какое',
                      'какая','какие','как','что','для','сколько','установите','почему','зачем'}
    question_prompt = question_body(q['prompt'])
    for name in re.finditer(r'\b[A-Z][A-Za-z0-9]*\b|\b[А-ЯЁ][а-яё]{2,}\b', question_prompt):
        if name.start() and name.group().casefold() not in question_words and not present(name.group(), source) and overlap(name.group(), source) == 0:
            raise ValueError(f'Вопрос: «{name.group()}» не найдено в исходном фрагменте. '
                             'Исправьте название или формулировку и сравните с раскрытым источником.')
    exact_quote = present(quote, source)
    if not exact_quote and overlap(quote, source) < 0.5:
        raise ValueError('Подтверждающие сведения не связаны с исходным фрагментом.')
    if all(not present(fact, quote) and overlap(fact, quote) == 0 for fact in facts):
        raise ValueError('Подтверждение не содержит сведений об ответе.')
    if q['type'] in ('short', 'choice') and any(not present(fact, quote) and overlap(fact, quote) < 0.35 for fact in facts):
        raise ValueError('Приведённое подтверждение не обосновывает ответ; нужен другой фрагмент или цитата.')
    if (q['type']=='short' and re.search(r'\bиспользу',q['prompt'],re.I)
            and not re.search(r'\bне\b|нельзя|невозможно',q['prompt'],re.I)):
        clauses=re.split(r'[.;!\n]',source)
        for fact in facts:
            relevant=[c for c in clauses if present(fact,c)]
            if relevant and all(re.search(r'\bне\s+использу',c,re.I) for c in relevant):
                raise ValueError('Источник содержит отрицание использования ответа; вопрос меняет смысл. Проверьте формулировку вручную.')
    reasons = []
    if not exact_quote:
        reasons.append('Подтверждение передано пересказом; сравните его с исходным фрагментом.')
    for fact in facts:
        # Числа, латинские сокращения и названия нельзя подтверждать только похожими русскими словами.
        entities = re.findall(r'(?<!\w)[+-]?\d+(?:[.,]\d+)?\b|\b[A-Za-z][A-Za-z0-9_.+-]*\b', fact)
        if any(not present(entity, source) for entity in entities):
            raise ValueError('Ответ содержит число или обозначение, отсутствующее в исходном фрагменте.')
        if not present(fact, source):
            if overlap(fact, source) == 0:
                raise ValueError('Ответ или элемент не подтверждается сведениями исходного фрагмента.')
            reasons.append('Ответ или элемент сформулирован иначе, чем в источнике; проверьте смысл.')
    if q['type'] == 'sequence':
        if not order_evidence(source):
            raise ValueError('В исходном фрагменте нет подтверждённого порядка действий.')
        ordered = [q['items'][i-1] for i in q['answer']]
        literal_source = normalized(source)
        if (re.search(r'сначала|затем|этапы\s*:|шаги\s*:', source, re.I)
                and all(literal_source.count(normalized(v)) == 1 for v in ordered)):
            positions = [literal_source.find(normalized(v)) for v in ordered]
            if positions != sorted(positions):
                raise ValueError('Ключ последовательности противоречит явно описанному порядку.')
        reasons.append('Проверьте, что источник задаёт именно порядок этих этапов, а не перечень.')
    elif q['type'] == 'matching':
        if not matching_evidence(source):
            raise ValueError('В исходном фрагменте не найдены три явные пары термин–описание; перечень тем не задаёт соответствия.')
        # Очевидные противоречия буквальным строкам термин—определение не являются пересказом.
        clauses = re.split(r'[;\n]', source)
        for left, number in zip(q['left'], q['answer']):
            selected = q['right'][number-1]
            explicit = [c for c in clauses if re.search(r'—|\s–\s|\s-\s|\|', c) and present(left, c)]
            if len(explicit) == 1 and not present(selected, explicit[0]) and overlap(selected, explicit[0]) == 0:
                if any(present(other, explicit[0]) for other in q['right'] if other != selected):
                    raise ValueError('Ключ соответствия противоречит паре, явно указанной в источнике.')
        reasons.append('Проверьте однозначность каждой пары по исходному фрагменту.')
    elif q['type'] == 'choice':
        reasons.append('Проверьте, что верен ровно один вариант, а остальные три неверны.')
    q['grounding_status'] = 'text_supported' if exact_quote and all(present(f, quote) for f in facts) else 'review'
    if q['type'] == 'short':
        reasons.append('Проверьте, что предложенный ответ отвечает именно на сформулированный вопрос.')
    confirmed = q.get('edited') is True and q.get('manual_confirmed') is True
    q['manual_confirmed'] = confirmed
    q['review_required'] = not confirmed
    q['review_reasons'] = [] if confirmed else list(dict.fromkeys(reasons))


def validate_question(q, previous=(), grounding=True):
    # Уровень 1: объект и обязательные поля; уровень 2: структура конкретного типа.
    if not isinstance(q, dict) or q.get("type") not in TYPES:
        raise ValueError("Неизвестный тип вопроса.")
    text(q.get("prompt"), "Вопрос")
    if len(normalized(q['prompt']).split()) < 2:
        raise ValueError('Формулировка слишком общая: укажите, о чём спрашивает вопрос.')
    clean_prompt = question_body(q['prompt'])
    if '?' not in clean_prompt and not re.match(r'как|что|како[йея]|какие|для\s+чего|назовите|укажите|выберите|расположите|сопоставьте|установите|найдите|определите|соотнесите|упорядочьте|составьте|почему|зачем|кто|чем|в\s+каком', clean_prompt, re.I):
        raise ValueError('Модель вернула утверждение вместо вопроса или задания.')
    if re.search(r'создай\s+(?:новый\s+)?вопрос|сгенерируй|верни\s+json|готовый\s+тест|source_quote', q['prompt'], re.I):
        raise ValueError('Модель повторила инструкцию вместо формулировки учебного вопроса.')
    kind, answer = q["type"], q.get("answer")
    if kind in ('choice','short') and re.match(r'расположите|упорядочьте|сопоставьте|установите\s+соответствие',clean_prompt,re.I):
        raise ValueError('Формулировка требует другого типа задания: исправьте вопрос на выбор или краткий ответ.')
    if kind == "choice":
        unique_list(q.get("options"), 4, 4, "Варианты")
        if type(answer) is not int or not 1 <= answer <= 4:
            raise ValueError("Правильный ответ: номер от 1 до 4.")
        facts = [q["options"][answer - 1]]
    elif kind in ("sequence", "matching"):
        key = "items" if kind == "sequence" else "left"
        unique_list(q.get(key), 3, 6, "Элементы")
        count = len(q[key])
        if kind == "matching":
            unique_list(q.get("right"), count, count, "Правая колонка")
        if (not isinstance(answer, list) or any(type(v) is not int for v in answer)
                or sorted(answer) != list(range(1, count + 1))):
            raise ValueError(f"Ответ должен содержать каждый номер от 1 до {count} ровно один раз.")
        facts = q[key] + (q["right"] if kind == "matching" else [])
    else:
        text(answer, "Краткий ответ")
        if len(answer) > 300 or len(answer.split()) > 40:
            raise ValueError('Краткий ответ должен быть коротким, без длинного рассуждения.')
        aliases = q.get('acceptable_answers', [])
        if not isinstance(aliases, list) or len(aliases) > 6:
            raise ValueError('Допустимые формулировки должны быть списком, не более шести.')
        for alias in aliases:
            text(alias, 'Допустимая формулировка')
        facts = [answer] + aliases
    if grounding:
        assess_grounding(q, facts)
    candidate = normalized(q["prompt"])
    for old in previous:
        old_prompt = normalized(old["prompt"])
        structured_task = kind == old['type'] and kind in ('sequence','matching')
        if not structured_task and (candidate == old_prompt or SequenceMatcher(None, candidate, old_prompt).ratio() > 0.9):
            raise ValueError("Вопрос явно повторяет уже принятый.")
        if (kind == old["type"] and kind == "choice"
                and {normalized(v) for v in q["options"]} ==
                {normalized(v) for v in old["options"]}):
            raise ValueError("Повторяется тот же набор вариантов.")
        if kind == old["type"] and kind in ("sequence", "matching"):
            key = "items" if kind == "sequence" else "left"
            if {normalized(v) for v in q[key]} == {normalized(v) for v in old[key]}:
                raise ValueError("Повторяется тот же набор элементов.")
        if kind == old["type"] == "short" and normalized(answer) == normalized(old["answer"]):
            raise ValueError("Повторяется краткий ответ.")
    return q


def validate_test(test):
    if not test.get("questions"):
        raise ValueError("Нет вопросов для сохранения.")
    accepted = []
    for q in test["questions"]:
        validate_question(q, accepted, grounding="review_status" not in q)
        accepted.append(q)
