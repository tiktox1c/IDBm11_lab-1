import unittest
from unittest.mock import patch
import test_gui
from ai_test_generator.review import question_status

class ReleaseGuiTests(unittest.TestCase):
    setUp=test_gui.GuiTests.setUp
    tearDown=test_gui.GuiTests.tearDown
    def test_confirm_save_reset_and_export_snapshot(self):
        q=self.app.test['questions'][0]
        self.assertEqual(question_status(q),'Требует проверки')
        self.app.confirm_current();self.assertEqual(question_status(self.app.test['questions'][0]),'Проверено')
        card=self.app.cards[0];card.edit();card.answer_var.set('2')
        self.assertEqual(question_status(self.app.test['questions'][0]),'Требует проверки')
        self.assertTrue(self.app.commit_edits())
        self.assertEqual(question_status(self.app.test['questions'][0]),'Исправлено')
        self.assertEqual(self.app.test['questions'][0]['answer'],2)
        self.app.notebook.select(self.app.result_page);self.app.update()
        self.assertIn('Статус: Исправлено',self.app.preview.get('1.0','end'))
        self.assertIn('Исправлено: 1',self.app.summary.cget('text'))
    def test_cancel_navigation_preserves_draft(self):
        card=self.app.cards[0];card.edit();card.answer_var.set('2')
        with patch('ai_test_generator.gui.messagebox.askyesnocancel',return_value=None):
            self.assertFalse(self.app.save_before_navigation())
        self.assertTrue(card.editing);self.assertEqual(card.answer_var.get(),'2')
    def test_cancel_edit_restores_confirmed_content_and_status(self):
        self.app.confirm_current();card=self.app.cards[0];card.edit();card.answer_var.set('2');card.cancel()
        self.assertEqual(question_status(card.question),'Проверено');self.assertEqual(card.question['answer'],1)
    def test_no_json_or_duplicate_save_buttons(self):
        def labels(widget):
            result=[]
            for child in widget.winfo_children():
                if child.winfo_class()=='TButton':result.append(child.cget('text'))
                result+=labels(child)
            return result
        self.assertFalse(any('JSON' in s for s in labels(self.app)))
        self.assertFalse(any('Сохранить' in s for s in labels(self.app.create_page)))
        self.assertEqual(labels(self.app.result_page).count('Сохранить в Word'),1)
    def test_invalid_confirmation_shows_reason_and_does_not_confirm(self):
        self.app.test['questions'][0]['answer']=99
        with patch('ai_test_generator.gui.messagebox.showerror') as error:self.app.confirm_current()
        self.assertTrue(error.called)
        self.assertEqual(question_status(self.app.test['questions'][0]),'Требует проверки')

    def test_download_is_not_started_without_consent(self):
        with patch('ai_test_generator.gui.messagebox.askyesno',return_value=False),patch.object(self.app,'start_job') as start:
            self.app.download_model();start.assert_not_called()
    def test_short_answer_must_not_reverse_explicit_non_use(self):
        from test_core import fixture
        from ai_test_generator.validation import validate_question
        q=fixture('short');q.update(prompt='Какие данные используются для генерации?',answer='пиксели',source_quote='Пиксели не используются для генерации.',source_excerpt='Пиксели не используются для генерации.')
        with self.assertRaisesRegex(ValueError,'отрицание'):validate_question(q)
