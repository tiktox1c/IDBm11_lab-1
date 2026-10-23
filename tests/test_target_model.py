import unittest
from ai_test_generator.config import MODEL
from ai_test_generator.generation import ModelStatus

class TargetModelTests(unittest.TestCase):
    def test_only_user_selected_model_is_used_and_named(self):
        self.assertEqual(MODEL,'qwen2.5:1.5b')
        self.assertIn('Qwen2.5 1.5B',ModelStatus('ready').message)
        self.assertIn('ollama pull qwen2.5:1.5b',ModelStatus('missing').message)

if __name__=='__main__':
    unittest.main()
