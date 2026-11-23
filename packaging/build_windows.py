"""Build a self-contained Windows folder on a Windows runner (no Python needed by recipient)."""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / 'portable-windows'
PYTHON_VERSION = '3.12.10'
URL = f'https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip'


def main():
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 12):
        raise SystemExit('Build this package on 64-bit Windows with Python 3.12.')
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir()
    runtime = STAGE / 'runtime'
    runtime.mkdir()
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / 'python.zip'
        urllib.request.urlretrieve(URL, archive)
        with zipfile.ZipFile(archive) as z:
            z.extractall(runtime)
    (runtime / 'python312._pth').write_text('python312.zip\n.\nLib\\site-packages\nimport site\n', encoding='utf-8')
    site = runtime / 'Lib' / 'site-packages'
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:', '--target', str(site), '-r', str(ROOT / 'requirements.txt')], check=True)
    for file in ('build_report.py', 'serve.py'):
        shutil.copy2(ROOT / file, STAGE / file)
    shutil.copytree(ROOT / 'src', STAGE / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for file in ROOT.iterdir():
        if file.is_file() and file.suffix.lower() in ('.xlsx', '.docx'):
            shutil.copy2(file, STAGE / file.name)
    shutil.copy2(ROOT / 'packaging' / 'start_windows.bat', STAGE / 'start.bat')
    shutil.copy2(ROOT / 'packaging' / 'windows_readme.txt', STAGE / 'راهنمای اجرا.txt')
    (STAGE / 'data').mkdir()
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    subprocess.run([str(runtime / 'python.exe'), str(STAGE / 'build_report.py')], cwd=STAGE, env=env, check=True, timeout=600)
    print('Portable package is ready:', STAGE, flush=True)


if __name__ == '__main__':
    main()
