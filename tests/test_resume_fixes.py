"""Регрессии по реальным отказам после возобновления работы."""
import unittest
from unittest.mock import Mock,patch

from ai_test_generator.validation import validate_question
from ai_test_generator.ollama_runtime import OllamaRuntime
from ai_test_generator.generation import ModelStatus
from ai_test_generator.generation import generate_test,normalize_model_question
from ai_test_generator.extraction import Material
from ai_test_generator.fragments import focus_fact
from test_core import fixture


class ResumeFixTests(unittest.TestCase):
    def test_fact_focus_can_choose_different_complete_definitions(self):
        definitions=['CPU — компонент, который выполняет инструкции программы и вычисления модели.',
                     'RAM — компонент, который временно хранит параметры работающей модели и входные данные.']
        fragment={'text':'\n'.join(definitions)}
        first,second=focus_fact(fragment),focus_fact(fragment,1)
        self.assertNotEqual(first,second)
        self.assertIn(first,definitions)
        self.assertIn(second,definitions)

    def test_choice_cannot_ask_for_ordering_instead_of_one_answer(self):
        q=fixture('choice')
        q['prompt']='Расположите компоненты в порядке увеличения.'
        with self.assertRaisesRegex(ValueError,'тип'):validate_question(q)

    def test_model_step_numbers_do_not_reveal_the_answer_after_shuffle(self):
        reply={'question':'Расположите действия процесса.',
               'steps':['1. Прочитать файл','Этап 2: Обработать данные','3) Сохранить результат']}
        q=normalize_model_question(reply,'sequence','Источник')
        self.assertEqual(q['items'],['Прочитать файл','Обработать данные','Сохранить результат'])

    def test_second_slot_uses_next_untried_process_not_third_fragment(self):
        source=('[Страница 1]\nПроцесс первый:\n1. Прочитать файл.\n2. Обработать данные.\n3. Сохранить результат.\n'
                '[Страница 2]\nПроцесс второй:\n1. Подключить устройство.\n2. Проверить связь.\n3. Загрузить программу.\n'
                '[Страница 3]\nCPU — процессор. RAM — память. SSD — накопитель.')
        def reply(prompt,schema):
            if 'steps' not in schema['properties']:
                return {'available':False,'reason':'Тестируется только выбор процесса.'}
            if 'Процесс первый' in prompt:
                return {'question':'Расположите действия первого процесса.',
                        'steps':['Прочитать файл','Обработать данные','Сохранить результат']}
            if 'Процесс второй' in prompt:
                return {'question':'Расположите действия второго процесса.',
                        'steps':['Подключить устройство','Проверить связь','Загрузить программу']}
            return {'question':'','steps':[]}
        result=generate_test(Material('processes',source),call=reply)
        self.assertEqual(len([q for q in result['questions'] if q['type']=='sequence']),2)

    def test_matching_instruction_with_task_prefix_is_valid(self):
        q=fixture('matching')
        q['prompt']='Задание: Составьте пары: компоненты и их функции.'
        validate_question(q)
        self.assertTrue(q['review_required'])

    def test_task_prefix_does_not_allow_a_copied_statement(self):
        q=fixture('short')
        q['prompt']='Задание: Вычислитель CPU выполняет обработку данных.'
        with self.assertRaises(ValueError):validate_question(q)

    def test_task_prefix_does_not_hide_an_unknown_name(self):
        q=fixture('short')
        q['prompt']='Вопрос 1: Как называется столица Франции?'
        with self.assertRaisesRegex(ValueError,'Франции'):validate_question(q)

    def test_owned_server_recovers_from_transient_startup_api_error(self):
        process=Mock()
        process.poll.return_value=None
        states=[ModelStatus(v) for v in ('not_running','connection_error','ready','ready')]
        with patch('ai_test_generator.ollama_runtime.check_ollama',side_effect=states), \
             patch('ai_test_generator.ollama_runtime.find_ollama',return_value='ollama.exe'), \
             patch('ai_test_generator.ollama_runtime.subprocess.Popen',return_value=process), \
             patch('ai_test_generator.ollama_runtime.time.sleep'):
            result=OllamaRuntime().ensure_ready()
        self.assertEqual(result.state,'ready')

