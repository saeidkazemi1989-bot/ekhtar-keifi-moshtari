#!/usr/bin/env bash
# به‌روزرسانی برنامه بدون از دست دادن داده‌ها (لینوکس / مک)
#
#   bash update.sh
#
# داده‌های شما در پوشهٔ data/ هستند (فرم‌های 8D، اصلاح ایرادها، اصلاح گروه‌بندی
# و نسخه‌های پشتیبان) و این اسکریپت به آن‌ها دست نمی‌زند.
set -u
cd "$(dirname "$0")"

echo "============================================================"
echo "  به‌روزرسانی برنامهٔ گزارش اخطارهای کیفی"
echo "============================================================"
echo

echo "[۱/۴] بررسی پوشهٔ داده…"
mkdir -p data
if [ -f "output/8d-forms.json" ] && [ ! -f "data/8d-forms.json" ]; then
  cp -p "output/8d-forms.json" "data/8d-forms.json"
  echo "      فرم‌های 8D از output/ به data/ منتقل شد."
fi
for name in "اصلاح ایرادها.xlsx" "اصلاحات گروه‌بندی.xlsx"; do
  if [ -f "$name" ] && [ ! -f "data/$name" ]; then
    cp -p "$name" "data/$name"
    echo "      $name به data/ منتقل شد."
  fi
done
echo "      داده‌های شما دست‌نخورده در data/ است."

echo "[۲/۴] گرفتن نسخهٔ تازهٔ برنامه…"
if [ -d .git ] && command -v git >/dev/null 2>&1; then
  if git pull --ff-only; then
    echo "      برنامه به آخرین نسخه به‌روز شد."
  else
    echo "      [هشدار] git pull انجام نشد؛ با نسخهٔ فعلی ادامه می‌دهیم."
  fi
else
  echo "      این پوشه مخزن git نیست؛ فایل‌های برنامه را جایگزین کنید."
  echo "      فقط پوشهٔ data/ را نگه دارید تا داده‌ها بمانند."
fi

echo "[۳/۴] بررسی کتابخانه‌ها…"
if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv || { echo "[خطا] ساخت محیط مجازی ناموفق بود."; exit 1; }
fi
if ! .venv/bin/python -c "import pandas, openpyxl, rapidfuzz, jdatetime, docx" >/dev/null 2>&1; then
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt || { echo "[خطا] نصب کتابخانه‌ها ناموفق بود."; exit 1; }
fi
echo "      کتابخانه‌ها آماده‌اند."

echo "[۴/۴] ساخت گزارش با داده‌های قبلی…"
.venv/bin/python build_report.py
status=$?

echo
if [ $status -eq 0 ]; then
  echo "پایان موفق. داده‌های قبلی حفظ شدند:"
  echo "  data/8d-forms.json        فرم‌های 8D"
  echo "  data/اصلاح ایرادها.xlsx   اصلاح متن ایرادها"
  echo "  data/اصلاحات گروه‌بندی.xlsx  اصلاح گروه‌بندی"
  echo "  data/backups/             نسخه‌های پشتیبان"
  echo
  echo "برای دیدن داشبورد: bash serve.sh"
else
  echo "ساخت گزارش با خطا تمام شد (کد $status). شرح: output/build.log"
fi
exit $status
