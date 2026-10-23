"""Настоящие виджеты Tkinter; только граница с Ollama заменена."""
import copy
import tkinter
import unittest
import time
from unittest.mock import Mock, patch

from ai_test_generator.gui import App
from ai_test_generator.generation import ModelStatus
from test_core import fixture


class GuiTests(unittest.TestCase):
    def setUp(self):
        navigation=patch("ai_test_generator.gui.messagebox.askyesnocancel",return_value=True)
        navigation.start();self.addCleanup(navigation.stop)
        runtime = Mock()
        runtime.ensure_ready.return_value = ModelStatus("ready")
        try:
            self.app = App(runtime=runtime)
        except tkinter.TclError as exc:
            self.skipTest(f"Tkinter недоступен: {exc}")
        self.app.withdraw()
        questions = [fixture(kind) for kind in ("choice", "sequence", "matching", "short")]
        for i, q in enumerate(questions):
            q["prompt"] = ["Выберите вычислитель", "Расположите этапы", "Сопоставьте компоненты", "Назовите вычислитель"][i]
        self.app.test = {"questions": questions, "warnings": [], "requested_count": 8}
        self.app.render_questions()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.app.update()
            if self.app.model_status.state == 'ready' and not self.app.busy:
                break
            time.sleep(0.01)
        self.assertEqual(self.app.model_status.state, 'ready', 'GUI fixture must finish its initial connection')
        self.assertFalse(self.app.busy)

    def tearDown(self):
        for timer in self.app.tk.splitlist(self.app.tk.call("after", "info")):
            # Tcl/ttk also schedules native list-valued scripts; Tkinter's
            # wrapper tries to delete these as Python command strings.
            self.app.tk.call("after", "cancel", timer)
        self.app.destroy()

    def test_three_sections_and_type_specific_editors(self):
        self.assertEqual(len(self.app.notebook.tabs()), 3)
        self.assertEqual(len(self.app.cards), 4)
        for card in self.app.cards:
            card.edit()
        self.assertEqual(len(self.app.cards[0].option_vars), 4)
        self.assertEqual(len(self.app.cards[1].option_vars), 3)
        self.assertEqual(len(self.app.cards[2].right_vars), 3)
        self.assertEqual(len(self.app.cards[3].option_vars), 0)

    def test_edit_updates_question_and_preview(self):
        card = self.app.cards[0]
        card.edit()
        card.prompt_box.delete("1.0", "end")
        card.prompt_box.insert("1.0", "Какой вычислитель упомянут?")
        self.assertTrue(self.app.commit_edits())
        self.assertTrue(self.app.test["questions"][0]["edited"])
        self.assertIn("Какой вычислитель упомянут?", self.app.preview.get("1.0", "end"))

    def test_invalid_answer_does_not_replace_question(self):
        before = copy.deepcopy(self.app.test["questions"][0])
        card = self.app.cards[0]
        card.edit()
        card.answer_var.set("99")
        with patch("ai_test_generator.gui.messagebox.showerror"):
            self.assertFalse(self.app.commit_edits())
        from ai_test_generator.review import fingerprint,question_status
        self.assertEqual(fingerprint(self.app.test["questions"][0]),fingerprint(before))
        self.assertEqual(question_status(self.app.test["questions"][0]),"Требует проверки")

    def test_answers_and_quote_start_collapsed(self):
        card = self.app.cards[0]
        self.assertFalse(card.answer_area.winfo_manager())
        self.assertFalse(card.quote_area.winfo_manager())
        self.app.show_answers.set(True)
        self.app.toggle_answers()
        self.assertTrue(self.app.cards[0].answer_area.winfo_manager())

    def test_generation_is_disabled_until_model_ready(self):
        from ai_test_generator.extraction import Material
        self.app.material = Material("source", "CPU")
        self.app.set_model_status(ModelStatus("missing"))
        self.assertTrue(self.app.generate_button.instate(["disabled"]))
        self.app.set_model_status(ModelStatus("ready"))
        self.assertFalse(self.app.generate_button.instate(["disabled"]))

    def test_generation_checks_connection_before_using_model(self):
        from ai_test_generator.extraction import Material
        self.app.test = None
        self.app.material = Material("source", "CPU")
        self.app.runtime.ensure_ready.return_value = ModelStatus("missing")
        with patch("ai_test_generator.gui.generate_test") as generate:
            self.app.generate()
            deadline = time.monotonic() + 2
            while self.app.busy and time.monotonic() < deadline:
                self.app.update()
                time.sleep(0.01)
            generate.assert_not_called()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.model_status.state, "missing")

    def test_reconnect_and_generation_complete_without_manual_server_command(self):
        from ai_test_generator.extraction import Material
        self.app.test = None
        self.app.material = Material("source", "CPU")
        result = {"questions": [fixture()], "requested_count": 8, "warnings": []}
        with patch("ai_test_generator.gui.generate_test", return_value=result):
            self.app.generate()
            deadline = time.monotonic() + 2
            while self.app.busy and time.monotonic() < deadline:
                self.app.update()
                time.sleep(0.01)
        self.assertFalse(self.app.busy)
        self.assertEqual(len(self.app.cards), 1)
        self.assertEqual(self.app.model_status.state, "ready")
