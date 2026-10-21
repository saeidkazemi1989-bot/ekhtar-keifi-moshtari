#!/usr/bin/env python3
"""اجرای داشبورد به‌صورت برنامهٔ محلی با امکان ذخیرهٔ فرم‌های 8D.

    python serve.py                # پورت ۸۰۰۰، باز کردن مرورگر
    python serve.py --port 8800    # پورت دلخواه
    python serve.py --no-browser   # بدون باز کردن مرورگر

داشبورد از مسیر /index.html باز می‌شود و فرم‌های 8D در فایل
`output/8d-forms.json` ذخیره می‌شوند. با `python build_report.py`، همین
داده‌ها در اکسل، فایل ورد و داشبورد لحاظ می‌شوند.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import os
import subprocess
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import sys

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
STORE = OUTPUT / "8d-forms.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import eight_d_store  # noqa: E402

MAX_BODY = 200_000
BUILD_LOG = OUTPUT / "rebuild.log"
BUILD_TIMEOUT = 900
BUILD_LOCK = threading.Lock()
BUILD_STATE: dict = {
    "state": "idle",
    "started": None,
    "finished": None,
    "error": "",
    "returncode": None,
}


def _build_snapshot() -> dict:
    """وضعیت لحظه‌ای ساخت گزارش برای نمایش در داشبورد."""
    with BUILD_LOCK:
        snapshot = dict(BUILD_STATE)
    started = snapshot.get("started")
    if started:
        end = snapshot.get("finished") or time.time()
        snapshot["elapsed"] = round(end - started, 1)
    else:
        snapshot["elapsed"] = 0
    log_tail = ""
    if BUILD_LOG.exists():
        try:
            log_tail = BUILD_LOG.read_text(encoding="utf-8", errors="replace")[-4000:]
        except OSError:
            log_tail = ""
    snapshot["log"] = log_tail
    return snapshot


def _run_build() -> None:
    """اجرای build_report.py در پس‌زمینه؛ پورت سرور بلاک نمی‌شود."""
    code = 1
    error = ""
    try:
        with BUILD_LOG.open("w", encoding="utf-8") as handle:
            process = subprocess.run(
                [sys.executable, str(ROOT / "build_report.py")],
                cwd=str(ROOT),
                stdout=handle,
                stderr=subprocess.STDOUT,
                timeout=BUILD_TIMEOUT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        code = process.returncode
    except subprocess.TimeoutExpired:
        error = "ساخت گزارش بیش از ۱۵ دقیقه طول کشید و متوقف شد"
    except Exception as exc:  # noqa: BLE001
        error = str(exc)

    if code != 0 and not error:
        try:
            tail = BUILD_LOG.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            error = tail[-1] if tail else f"ساخت گزارش با کد {code} متوقف شد"
        except OSError:
            error = f"ساخت گزارش با کد {code} متوقف شد"

    with BUILD_LOCK:
        BUILD_STATE.update(
            state="done" if code == 0 and not error else "error",
            finished=time.time(),
            error=error,
            returncode=code,
        )


def _start_build() -> bool:
    """شروع ساخت؛ اگر ساخت دیگری در جریان است False برمی‌گرداند."""
    with BUILD_LOCK:
        if BUILD_STATE["state"] == "running":
            return False
        BUILD_STATE.update(
            state="running",
            started=time.time(),
            finished=None,
            error="",
            returncode=None,
        )
    try:
        BUILD_LOG.write_text("", encoding="utf-8")
    except OSError:
        pass
    threading.Thread(target=_run_build, daemon=True).start()
    return True


class Handler(SimpleHTTPRequestHandler):
    server_version = "EkhtarDashboard/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(OUTPUT), **kwargs)

    # ------------------------------------------------------------------ کمکی
    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, text: str, status: int = 200, content_type="text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path) -> None:
        if not path.exists():
            self._json({"error": "فایل پیدا نشد"}, 404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="8d-forms{path.suffix}"')
        self.end_headers()
        self.wfile.write(data)

    def send_response(self, code, message=None) -> None:  # noqa: D401
        self._cache_control_sent = False
        super().send_response(code, message)

    def send_header(self, keyword, value) -> None:
        if keyword.lower() == "cache-control":
            self._cache_control_sent = True
        super().send_header(keyword, value)

    def end_headers(self) -> None:
        # داشبورد و فایل دادهٔ آن باید بعد از «به‌روزرسانی» تازه خوانده شوند.
        path = urlparse(self.path).path.lower()
        if not getattr(self, "_cache_control_sent", False) and path.endswith((".html", ".js")):
            super().send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        if "/api/" in (fmt % args):
            return

    # ------------------------------------------------------------------ مسیرها
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path in {"/api/rebuild", "/api/rebuild/", "/api/rebuild/status"}:
            self._json(_build_snapshot())
            return
        if path in {"/api/8d", "/api/8d/"}:
            entries = eight_d_store.load(STORE)
            serials = list(entries.keys())
            self._json(
                {
                    "entries": entries,
                    "stats": eight_d_store.stats(entries, serials),
                    "fields": eight_d_store.FIELDS,
                    "statuses": list(eight_d_store.STATUS_OPTIONS),
                }
            )
            return
        if path == "/api/8d/export.json":
            self._file(STORE)
            return
        if path == "/api/8d/export.csv":
            entries = eight_d_store.load(STORE)
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            header = ["سریال اخطار"] + list(eight_d_store.FIELDS.values()) + ["وضعیت فرم", "درصد تکمیل", "آخرین به‌روزرسانی"]
            writer.writerow(header)
            for serial, entry in entries.items():
                writer.writerow(
                    [serial]
                    + [entry.get(field, "") for field in eight_d_store.FIELDS]
                    + [
                        eight_d_store.status_of(entry),
                        eight_d_store.percent(entry),
                        entry.get("updated", "").replace("T", " "),
                    ]
                )
            csv_path = OUTPUT / "فرم‌های 8D.csv"
            csv_path.write_text("\ufeff" + buffer.getvalue(), encoding="utf-8")
            self._file(csv_path)
            return
        if path in {"/", ""}:
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path in {"/api/rebuild", "/api/rebuild/"}:
            started = _start_build()
            payload = _build_snapshot()
            payload.update({"ok": True, "startedNow": started})
            self._json(payload, 200 if started else 409)
            return
        if path not in {"/api/8d", "/api/8d/"}:
            self._json({"error": "مسیر ناشناخته"}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self._json({"error": "حجم درخواست نامعتبر است"}, 400)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._json({"error": "JSON نامعتبر"}, 400)
            return

        serial = payload.get("serial")
        if serial in (None, ""):
            self._json({"error": "شماره سریال اخطار لازم است"}, 400)
            return
        values = payload.get("values") or payload.get("fields") or {}
        if not isinstance(values, dict):
            self._json({"error": "ساختار داده نامعتبر"}, 400)
            return
        if payload.get("number"):
            values["number"] = payload["number"]

        entry = eight_d_store.update(serial, values, STORE)
        entries = eight_d_store.load(STORE)
        self._json(
            {
                "ok": True,
                "serial": str(serial),
                "entry": entry,
                "status": eight_d_store.status_of(entry),
                "percent": eight_d_store.percent(entry),
                "stats": eight_d_store.stats(entries, list(entries.keys())),
            }
        )

    def do_DELETE(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if not path.startswith("/api/8d/"):
            self._json({"error": "مسیر ناشناخته"}, 404)
            return
        serial = path.rsplit("/", 1)[-1]
        entries = eight_d_store.load(STORE)
        entries.pop(str(serial), None)
        eight_d_store.save_all(entries, STORE)
        self._json({"ok": True, "stats": eight_d_store.stats(entries, list(entries.keys()))})


def main() -> int:
    parser = argparse.ArgumentParser(description="اجرای داشبورد اخطارهای کیفی با ذخیرهٔ فرم‌های 8D")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not (OUTPUT / "index.html").exists():
        print("داشبورد ساخته نشده است. اول اجرا کنید:  python build_report.py")
        return 1

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://localhost:{args.port}/"
    print("=" * 60)
    print("  داشبورد اخطارهای کیفی — حالت ویرایش فرم‌های 8D")
    print("=" * 60)
    print(f"  آدرس:            {url}")
    print(f"  ذخیرهٔ فرم‌ها:    {STORE}")
    print("  به‌روزرسانی داده:  دکمهٔ «⟳ به‌روزرسانی داده‌ها» در داشبورد")
    print("  برای توقف:       Ctrl+C")
    print("=" * 60)
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nمتوقف شد.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
