#!/usr/bin/env bash
# اجرای داشبورد با امکان تکمیل و ذخیرهٔ فرم‌های 8D
set -u
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[خطا] محیط مجازی پیدا نشد. اول bash run.sh را اجرا کنید."
  exit 1
fi

.venv/bin/python serve.py "$@"
