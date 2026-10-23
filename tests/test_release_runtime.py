import unittest,json,copy
from unittest.mock import patch,Mock
from ai_test_generator.ollama_runtime import OllamaRuntime
from ai_test_generator.generation import ModelStatus
from ai_test_generator.review import question_status,fingerprint
from ai_test_generator.extraction import extract
from ai_test_generator.config import TEMP
from pathlib import Path
from test_core import fixture
class ReleaseRuntimeTests(unittest.TestCase):
    def test_download_uses_fixed_local_model_and_reports_progress(self):
        runtime=OllamaRuntime();progress=[]
        response=Mock();response.__enter__=Mock(return_value=iter([b'{"status":"pulling","total":100,"completed":50}\n',b'{"status":"success"}\n']));response.__exit__=Mock(return_value=False)
        with patch.object(runtime,'ensure_ready',side_effect=[ModelStatus('missing'),ModelStatus('ready')]),patch('urllib.request.urlopen',return_value=response) as url:
            self.assertEqual(runtime.pull_model(progress.append).state,'ready')
            request=url.call_args.args[0]
            self.assertEqual(request.full_url,'http://127.0.0.1:11434/api/pull')
            self.assertEqual(json.loads(request.data)['model'],'qwen2.5:1.5b')
            self.assertTrue(any('50%' in s for s in progress))
    def test_no_download_when_model_exists(self):
        runtime=OllamaRuntime()
        with patch.object(runtime,'ensure_ready',return_value=ModelStatus('ready')),patch('urllib.request.urlopen') as url:
            self.assertEqual(runtime.pull_model().state,'ready');url.assert_not_called()
    def test_no_download_if_server_missing(self):
        runtime=OllamaRuntime()
        with patch.object(runtime,'ensure_ready',return_value=ModelStatus('not_found')),patch('urllib.request.urlopen') as url:
            with self.assertRaises(ValueError):runtime.pull_model()
            url.assert_not_called()
    def test_post_confirmation_mutation_invalidates_fingerprint(self):
        from ai_test_generator.review import confirm_question
        q=fixture();confirm_question(q);q['options'][0]='TPU'
        self.assertEqual(question_status(q),'Требует проверки')
