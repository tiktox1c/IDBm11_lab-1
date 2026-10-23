import copy
import unittest

from ai_test_generator.extraction import Material
from ai_test_generator.generation import generate_test, schema_for
from ai_test_generator.validation import validate_question
from test_core import fixture


class GroundingQualityTests(unittest.TestCase):
    def test_same_sequence_instruction_with_different_actions_is_not_duplicate(self):
        old=fixture('sequence')
        old['prompt']='Расположите этапы в правильном порядке.'
        new=copy.deepcopy(old)
        new.update(items=['ввод','анализ','вывод'],answer=[1,2,3],
                   source_quote='Этапы: ввод, анализ, вывод.',source_excerpt='Этапы: ввод, анализ, вывод.')
        validate_question(new,[old])

    def test_inflected_answer_is_retained_for_manual_review(self):
        q = fixture('short')
        q.update(prompt='Что обеспечивают нейросети?', answer='параллельная обработка',
                 source_quote='Нейросети обеспечивают параллельную обработку данных.',
                 source_excerpt='Нейросети обеспечивают параллельную обработку данных.')
        validate_question(q)
        self.assertTrue(q.get('review_required'))
        self.assertTrue(q.get('review_reasons'))

    def test_unseen_numeric_answer_is_not_supported_by_nearby_words(self):
        q = fixture('short')
        q.update(answer='64 ядра', source_quote='Процессор содержит 8 ядер.',
                 source_excerpt='Процессор содержит 8 ядер.')
        with self.assertRaises(ValueError):
            validate_question(q)

    def test_six_sequence_elements_are_supported(self):
        q = fixture('sequence')
        q.update(items=['ввод', 'анализ', 'поиск', 'оценка', 'проверка', 'вывод'],
                 answer=[1, 2, 3, 4, 5, 6], source_quote='Этапы: ввод, анализ, поиск, оценка, проверка, вывод.')
        q['source_excerpt'] = q['source_quote']
        validate_question(q)

    def test_unordered_terms_do_not_become_a_sequence(self):
        q = fixture('sequence')
        q.update(items=['CPU', 'RAM', 'SSD'], answer=[1, 2, 3],
                 source_quote='Компоненты компьютера: CPU, RAM, SSD.',
                 source_excerpt='Компоненты компьютера: CPU, RAM, SSD.')
        with self.assertRaisesRegex(ValueError, 'поряд'):
            validate_question(q)

    def test_unrelated_answer_and_aliases_are_rejected(self):
        for answer, aliases in [('Зелёный крокодил', []), ('RAM', ['999']), ('-5', [])]:
            q = fixture('short')
            q.update(answer=answer, acceptable_answers=aliases, source_quote='RAM хранит данные. Значение равно 5.',
                     source_excerpt='RAM хранит данные. Значение равно 5.')
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                validate_question(q)

    def test_heading_does_not_support_long_answer(self):
        q = fixture('short')
        q.update(answer='Система управления поведением формирует команды движения робота',
                 source_quote='Программное обеспечение систем ИИ',
                 source_excerpt='Программное обеспечение систем ИИ. Система управления поведением формирует команды движения робота.')
        with self.assertRaises(ValueError):
            validate_question(q)

    def test_literal_reversed_order_and_pairs_are_rejected(self):
        q = fixture('sequence')
        q['answer'] = [1,3,2]
        with self.assertRaises(ValueError):
            validate_question(q)

    def test_table_of_contents_is_not_matching_evidence(self):
        q = fixture('matching')
        q.update(prompt='Сопоставьте разделы?', left=['Классификация ИИ','История ИИ','Методы ИИ'],
                 right=['Глубокое обучение','Роботы','Нейросети'], answer=[1,2,3],
                 source_quote='Содержание: Классификация ИИ, История ИИ, Методы ИИ. Глубокое обучение, Роботы, Нейросети.')
        q['source_excerpt'] = q['source_quote']
        with self.assertRaises(ValueError):
            validate_question(q)

    def test_bare_question_word_is_not_a_question(self):
        q = fixture('short')
        q['prompt'] = 'Что?'
        with self.assertRaises(ValueError):
            validate_question(q)

    def test_copied_declarative_sentence_is_not_question(self):
        q = fixture('short')
        q['prompt'] = 'Вычислитель CPU выполняет обработку данных.'
        with self.assertRaises(ValueError):
            validate_question(q)

    def test_unseen_named_subject_cannot_be_hidden_behind_a_grounded_answer(self):
        q = fixture('short')
        q.update(prompt='Как называется столица Франции?', answer='процессор',
                 source_quote='CPU — процессор.', source_excerpt='CPU — процессор.')
        with self.assertRaises(ValueError):
            validate_question(q)

    def test_corrupt_docx_has_readable_error(self):
        import tempfile
        from pathlib import Path
        from ai_test_generator.config import TEMP
        from ai_test_generator.extraction import extract
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            path = Path(folder) / 'broken.docx'
            path.write_bytes(b'not a ZIP document')
            with self.assertRaisesRegex(ValueError, 'DOCX'):
                extract(path)
        q = fixture('matching')
        q['answer'] = [1,2,3]
        with self.assertRaises(ValueError):
            validate_question(q)


class GenerationQualityTests(unittest.TestCase):
    def test_question_form_is_in_prompt_not_unsupported_regex_grammar(self):
        from ai_test_generator.generation import build_prompt
        for kind in ('choice','short','sequence','matching'):
            self.assertNotIn('pattern',schema_for(kind)['properties']['question'])

    def test_specific_task_focus_retains_actual_definitions_and_numbered_process(self):
        from ai_test_generator.fragments import focus_matching, focus_process
        definitions='CPU — вычислитель.\nRAM — память.\nSSD — накопитель.'
        process='Порядок запуска:\n1. Прочитать файл.\n2. Загрузить данные.\n3. Выполнить программу.'
        fragment={'text':'Введение в тему.\n\n'+definitions+'\n\n'+process+'\n\nЗаключение.'}
        self.assertEqual(focus_matching(fragment),definitions)
        self.assertEqual(focus_process(fragment),process)

    def test_llm_creates_content_python_builds_keys_and_keeps_real_evidence(self):
        def call(prompt, schema):
            fields=schema['properties']
            if 'correct_answer' in fields:
                return {'question':'Выберите вычислитель?', 'correct_answer':'CPU','wrong_answers':['экран','мышь','кабель']}
            if 'steps' in fields:
                return {'question':'Расположите этапы?', 'steps':['чтение','обработка','запись']}
            if 'pairs' in fields:
                return {'question':'Сопоставьте компоненты?', 'pairs':[
                    {'term':'RAM','definition':'память'},{'term':'SSD','definition':'накопитель'},
                    {'term':'GPU','definition':'ускоритель'}]}
            return {'question':'Назовите вычислитель?', 'answer':'CPU'}
        result=generate_test(Material('source',fixture()['source_excerpt']),call=call,count=4)
        self.assertEqual(len(result['questions']),4)
        q=next(q for q in result['questions'] if q['type']=='choice')
        self.assertEqual(q['options'][q['answer']-1],'CPU')
        for q in result['questions']:
            self.assertEqual(q['source_quote'],q['source_excerpt'])
    def test_fragments_do_not_merge_distinct_section_headings_or_pages(self):
        from ai_test_generator.fragments import build_fragments
        parts = build_fragments('[Страница 1]\nГлава 1. Процессоры\n\nCPU выполняет вычисления.\n\nГлава 2. Память\n\nRAM хранит данные.\n[Страница 2]\nSSD хранит файлы.')
        self.assertFalse(any('CPU' in p['text'] and 'RAM' in p['text'] for p in parts))
        self.assertTrue(any(p['pages'] == [2] and 'SSD' in p['text'] for p in parts))

    def test_ordered_algorithm_actions_outrank_mentions_of_other_steps(self):
        from ai_test_generator.fragments import rank_fragments, order_evidence
        source = 'Алгоритм:\n• Сгенерировать варианты.\n• Исключить лишние пути.\n• Проверить результат.'
        self.assertTrue(order_evidence(source))
        parts=[{'id':1,'pages':[1],'text':'Шаг 4 продолжает шаг 2 и шаг 3. Шаг 5 завершает работу.'},
               {'id':2,'pages':[2],'text':source}]
        self.assertEqual(rank_fragments(parts,'sequence')[0]['id'],2)

    def test_schema_and_prompt_do_not_ask_model_to_find_ready_test(self):
        self.assertIn('question', schema_for('choice')['properties'])
        prompts = []

        def reply(prompt, schema):
            prompts.append(prompt)
            return {'prompt': '', 'options': [], 'answer': 0, 'source_quote': ''}

        result = generate_test(Material('source', 'CPU — центральный процессор.'), call=reply)
        self.assertNotIn('Создай ОДИН вопрос типа Один ответ из четырёх', prompts[0])
        self.assertLess(len(prompts[0]), 1200)
        self.assertTrue(result.get('attempts'))
        self.assertTrue(result.get('fragments'))

    def test_matching_and_sequence_are_shuffled_with_keys_preserved(self):
        # The LLM supplies content; Python only changes presentation order.
        counters = {}

        def reply(prompt, schema):
            fields = schema['properties']
            kind = 'choice' if 'correct_answer' in fields else 'sequence' if 'steps' in fields else 'matching' if 'pairs' in fields else 'short'
            q = fixture(kind)
            q['prompt'] = {'choice':'Выберите CPU', 'sequence':'Укажите этапы', 'matching':'Сопоставьте компоненты', 'short':'Назовите процессор'}[kind]
            return q

        result = generate_test(Material('source', fixture()['source_excerpt']), call=reply, count=4)
        for q in result['questions']:
            if q['type'] == 'sequence':
                self.assertNotEqual(q['answer'], list(range(1, len(q['items']) + 1)))
                self.assertEqual([q['items'][i-1] for i in q['answer']], ['чтение', 'обработка', 'запись'])
            if q['type'] == 'matching':
                self.assertNotEqual(q['answer'], list(range(1, len(q['left']) + 1)))
                self.assertEqual([q['right'][i-1] for i in q['answer']], ['память', 'накопитель', 'ускоритель'])
