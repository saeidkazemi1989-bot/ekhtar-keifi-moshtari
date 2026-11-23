import json
import tempfile
import threading
import unittest
from pathlib import Path

import pandas as pd

from src import manual_fix
from src.report_html import add_status_group, STATUS_CLOSED, STATUS_IN_REVIEW, STATUS_NOT_RECEIVED


class ManualFixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'fixes.json'

    def test_save_update_bulk_and_restore(self):
        manual_fix.update('1', {'root': '  اتصالی  ', 'process': 'تولید'}, self.path)
        manual_fix.update_many(['1', '2'], {'part': 'LCD'}, self.path)
        data = manual_fix.load(self.path)
        self.assertEqual(data['1']['root'], 'اتصالی')
        self.assertEqual(data['1']['process'], 'تولید')
        self.assertEqual(data['2']['part'], 'LCD')
        manual_fix.update('1', {'root': '', 'part': '', 'process': ''}, self.path)
        self.assertNotIn('1', manual_fix.load(self.path))
        self.assertIn('2', manual_fix.load(self.path))

    def test_parallel_updates_do_not_lose_entries(self):
        workers = [threading.Thread(target=manual_fix.update, args=(str(n), {'root': str(n)}, self.path)) for n in range(20)]
        for w in workers: w.start()
        for w in workers: w.join()
        self.assertEqual(len(manual_fix.load(self.path)), 20)

    def test_corrupt_file_is_not_overwritten(self):
        self.path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(json.JSONDecodeError):
            manual_fix.update('1', {'root': 'علت'}, self.path)
        self.assertEqual(self.path.read_text(), '{broken')

    def test_status_and_process_use_manual_values(self):
        df = pd.DataFrame([
            {'سریال اخطار': 1, 'ریشهٔ ایراد': 'اعلام نشده', 'قطعهٔ تحلیل': '', 'منشاء ایراد': '', 'دارای برگه بررسی': 'بله', 'وضعیت اخطار': 'خاتمه يافته', 'آنالیز علت ایراد': ''},
            {'سریال اخطار': 2, 'ریشهٔ ایراد': 'اعلام نشده', 'قطعهٔ تحلیل': '', 'منشاء ایراد': '', 'دارای برگه بررسی': 'بله', 'وضعیت اخطار': 'باز', 'آنالیز علت ایراد': ''},
            {'سریال اخطار': 3, 'ریشهٔ ایراد': 'اعلام نشده', 'قطعهٔ تحلیل': '', 'منشاء ایراد': '', 'دارای برگه بررسی': 'بله', 'وضعیت اخطار': 'خاتمه يافته', 'آنالیز علت ایراد': 'عدم دریافت قطعه'},
        ])
        fixed, count = manual_fix.apply(df, {'1': {'root': 'اتصالی', 'part': 'LCD', 'process': 'تولید'}, '2': {'root': 'خرابی'}})
        self.assertEqual(count, 2)
        self.assertEqual(fixed.loc[0, 'مقدار خودکار root'], 'اعلام نشده')
        self.assertEqual(fixed.loc[0, 'منشاء ایراد'], 'تولید')
        grouped = add_status_group(fixed)
        self.assertEqual(grouped['گروه وضعیت'].tolist(), [STATUS_CLOSED, STATUS_IN_REVIEW, STATUS_NOT_RECEIVED])
        self.assertEqual(grouped['ریشهٔ فرآیندی ثبت شده'].tolist(), ['بله', 'خیر', 'خیر'])
        restored, _ = manual_fix.apply(df, {})
        self.assertEqual(add_status_group(restored).loc[0, 'گروه وضعیت'], STATUS_IN_REVIEW)

class FixApiTests(unittest.TestCase):
    def setUp(self):
        import serve
        from http.server import ThreadingHTTPServer
        from unittest.mock import patch
        self.serve = serve
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / 'fix.json'
        p = patch.object(manual_fix, 'store_path', return_value=path)
        p.start(); self.addCleanup(p.stop)
        p = patch.object(serve, '_start_build', return_value=True)
        p.start(); self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), serve.Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, payload=None):
        import urllib.request
        req = urllib.request.Request(
            f'http://127.0.0.1:{self.server.server_port}/api/fix',
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Content-Type': 'application/json'}, method=method)
        with urllib.request.urlopen(req) as response:
            return json.load(response)

    def test_real_api_partial_and_batch_updates(self):
        self.request('POST', {'serial': 1, 'root': 'علت', 'process': 'تولید'})
        self.request('POST', {'serials': [1, 2], 'part': 'LCD'})
        entries = self.request('GET')['entries']
        self.assertEqual(entries['1']['root'], 'علت')
        self.assertEqual(entries['1']['process'], 'تولید')
        self.assertEqual(entries['2']['part'], 'LCD')
        self.request('POST', {'serial': 1, 'root': ''})
        self.assertNotIn('root', self.request('GET')['entries']['1'])
        self.assertTrue(self.serve._start_build.called)

if __name__ == '__main__':
    unittest.main()
