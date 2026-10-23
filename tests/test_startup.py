import unittest
from unittest.mock import patch
import main
class StartupTests(unittest.TestCase):
    def test_windowless_startup_failure_is_reported(self):
        with patch('ai_test_generator.gui.App',side_effect=RuntimeError('test startup failure')),patch('ctypes.windll.user32.MessageBoxW') as dialog:
            self.assertEqual(main.main(),1)
            dialog.assert_called_once()
