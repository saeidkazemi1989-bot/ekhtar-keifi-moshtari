"""Exercise the actual embedded runtime, HTTP editing, rebuild and Excel on Windows."""
from __future__ import annotations
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def request(url, payload=None):
    body = None if payload is None else json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)

def main():
    if sys.platform != 'win32':
        raise SystemExit('Run on Windows')
    with tempfile.TemporaryDirectory() as tmp:
        app = Path(tmp) / 'app'
        shutil.copytree(ROOT / 'portable-windows', app)
        embedded = app / 'runtime' / 'python.exe'
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        subprocess.run([str(embedded), '-c', 'import pandas, openpyxl, rapidfuzz, jdatetime, docx'], cwd=app, env=env, check=True, timeout=30)
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        server = subprocess.Popen([str(embedded), 'serve.py', '--host', '127.0.0.1', '--port', str(port), '--no-browser', '--no-watch'], cwd=app, env=env)
        base = f'http://127.0.0.1:{port}/'
        try:
            for _ in range(50):
                if server.poll() is not None:
                    raise RuntimeError('Server exited unexpectedly')
                try:
                    with urllib.request.urlopen(base, timeout=2) as r:
                        html = r.read().decode('utf-8')
                    break
                except OSError:
                    time.sleep(.2)
            else:
                raise RuntimeError('Server did not start')
            assert 'id="fix-open"' in html, 'Missing edit button'
            raw = (app / 'output' / 'dashboard-data.js').read_text(encoding='utf-8')
            data = json.loads(raw.split('window.DASHBOARD_DATA = ', 1)[1].strip().removesuffix(';'))
            serial = data['warnings'][0]['id']
            result = request(base + 'api/fix', {'serial':serial, 'root':'ریشه آزمایشی', 'part':'قطعه آزمایشی', 'process':'تولید'})
            assert result['ok'] and result['buildStarted'], result
            assert request(base + 'api/fix')['entries'][str(serial)]['root'] == 'ریشه آزمایشی'
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                status = request(base + 'api/status')
                if status['state'] == 'done': break
                if status['state'] == 'error': raise RuntimeError(status.get('error'))
                time.sleep(2)
            else: raise TimeoutError('Rebuild did not finish')
            raw = (app / 'output' / 'dashboard-data.js').read_text(encoding='utf-8')
            data = json.loads(raw.split('window.DASHBOARD_DATA = ', 1)[1].strip().removesuffix(';'))
            row = next(x for x in data['warnings'] if x['id'] == serial)
            assert row['rootCause'] == 'ریشه آزمایشی' and row['analysisPart'] == 'قطعه آزمایشی' and row['process'] == 'تولید', row
            # Read the rebuilt workbook with the same bundled runtime.
            code = "import openpyxl,sys; w=openpyxl.load_workbook(sys.argv[1],read_only=True,data_only=True); assert any(any(str(v)=='ریشه آزمایشی' for v in row if v is not None) for row in w['اخطارها'].iter_rows(values_only=True))"
            subprocess.run([str(embedded), '-c', code, str(app / 'output' / 'گزارش دسته‌بندی اخطارهای کیفی.xlsx')], cwd=app, env=env, check=True, timeout=60)
            print('PASS: embedded dependencies, server, edit/save, rebuild, dashboard and Excel', flush=True)
        finally:
            server.terminate()
            try: server.wait(timeout=20)
            except subprocess.TimeoutExpired: server.kill(); server.wait()

if __name__ == '__main__':
    main()
