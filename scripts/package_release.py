"""Allowlist packaging: no user documents, models, logs or tests in the binary bundle."""
from pathlib import Path
import hashlib
import shutil
import zipfile
import importlib.metadata as metadata

ROOT=Path(__file__).resolve().parent.parent
RELEASE=ROOT/'release'
SOURCE_FILES=('main.py','README.md','requirements.txt','requirements-build.txt','setup.bat','run.bat','build.bat','build_installer.bat','LICENSE','THIRD_PARTY_NOTICES.md','.gitignore','RELEASE_NOTES.md')

def sources():
    for name in SOURCE_FILES:
        path=ROOT/name
        if path.is_file():yield path
    for folder,pattern in [('ai_test_generator','*.py'),('scripts','*.py'),('tests','*.py'),('licenses','*'),('docs','*.png'),('docs','*.md'),('examples','*.md'),('installer','*.iss')]:
        for path in (ROOT/folder).rglob(pattern):
            if path.is_file() and '__pycache__' not in path.parts:yield path

    for name in ('sample_material.pdf','sample_material.docx'):
        path=ROOT/'examples'/name
        if path.is_file():yield path


def licenses():
    target=ROOT/'licenses';target.mkdir(exist_ok=True)
    names=['PyMuPDF','python-docx','pywin32','lxml','typing_extensions']
    try:metadata.distribution('PyInstaller');names.append('PyInstaller')
    except metadata.PackageNotFoundError:pass
    for name in names:
        dist=metadata.distribution(name)
        for rel in dist.files:
            if rel.name.lower().startswith(('license','copying')) and ('dist-info' in str(rel) or name=='pywin32'):
                origin=Path(dist.locate_file(rel))
                suffix=hashlib.sha256(str(rel).encode()).hexdigest()[:8]
                shutil.copyfile(origin,target/f'{name}-{suffix}-{origin.name}')
    import sys
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.is_file():shutil.copyfile(python_license,target/'Python-LICENSE.txt')
    for license_file in (Path(sys.base_prefix)/'tcl').rglob('license.terms'):
        shutil.copyfile(license_file,target/f'{license_file.parent.name}-license.terms')

def file_digest(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def main():
    RELEASE.mkdir(exist_ok=True);licenses()
    source_zip=RELEASE/'AI-Test-Generator-source.zip'
    with zipfile.ZipFile(source_zip,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sources():archive.write(path,Path('AI-Test-Generator')/path.relative_to(ROOT))
    bundle=ROOT/'dist'/'AI Test Generator'
    if (bundle/'AI Test Generator.exe').is_file():
        for name in ('README.md','LICENSE','THIRD_PARTY_NOTICES.md','RELEASE_NOTES.md'):shutil.copyfile(ROOT/name,bundle/name)
        shutil.copytree(ROOT/'licenses',bundle/'licenses',dirs_exist_ok=True)
        # Publish matching source as a separate Release asset, keeping tests out of the app folder.
        embedded_source=bundle/'source.zip'
        if embedded_source.is_file():embedded_source.unlink()
        for unused in (bundle/'_internal'/'tcl8'/'8.5').glob('tcltest-*.tm'):
            unused.unlink()
        with zipfile.ZipFile(RELEASE/'AI-Test-Generator-Windows-x64.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for path in bundle.rglob('*'):
                if path.is_file() and not any(p in ('temp','logs','output','tests','__pycache__') for p in path.relative_to(bundle).parts):archive.write(path,Path(bundle.name)/path.relative_to(bundle))
    setup=RELEASE/'AI-Test-Generator-Setup.exe'
    if setup.is_file():
        with zipfile.ZipFile(RELEASE/'AI-Test-Generator-Setup.zip','w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
            archive.write(setup,setup.name)
    files=sorted(RELEASE.glob('*.zip'))
    (RELEASE/'SHA256SUMS.txt').write_text('\n'.join(file_digest(p)+'  '+p.name for p in files)+'\n','utf-8')
    print('\n'.join(str(p) for p in files))
if __name__=='__main__':main()
