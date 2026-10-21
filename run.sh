#!/usr/bin/env bash
# ساخت گزارش دسته‌بندی اخطارهای کیفی (لینوکس / مک)
set -u
cd "$(dirname "$0")"

echo "============================================================"
echo "  ساخت گزارش دسته‌بندی اخطارهای کیفی"
echo "============================================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "[خطا] python3 پیدا نشد. پایتون ۳.۱۰ یا بالاتر نصب کنید."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "[۱/۳] ساخت محیط مجازی در .venv ..."
  python3 -m venv .venv || { echo "[خطا] ساخت محیط مجازی ناموفق بود."; exit 1; }
else
  echo "[۱/۳] محیط مجازی موجود است."
fi

echo "[۲/۳] بررسی کتابخانه‌ها ..."
if ! .venv/bin/python -c "import pandas, openpyxl, rapidfuzz, jdatetime, docx" >/dev/null 2>&1; then
  echo "      نصب کتابخانه‌های لازم ..."
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt || { echo "[خطا] نصب کتابخانه‌ها ناموفق بود."; exit 1; }
else
  echo "      همهٔ کتابخانه‌ها نصب هستند."
fi

echo "[۳/۳] ساخت گزارش ..."
echo
.venv/bin/python build_report.py
status=$?

echo
if [ $status -eq 0 ]; then
  echo "پایان موفق. فایل‌ها در پوشهٔ output/ هستند."
else
  echo "ساخت گزارش با خطا تمام شد (کد $status). شرح کامل: output/build.log"
fi
exit $status
