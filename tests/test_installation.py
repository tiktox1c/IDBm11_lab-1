import configparser
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ai_test_generator.config import TEMP,prepare_temp
from ai_test_generator.generation import ModelStatus
from ai_test_generator.ollama_runtime import OllamaRuntime
from ai_test_generator.installation import installed_paths,model_present,model_files,MODEL_MANIFEST

class InstallationTests(unittest.TestCase):
    def setUp(self):
        prepare_temp();self.temp=tempfile.TemporaryDirectory(dir=TEMP);self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def model(self):
        root=self.root/'models';blob=b'local test blob';digest=hashlib.sha256(blob).hexdigest()
        (root/'blobs').mkdir(parents=True);(root/'blobs'/('sha256-'+digest)).write_bytes(blob)
        manifest=root/'manifests/registry.ollama.ai/library/qwen2.5/1.5b';manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({'layers':[{'digest':'sha256:'+digest,'size':len(blob)}]}),'utf-8')
        return root
    def test_no_configuration_keeps_existing_behavior(self):self.assertEqual(installed_paths(self.root),{})
    def test_configuration_is_local_and_does_not_expand_percent_environment(self):
        exe=self.root/'Ollama/ollama.exe';exe.parent.mkdir();exe.write_bytes(b'test')
        models=self.model();(self.root/'installation.ini').write_text(f'[paths]\nollama={exe}\nmodels={models}\n','utf-8')
        settings=installed_paths(self.root);self.assertEqual(settings['ollama'],exe);self.assertEqual(settings['models'],models)
    def test_relative_paths_are_rejected(self):
        (self.root/'installation.ini').write_text('[paths]\nollama=..\\ollama.exe\nmodels=..\\models\n','utf-8')
        self.assertEqual(installed_paths(self.root),{})
    def test_model_presence_requires_referenced_files(self):
        model=self.model();self.assertTrue(model_present(model))
        next((model/'blobs').iterdir()).unlink();self.assertFalse(model_present(model))
    def test_running_server_with_different_store_is_not_restarted(self):
        models=self.model();runtime=OllamaRuntime()
        with patch('ai_test_generator.ollama_runtime.installed_paths',return_value={'models':models}),patch('ai_test_generator.ollama_runtime.check_ollama',return_value=ModelStatus('missing')),patch('ai_test_generator.ollama_runtime.subprocess.Popen') as spawn:
            status=runtime.ensure_ready();self.assertEqual(status.state,'connection_error');self.assertIn('папк',status.message);spawn.assert_not_called()

    def test_verification_rejects_same_size_corruption(self):
        root=self.model();blob=next((root/'blobs').iterdir());blob.write_bytes(b'x'*blob.stat().st_size)
        with self.assertRaisesRegex(ValueError,'Контрольная сумма'):model_files(root,verify=True)

    def test_nested_manifest_includes_its_referenced_blobs(self):
        root=self.model();data=json.loads((root/MODEL_MANIFEST).read_text('utf-8'))
        nested=json.dumps(data).encode();digest=hashlib.sha256(nested).hexdigest()
        (root/'blobs'/('sha256-'+digest)).write_bytes(nested)
        (root/MODEL_MANIFEST).write_text(json.dumps({'layers':[{'digest':'sha256:'+digest,'size':len(nested),'mediaType':'application/vnd.ollama.image.manifest'}]}),'utf-8')
        self.assertEqual(len(model_files(root,verify=True)),3)

    def test_configured_executable_is_preferred_to_path(self):
        from ai_test_generator.ollama_runtime import find_ollama
        exe=self.root/'ollama.exe';exe.write_bytes(b'test')
        with patch('ai_test_generator.ollama_runtime.installed_paths',return_value={'ollama':exe}),patch('ai_test_generator.ollama_runtime.shutil.which') as search:
            self.assertEqual(find_ollama(),str(exe));search.assert_not_called()

    def test_model_path_is_set_for_owned_process_only(self):
        import os
        from unittest.mock import Mock
        models=self.model();process=Mock();process.poll.return_value=None
        before=os.environ.get('OLLAMA_MODELS')
        with patch('ai_test_generator.ollama_runtime.installed_paths',return_value={'models':models}),patch('ai_test_generator.ollama_runtime.find_ollama',return_value='ollama.exe'),patch('ai_test_generator.ollama_runtime.check_ollama',side_effect=[ModelStatus('not_running'),ModelStatus('ready'),ModelStatus('ready')]),patch('ai_test_generator.ollama_runtime.subprocess.Popen',return_value=process) as spawn:
            self.assertEqual(OllamaRuntime().ensure_ready().state,'ready')
            self.assertEqual(spawn.call_args.kwargs['env']['OLLAMA_MODELS'],str(models))
        self.assertEqual(os.environ.get('OLLAMA_MODELS'),before)
