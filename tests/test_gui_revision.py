"""Regression coverage for source visibility, editing and audit notices."""
import tkinter
import unittest
from unittest.mock import patch

import test_gui
from ai_test_generator.extraction import Material


class GuiRevisionTests(unittest.TestCase):
    setUp = test_gui.GuiTests.setUp
    tearDown = test_gui.GuiTests.tearDown

    def test_destroyed_tk_variables_are_collected_before_starting_worker(self):
        import gc,weakref,threading
        old=self.app.cards[0]
        old.callback_cycle=old
        reference=weakref.ref(old.answer_var)
        self.app.render_questions()
        del old
        was_enabled=gc.isenabled()
        gc.disable()
        completed=threading.Event()
        observed=[]
        def action():
            observed.append(reference() is None)
            completed.set()
        try:
            self.app.start_job('verification',action,'Проверка потока')
            self.assertTrue(completed.wait(2))
            self.assertEqual(observed,[True])
        finally:
            gc.collect()
            if was_enabled:gc.enable()
            self.app.update()


    def test_manual_confirmation_removes_badge_and_is_shown_in_preview(self):
        from ai_test_generator.review import question_status
        self.app.confirm_current()
        q=self.app.test['questions'][0]
        self.assertEqual(question_status(q),'Проверено')
        self.assertIn('Статус: Проверено',self.app.preview.get('1.0','end'))
        card=self.app.cards[0];card.edit();card.answer_var.set('2')
        self.assertEqual(question_status(q),'Требует проверки')

    def test_material_opens_resizable_window_with_full_text_and_selected_fragments(self):
        self.app.material = Material("book.docx", "FIRST\n" + "full material\n" * 200 + "LAST")
        self.app.test["fragments"] = [{"id": 7, "text": "ACTUAL SELECTED FRAGMENT", "pages": [2, 3]}]
        self.app.toggle_material()
        self.assertTrue(hasattr(self.app, "material_window"), "Material must open in its own window")
        self.assertIsInstance(self.app.material_window, tkinter.Toplevel)
        self.assertIn("LAST", self.app.material_text.get("1.0", "end"))
        self.assertIn("ACTUAL SELECTED FRAGMENT", self.app.fragments_text.get("1.0", "end"))
        self.assertIn("2, 3", self.app.fragments_text.get("1.0", "end"))
        self.assertNotIn("full material", self.app.fragments_text.get("1.0", "end"))
        self.app.material_text.tag_add("sel", "1.0", "1.5")
        self.app.material_text.event_generate("<<Copy>>")
        self.assertEqual(self.app.clipboard_get(), "FIRST")

    def test_selecting_question_preserves_pending_edit(self):
        self.assertTrue(hasattr(self.app, "question_list"), "Editor needs a question selector")
        card = self.app.cards[0]
        card.edit()
        card.prompt_box.delete("1.0", "end")
        card.prompt_box.insert("1.0", "Какой вычислитель упомянут?")
        self.app.question_list.selection_set("1")
        self.app.question_list.event_generate("<<TreeviewSelect>>")
        self.app.update()
        self.assertEqual(self.app.test["questions"][0]["prompt"], "Какой вычислитель упомянут?")
        self.assertEqual(self.app.selected_question, 1)

    def test_invalid_pending_edit_blocks_selection(self):
        self.assertTrue(hasattr(self.app, "question_list"), "Editor needs a question selector")
        self.app.cards[0].edit()
        self.app.cards[0].answer_var.set("99")
        with patch("ai_test_generator.gui.messagebox.showerror"):
            self.app.question_list.selection_set("1")
            self.app.question_list.event_generate("<<TreeviewSelect>>")
            self.app.update()
        self.assertEqual(self.app.selected_question, 0)
        self.assertEqual(self.app.cards[0].answer_var.get(), "99")

    def test_delete_selected_question_updates_list_preview_and_test(self):
        self.assertTrue(hasattr(self.app, "delete_question"), "Editor needs question deletion")
        self.app.delete_question()
        self.assertEqual(len(self.app.test["questions"]), 3)
        self.assertNotIn("Выберите вычислитель", self.app.preview.get("1.0", "end"))
        self.assertEqual(len(self.app.question_list.get_children()), 3)

    def test_review_is_visible_without_presenting_answer_as_verified(self):
        self.app.test["questions"][0].update(review_required=True, review_reasons=["Неоднозначный источник"])
        self.app.show_answers.set(True)
        self.app.render_questions()
        preview = self.app.preview.get("1.0", "end")
        self.assertIn("ТРЕБУЕТ ПРОВЕРКИ", preview)
        first_question = preview.split("2. ")[0]
        self.assertNotIn("Правильный ответ:", first_question)
        self.assertIn("Неоднозначный источник", first_question)

    def test_remarks_include_rejected_attempt_and_copy_all(self):
        self.app.test["attempts"] = [{"type": "short", "slot": 2, "attempt": 3,
            "fragment_id": 7, "status": "rejected", "reason": "Источник не подтверждает ответ",
            "action": "Повторная попытка"}]
        self.app.refresh_preview()
        remarks = self.app.warnings.get("1.0", "end")
        self.assertIn("Источник не подтверждает ответ", remarks)
        self.assertIn("Повторная попытка", remarks)
        self.assertTrue(hasattr(self.app, "copy_warnings"), "Remarks need copy all")
        self.app.copy_warnings()
        self.assertEqual(self.app.clipboard_get(), remarks.rstrip("\n"))

    def test_title_is_preserved_when_applying_edits(self):
        self.assertTrue(hasattr(self.app, "test_name"), "Creation needs a test name")
        self.app.test_name.set("Проверка архитектуры")
        self.assertTrue(self.app.commit_edits())
        self.assertEqual(self.app.test["title"], "Проверка архитектуры")

    def test_source_window_close_reopen_refreshes_text_and_page_ids(self):
        self.app.material = Material("first.pdf", "FIRST FULL DOCUMENT")
        self.app.test["fragments"] = [{"id": 1, "text": "first excerpt", "pages": [2]}]
        self.app.toggle_material()
        original_window = self.app.material_window
        self.app.material_window.destroy()
        self.app.material = Material("second.pdf", "SECOND FULL DOCUMENT")
        self.app.test["fragments"] = [{"id": 9, "text": "second excerpt", "pages": [8, 10]}]
        self.app.toggle_material()
        self.assertIsNot(self.app.material_window, original_window)
        self.assertEqual(self.app.material_text.get("1.0", "end-1c"), "SECOND FULL DOCUMENT")
        fragments = self.app.fragments_text.get("1.0", "end-1c")
        self.assertIn("Фрагмент 9", fragments)
        self.assertIn("8, 10", fragments)
        self.assertNotIn("first excerpt", fragments)

    def test_explicit_empty_fragment_list_does_not_invent_question_fragments(self):
        self.app.material = Material("book.docx", "Full material")
        self.app.test["fragments"] = []
        self.app.toggle_material()
        self.assertNotIn("Вычислитель CPU", self.app.fragments_text.get("1.0", "end"))
        self.app.test.pop("fragments")
        self.app.refresh_material_view()
        self.assertIn("Вычислитель CPU", self.app.fragments_text.get("1.0", "end"))

    def test_editing_exposes_answer_form_even_when_answers_hidden(self):
        self.app.cards[0].edit()
        self.assertTrue(self.app.cards[0].answer_area.winfo_manager())
        self.assertFalse(self.app.show_answers.get())

    def test_empty_test_shows_generation_guidance_in_preview(self):
        self.app.test["questions"] = []
        self.app.refresh_preview()
        self.assertIn("Прочитайте замечания", self.app.preview.get("1.0", "end"))

    def test_ctrl_a_and_copy_keep_full_material_selectable(self):
        self.app.material = Material("book.docx", "FIRST\nSECOND\nLAST")
        self.app.toggle_material()
        self.app.material_window.update()
        self.app.material_window.tabs.select(self.app.material_text)
        self.app.material_text.focus_force()
        self.app.update()
        self.app.material_text.event_generate("<Control-KeyPress>", keycode=65)
        self.app.material_text.event_generate("<Control-KeyPress>", keycode=67)
        self.assertEqual(self.app.clipboard_get(), "FIRST\nSECOND\nLAST")

    def test_remarks_pane_opens_large_and_can_resize(self):
        self.app.notebook.select(self.app.result_page)
        self.app.deiconify()
        self.app.update()
        remarks = self.app.warnings.master.master
        old_height = remarks.winfo_height()
        self.assertGreaterEqual(old_height, 100)
        self.assertLessEqual(old_height, 250)
        sash_x, sash_y = self.app.result_panes.sash_coord(0)
        self.app.result_panes.sash_place(0, sash_x, sash_y - 50)
        self.app.update()
        self.assertGreater(remarks.winfo_height(), old_height)



    def test_source_excerpt_can_be_copied_without_editing_question(self):
        card = self.app.cards[0]
        card.toggle_quote()
        self.assertTrue(hasattr(card, "source_excerpt_text"), "Source fragment should be selectable without editing")
        self.assertEqual(card.source_excerpt_text.get("1.0", "end-1c"), card.question["source_excerpt"])
        card.source_excerpt_text.tag_add("sel", "1.0", "1.5")
        card.source_excerpt_text.event_generate("<<Copy>>")
        self.assertEqual(self.app.clipboard_get(), "Вычис")

    def test_deleting_another_question_preserves_valid_pending_edit(self):
        self.app.cards[1].edit()
        self.app.cards[1].prompt_box.delete("1.0", "end")
        self.app.cards[1].prompt_box.insert("1.0", "Расположите этапы работы по источнику")
        self.app.delete_question()
        self.assertEqual(self.app.test["questions"][0]["prompt"], "Расположите этапы работы по источнику")
        self.assertTrue(self.app.test["questions"][0]["edited"])
