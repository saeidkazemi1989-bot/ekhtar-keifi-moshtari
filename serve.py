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

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import eight_d_store, manual_fix, storage  # noqa: E402

# داده‌های کاربر در data/ نگه داشته می‌شوند (بیرون از پوشهٔ خروجی)
STORE = storage.forms_path()

MAX_BODY = 200_000
MAX_UPLOAD = storage.INPUT_MAX_MB * 1024 * 1024
UPLOAD_CHUNK = 1024 * 1024
BUILD_LOG = OUTPUT / "rebuild.log"
BUILD_TIMEOUT = 900
BUILD_LOCK = threading.Lock()
BUILD_PENDING = False
BUILD_STATE: dict = {
    "state": "idle",
    "started": None,
    "finished": None,
    "error": "",
    "returncode": None,
    "trigger": "",
}

WATCH_ENABLED = True
WATCH_INTERVAL = 3.0
WATCH_DEBOUNCE = 2.0

_BUILD_ID_FILE = OUTPUT / "dashboard-data.js"


def _build_id() -> str:
    """شناسهٔ نسخهٔ فعلی داشبورد؛ با هر ساخت موفق عوض می‌شود."""
    try:
        return str(_BUILD_ID_FILE.stat().st_mtime_ns)
    except OSError:
        return ""


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
    snapshot["buildId"] = _build_id()
    snapshot["watching"] = WATCH_ENABLED
    snapshot["dataFile"] = str(STORE)
    try:
        snapshot["inputs"] = storage.inputs_status()
    except Exception:  # noqa: BLE001 - وضعیت ورودی‌ها نباید داشبورد را بشکند
        snapshot["inputs"] = []
    return snapshot


def _run_build() -> None:
    """اجرای build_report.py در پس‌زمینه؛ پورت سرور بلاک نمی‌شود."""
    code = 1
    error = ""
    # پیش از هر ساخت، از داده‌های کاربر نسخهٔ پشتیبان می‌گیریم
    try:
        storage.backup(STORE)
    except Exception:  # noqa: BLE001 - پشتیبان نباید مانع ساخت شود
        pass
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

    global BUILD_PENDING
    with BUILD_LOCK:
        pending = BUILD_PENDING
        BUILD_PENDING = False
        BUILD_STATE.update(
            state="done" if code == 0 and not error else "error",
            finished=time.time(),
            error=error,
            returncode=code,
        )
    if pending:
        _start_build(trigger="queued")


def _start_build(trigger: str = "manual") -> bool:
    """شروع ساخت؛ اگر ساخت دیگری در جریان است False برمی‌گرداند."""
    global BUILD_PENDING
    with BUILD_LOCK:
        if BUILD_STATE["state"] == "running":
            BUILD_PENDING = True
            return False
        BUILD_STATE.update(
            state="running",
            started=time.time(),
            finished=None,
            error="",
            returncode=None,
            trigger=trigger,
        )
    try:
        BUILD_LOG.write_text("", encoding="utf-8")
    except OSError:
        pass
    threading.Thread(target=_run_build, daemon=True).start()
    return True


def _watch_loop(stop: threading.Event) -> None:
    """تغییر فایل‌های ورودی یا کد را می‌بیند و گزارش را خودکار تازه می‌کند."""
    previous = storage.fingerprint()
    changed_at = 0.0
    while not stop.wait(WATCH_INTERVAL):
        current = storage.fingerprint()
        if current != previous:
            previous = current
            changed_at = time.time()
            continue
        if not changed_at or time.time() - changed_at < WATCH_DEBOUNCE:
            continue
        changed_at = 0.0
        if _start_build(trigger="watch"):
            print("[watch] فایل‌ها تغییر کرد؛ ساخت خودکار گزارش آغاز شد.", flush=True)


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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
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
        if path in {"/api/rebuild", "/api/rebuild/", "/api/rebuild/status", "/api/status"}:
            self._json(_build_snapshot())
            return
        if path in {"/api/inputs", "/api/inputs/"}:
            self._json({"ok": True, "inputs": storage.inputs_status()})
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
        if path in {"/api/fix", "/api/fix/"}:
            entries = manual_fix.load()
            roots = sorted({str(item.get("root")).strip() for item in entries.values() if item.get("root")})
            self._json(
                {
                    "ok": True,
                    "entries": entries,
                    "count": len(entries),
                    "roots": roots,
                    "fields": manual_fix.FIELDS,
                    "path": str(manual_fix.store_path().name),
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
        if path in {"/api/inputs", "/api/inputs/upload", "/api/inputs/"}:
            self._receive_input()
            return
        if path in {"/api/rebuild", "/api/rebuild/"}:
            started = _start_build(trigger="button")
            payload = _build_snapshot()
            payload.update({"ok": True, "startedNow": started})
            self._json(payload, 200 if started else 409)
            return
        if path in {"/api/fix", "/api/fix/"}:
            self._receive_fix()
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

    def _receive_fix(self) -> None:
        """ثبت اصلاح ریشه/قطعهٔ یک اخطار و ساخت دوبارهٔ گزارش.

        بدنه: ``{"serial": 235, "root": "…", "part": "…", "rebuild": true}``
        مقدار خالی یعنی «اصلاح حذف شود و مقدار خودکار برگردد».
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self._json({"error": "حجم درخواست نامعتبر است"}, 400)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._json({"error": "JSON نامعتبر"}, 400)
            return
        if not isinstance(payload, dict):
            self._json({"error": "درخواست نامعتبر است"}, 400)
            return
        serials = payload.get("serials", [payload.get("serial")])
        if not isinstance(serials, list) or not serials or len(serials) > 500 or any(not str(x or "").strip().isdigit() for x in serials):
            self._json({"error": "شماره اخطار نامعتبر است"}, 400)
            return
        values = {field: payload[field] for field in manual_fix.FIELDS if field in payload}
        if not values or any(not isinstance(value, str) or len(value) > 500 for value in values.values()):
            self._json({"error": "مقادیر ارسالی نامعتبر است"}, 400)
            return
        if values.get("process", "") not in ("", "تولید", "مواد اولیه", "تامین‌کننده", "طراحی مهندسی", "مشتری"):
            self._json({"error": "واحد مسئول نامعتبر است"}, 400)
            return
        try:
            entries = manual_fix.update_many(serials, values)
        except Exception as error:  # noqa: BLE001
            self._json({"error": f"ذخیرهٔ اصلاح ناموفق بود: {error}"}, 500)
            return
        started = _start_build(trigger="fix") if payload.get("rebuild", True) else False
        self._json({"ok": True, "entry": entries.get(str(serials[0]), {}), "entries": entries,
                    "count": len(entries), "buildStarted": started, "state": _build_snapshot().get("state")})

    def _receive_input(self) -> None:
        """دریافت فایل ورودی خام (بدنهٔ خام فایل، نه فرم) و ذخیرهٔ نسخهٔ تازه.

        نام فایل در هدر ``X-File-Name`` (UTF-8، percent-encoded) و کلید ورودی در
        هدر ``X-Input-Key`` فرستاده می‌شود؛ کلید می‌تواند خالی باشد و از نام فایل
        تشخیص داده شود.
        """
        from urllib.parse import unquote as _unquote

        key = (_unquote(self.headers.get("X-Input-Key") or "")).strip()
        filename = _unquote(self.headers.get("X-File-Name") or "").strip()
        if not filename:
            self._json({"ok": False, "error": "نام فایل در هدر X-File-Name لازم است"}, 400)
            return
        if not key:
            key = storage.input_key_of_name(filename) or ""
        if key not in storage.INPUT_FILES:
            self._json(
                {
                    "ok": False,
                    "error": "نوع فایل ورودی مشخص نیست؛ یکی از فایل‌های اخطار، ListData، گروه‌بندی، C_Plus، قالب 8D یا فرم برگشتی را انتخاب کنید",
                },
                400,
            )
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json({"ok": False, "error": "فایل خالی است"}, 400)
            return
        if length > MAX_UPLOAD:
            self._json(
                {"ok": False, "error": f"حجم فایل بیشتر از {storage.INPUT_MAX_MB} مگابایت است"},
                413,
            )
            return
        chunks: list[bytes] = []
        remaining = length
        try:
            while remaining > 0:
                chunk = self.rfile.read(min(UPLOAD_CHUNK, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) != length:
                self._json({"ok": False, "error": "دریافت فایل کامل نشد؛ دوباره تلاش کنید"}, 400)
                return
            # اعتبارسنجی سبک: فایل اکسل/ورد واقعی باشد
            if storage.INPUT_EXTENSIONS[key][0] == ".docx" and not payload.startswith(b"PK"):
                self._json({"ok": False, "error": "فایل ورد معتبر نیست (docx لازم است)"}, 400)
                return
            if payload[:4] not in {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"} and key != "template":
                self._json(
                    {"ok": False, "error": "فایل اکسل معتبر نیست؛ فایل xlsx را انتخاب کنید (نه xls قدیمی یا CSV)"},
                    400,
                )
                return
        except Exception:  # noqa: BLE001
            self._json({"ok": False, "error": "خواندن فایل ناموفق بود"}, 400)
            return

        try:
            saved = storage.save_input(key, filename, payload)
        except ValueError as error:
            self._json({"ok": False, "error": str(error)}, 400)
            return
        except Exception as error:  # noqa: BLE001
            self._json({"ok": False, "error": f"ذخیرهٔ فایل ناموفق بود: {error}"}, 500)
            return

        # پس از بارگذاری، گزارش با دادهٔ تازه خودکار ساخته می‌شود
        started = _start_build(trigger="upload")
        state = _build_snapshot()
        self._json(
            {
                "ok": True,
                "input": saved,
                "inputs": state.get("inputs", []),
                "buildStarted": started,
                "state": state.get("state"),
                "buildId": state.get("buildId"),
            }
        )

    def do_DELETE(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path.startswith("/api/fix/"):
            serial = path.rsplit("/", 1)[-1]
            entry = manual_fix.update(serial, {field: "" for field in manual_fix.FIELDS})
            _start_build(trigger="fix")
            self._json({"ok": True, "serial": serial, "entry": entry, "count": len(manual_fix.load())})
            return
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
    parser.add_argument("--no-watch", action="store_true", help="خاموش کردن ساخت خودکار پس از تغییر فایل‌ها")
    args = parser.parse_args()

    global WATCH_ENABLED
    WATCH_ENABLED = not args.no_watch

    if not (OUTPUT / "index.html").exists():
        print("داشبورد ساخته نشده است. اول اجرا کنید:  python build_report.py")
        return 1

    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        print(f"سرور روی پورت {args.port} اجرا نشد: {exc}. اگر نسخهٔ قبلی برنامه باز است، آن را ببندید و دوباره اجرا کنید.")
        return 1
    url = f"http://localhost:{args.port}/"
    print("=" * 60)
    print("  داشبورد اخطارهای کیفی — حالت ویرایش فرم‌های 8D")
    print("=" * 60)
    print(f"  آدرس:            {url}")
    print(f"  ذخیرهٔ فرم‌ها:    {STORE}")
    print(f"  پوشهٔ داده:       {storage.DATA_DIR}")
    print("  به‌روزرسانی:      خودکار پس از تغییر فایل‌ها" + ("" if WATCH_ENABLED else " (خاموش)"))
    print("  دادهٔ تازه:        دکمهٔ «⤒ بارگذاری داده» در نوار بالای داشبورد")
    print(f"  ذخیرهٔ ورودی‌ها:   {storage.DATA_DIR / storage.INPUT_DIR_NAME}")
    print("  برای توقف:       Ctrl+C")
    print("=" * 60)
    stop_watch = threading.Event()
    if WATCH_ENABLED:
        threading.Thread(target=_watch_loop, args=(stop_watch,), daemon=True).start()
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nمتوقف شد.")
    finally:
        stop_watch.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
