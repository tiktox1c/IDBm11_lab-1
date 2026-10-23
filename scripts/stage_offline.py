"""Stage an offline CPU package from existing files; never download a model."""
from pathlib import Path
import argparse
import json
import shutil
import sys
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from ai_test_generator.installation import model_files,MODEL_MANIFEST

def copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)

def stage(models,ollama=None):
    models=Path(models).resolve();ollama=Path(ollama or ROOT/'tools/Ollama').resolve()
    output=ROOT/'temp/offline-payload'
    if output.exists():
        if output.resolve().parent!= (ROOT/'temp').resolve() or output.is_symlink():raise ValueError('Unsafe staging path')
        shutil.rmtree(output)
    output.mkdir(parents=True,exist_ok=True)
    required=model_files(models,verify=True)
    bundle=ROOT/'dist/AI Test Generator'
    if not (bundle/'AI Test Generator.exe').is_file():raise ValueError('Сначала соберите приложение через build.bat')
    # Build the application from an allowlist of generated distribution resources.
    for path in bundle.rglob('*'):
        relative=path.relative_to(bundle)
        if path.is_file() and not any(p in ('temp','logs','output','tests','__pycache__') for p in relative.parts) and relative.name not in ('installation.ini','source.zip'):
            copy(path,output/'app'/relative)
    copy(ollama/'ollama.exe',output/'runtime/ollama.exe')
    library=ollama/'lib/ollama'
    for path in library.iterdir():
        if path.is_file() and (path.suffix.lower()=='.dll' or path.name=='llama-server.exe' or 'LICENSE' in path.name.upper()):
            copy(path,output/'runtime/lib/ollama'/path.name)
    if not (output/'runtime/lib/ollama/llama-server.exe').is_file():raise ValueError('Не найден CPU runner Ollama')
    for relative in required:copy(models/relative,output/'models'/relative)
    manifest=json.loads((models/MODEL_MANIFEST).read_text('utf-8'))
    license_entry=next(x for x in manifest['layers'] if x.get('mediaType','').endswith('.license'))
    license_file=models/'blobs'/license_entry['digest'].replace(':','-')
    copy(license_file,ROOT/'licenses/Qwen2.5-1.5B-LICENSE.txt')
    for name in ('Qwen2.5-1.5B-LICENSE.txt','Ollama-LICENSE.txt'):
        if not (ROOT/'licenses'/name).is_file():raise ValueError('Не найден текст лицензии '+name)
        copy(ROOT/'licenses'/name,output/'app/licenses'/name)
    (output/'runtime-checks.iss').write_text('\n'.join("ExpectedRuntimeFiles.Add('"+str(p.relative_to(output/'runtime'))+"');" for p in (output/'runtime').rglob('*') if p.is_file())+'\n','utf-8')
    (output/'model-checks.iss').write_text('\n'.join("ExpectedBlobs.Add('"+p.name+"');" for p in required if p.parent.name=='blobs')+'\n','utf-8')
    summary={'model':'qwen2.5:1.5b','model_files':len(required),'model_sha256_verified':True,
             'app_bytes':sum(p.stat().st_size for p in (output/'app').rglob('*') if p.is_file()),
             'runtime_bytes':sum(p.stat().st_size for p in (output/'runtime').rglob('*') if p.is_file()),
             'model_bytes':sum((models/p).stat().st_size for p in required),'payload_bytes':sum(p.stat().st_size for p in output.rglob('*') if p.is_file())}
    (output/'payload-sizes.iss').write_text('\n'.join('#define '+name+' '+str(summary[key]) for name,key in [('AppBytes','app_bytes'),('RuntimeBytes','runtime_bytes'),('ModelBytes','model_bytes')])+'\n','utf-8')
    (output/'payload-info.json').write_text(json.dumps(summary,indent=2),'utf-8')
    print(json.dumps(summary,indent=2));return output

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--models',type=Path,required=True);parser.add_argument('--ollama',type=Path)
    args=parser.parse_args();stage(args.models,args.ollama)
