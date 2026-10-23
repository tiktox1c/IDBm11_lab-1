import copy
import unittest
from ai_test_generator.validation import validate_question
from test_core import fixture


class ManualReviewTests(unittest.TestCase):
    def test_explicit_human_confirmation_survives_revalidation(self):
        q=fixture('short')
        q.update(edited=True,manual_confirmed=True)
        validate_question(q)
        self.assertFalse(q['review_required'])
        self.assertEqual(q['review_reasons'],[])
        validate_question(q)
        self.assertFalse(q['review_required'])

    def test_applying_edit_without_confirmation_still_has_actionable_reason(self):
        q=fixture('short')
        q.update(edited=True,manual_confirmed=False)
        validate_question(q)
        self.assertTrue(q['review_required'])
        self.assertTrue(q['review_reasons'])

    def test_llm_cannot_claim_human_confirmation(self):
        q=fixture('short')
        q.update(edited=False,manual_confirmed=True)
        validate_question(q)
        self.assertTrue(q['review_required'])

    def test_human_confirmation_cannot_bypass_invalid_structure(self):
        q=fixture('choice')
        q.update(edited=True,manual_confirmed=True,answer=99)
        with self.assertRaises(ValueError):validate_question(q)

    def test_duplicate_error_names_value_and_positions(self):
        q=fixture('choice')
        q['options']=['CPU','мышь','cpu','кабель']
        with self.assertRaises(ValueError) as error:validate_question(q)
        self.assertIn('CPU',str(error.exception))
        self.assertIn('1, 3',str(error.exception))

    def test_unseen_name_error_identifies_problematic_name(self):
        q=fixture('short')
        q['prompt']='Как называется столица Франции?'
        with self.assertRaises(ValueError) as error:validate_question(q)
        self.assertIn('Франции',str(error.exception))

