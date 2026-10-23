"""Optional integration regression using the real local Inno compiler; no model weights."""
import hashlib,json,os,subprocess,tempfile,unittest
from pathlib import Path
from ai_test_generator.config import ROOT,TEMP,prepare_temp

@unittest.skipUnless(os.name=='nt' and (ROOT/'tools/InnoSetup/ISCC.exe').is_file(),'Local portable Inno Setup compiler not present')
class InstallerScriptTests(unittest.TestCase):
    def test_config_rootfs_is_not_a_nested_manifest_and_corruption_is_rejected(self):
        prepare_temp()
        with tempfile.TemporaryDirectory(dir=TEMP) as directory:
            folder=Path(directory)
            def model(store,corrupt=False):
                (store/'blobs').mkdir(parents=True)
                def blob(data,media):
                    digest=hashlib.sha256(data).hexdigest();(store/'blobs'/('sha256-'+digest)).write_bytes(data)
                    return {'digest':'sha256:'+digest,'size':len(data),'mediaType':media}
                config=blob(json.dumps({'rootfs':{'type':'layers','diff_ids':['sha256:'+'0'*64]}}).encode(),'application/vnd.docker.container.image.v1+json')
                data=blob(b'real integration fixture','application/vnd.ollama.image.model')
                nested=blob(json.dumps({'schemaVersion':2,'config':config,'layers':[data]}).encode(),'application/vnd.ollama.image.manifest')
                manifest=store/'manifests/registry.ollama.ai/library/qwen2.5/1.5b';manifest.parent.mkdir(parents=True)
                manifest.write_text(json.dumps({'schemaVersion':2,'config':config,'layers':[data,nested]}),'utf-8')
                if corrupt:(store/'blobs'/data['digest'].replace(':','-')).write_bytes(b'x'*data['size'])
            good=folder/'valid';bad=folder/'bad';model(good);model(bad,True)
            source=(ROOT/'installer/offline.iss').read_text('utf-8-sig');helpers=source[source.index('function HexDigest('):source.index('function RunningWithoutModel')]
            header=f'[Setup]\nAppName=Installer regression\nAppVersion=1\nDefaultDirName={folder}\nCreateAppDir=no\nUninstallable=no\nPrivilegesRequired=lowest\nOutputDir={folder}\nOutputBaseFilename=probe\n[Code]\n'
            tail="\nfunction InitializeSetup: Boolean;\nbegin\n  Log('VALID='+IntToStr(Ord(ExistingModelComplete('"+str(good)+"'))));\n  Log('CORRUPT='+IntToStr(Ord(ExistingModelComplete('"+str(bad)+"'))));\n  Result:=False;\nend;\n"
            script=folder/'probe.iss';script.write_text(header+helpers+tail,'utf-8-sig')
            flags=subprocess.CREATE_NO_WINDOW
            result=subprocess.run([str(ROOT/'tools/InnoSetup/ISCC.exe'),'/Q',str(script)],capture_output=True,creationflags=flags,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace'))
            log=folder/'probe.log'
            subprocess.run([str(folder/'probe.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES',f'/LOG={log}'],creationflags=flags,timeout=30)
            content=log.read_text('utf-8-sig');self.assertIn('VALID=1',content);self.assertIn('CORRUPT=0',content)

    def test_default_paths_without_parameters_or_installed_model(self):
        prepare_temp()
        with tempfile.TemporaryDirectory(dir=TEMP) as directory:
            folder=Path(directory);profile=folder/'empty-profile';profile.mkdir()
            source=(ROOT/'installer/offline.iss').read_text('utf-8-sig')
            helpers=source[source.index('function DefaultAppDir('):source.index('procedure InitializeWizard;')]
            header=f'[Setup]\nAppName=Default paths regression\nAppVersion=1\nDefaultDirName={folder / "application"}\nCreateAppDir=no\nUninstallable=no\nPrivilegesRequired=lowest\nOutputDir={folder}\nOutputBaseFilename=probe\n[Code]\nconst AppBytes=3145728; RuntimeBytes=5242880; ModelBytes=104857600;\nvar\n StoragePage: TInputDirWizardPage;\n ExpectedRuntimeFiles: TStringList;\n LastDefaultRuntime, LastDefaultModels: String;\n IncludeRuntime, IncludeModels: Boolean;\n'
            tail="""
procedure InitializeWizard;
begin
  StoragePage:=CreateInputDirPage(wpSelectDir,'Test','Test','Test',False,'');
  StoragePage.Add('Ollama');StoragePage.Add('Models');
  ExpectedRuntimeFiles:=TStringList.Create;
  ExpectedRuntimeFiles.Add('nonexistent-runtime-file');
  try
    SetStorageDefaults;
    Log('DEFAULT_MODELS='+ModelsDir(''));
  except
    Log('DEFAULT_ERROR='+GetExceptionMessage);
  end;
end;
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin Result:='Regression probe stops before installation';end;
"""
            tail=tail.replace('  try\n',"  WizardForm.DirEdit.Text := '"+str(folder/'application')+"';\n  try\n")
            script=folder/'probe.iss';script.write_text(header+helpers+tail,'utf-8-sig')
            result=subprocess.run([str(ROOT/'tools/InnoSetup/ISCC.exe'),'/Q',str(script)],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace'))
            env=os.environ.copy();env['OLLAMA_MODELS']='';env['USERPROFILE']=str(profile)
            log=folder/'probe.log'
            subprocess.run([str(folder/'probe.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES',f'/LOG={log}'],env=env,creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)
            content=log.read_text('utf-8-sig')
            self.assertIn('DEFAULT_MODELS='+str(folder/'application/models'),content)
            self.assertNotIn('DEFAULT_ERROR=',content)

    def test_new_space_total_counts_runtime_and_model_and_handles_reuse(self):
        prepare_temp()
        with tempfile.TemporaryDirectory(dir=TEMP) as directory:
            folder=Path(directory);source=(ROOT/'installer/offline.iss').read_text('utf-8-sig')
            start=source.find('function RequiredNewBytes:')
            helpers=source[start:source.index('function LocalDirectory(')] if start>=0 else ''
            header=f'[Setup]\nAppName=Space regression\nAppVersion=1\nDefaultDirName={folder}\nCreateAppDir=no\nUninstallable=no\nPrivilegesRequired=lowest\nOutputDir={folder}\nOutputBaseFilename=probe\n[Code]\nconst AppBytes=3145728; RuntimeBytes=5242880; ModelBytes=104857600;\nvar IncludeRuntime, IncludeModels: Boolean;\n'
            tail="""
function InitializeSetup: Boolean;
begin
  IncludeRuntime:=True;IncludeModels:=True;Log('FRESH='+IntToStr(RequiredNewBytes));
  IncludeModels:=False;Log('MODEL_REUSED='+IntToStr(RequiredNewBytes));
  IncludeRuntime:=False;Log('BOTH_REUSED='+IntToStr(RequiredNewBytes));
  IncludeModels:=True;Log('RUNTIME_REUSED='+IntToStr(RequiredNewBytes));
  Result:=False;
end;
"""
            script=folder/'probe.iss';script.write_text(header+helpers+tail,'utf-8-sig')
            result=subprocess.run([str(ROOT/'tools/InnoSetup/ISCC.exe'),'/Q',str(script)],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace'))
            log=folder/'probe.log'
            subprocess.run([str(folder/'probe.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES',f'/LOG={log}'],creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)
            content=log.read_text('utf-8-sig')
            for expected in ('FRESH=113246208','MODEL_REUSED=8388608','BOTH_REUSED=3145728','RUNTIME_REUSED=108003328'):self.assertIn(expected,content)
