"""
config.py
تنظیمات مرکزی ربات تریدر.
تمام مقادیر قابل تغییر در همین فایل جمع‌آوری شده‌اند.
"""
from datetime import time

# ─────────────────────────────────────────────
# MetaTrader 5 Credentials
# مسیر ترمینال، شماره حساب، رمز و سرور بروکر را اینجا بگذارید.
# ─────────────────────────────────────────────
MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
MT5_LOGIN = 12345678            # ← شماره حساب واقعی
MT5_PASSWORD = "YOUR_PASSWORD"  # ← رمز عبور
MT5_SERVER = "YOUR_BROKER-Server"

# ─────────────────────────────────────────────
# Symbol & Timeframe
# ─────────────────────────────────────────────
SYMBOL = "XAUUSD"
CANDLE_COUNT = 200   # تعداد کندل‌های M15 مورد نیاز برای تحلیل ICT

# ─────────────────────────────────────────────
# Session Windows (ساعت محلیِ هر بورس)
# زمان بر اساس ساعت محلی لندن / نیویورک است،
# بنابراین به‌طور خودکار با DST تنظیم می‌شود.
# ─────────────────────────────────────────────
LONDON_SESSION_START = time(8, 0)    # 08:00 London
LONDON_SESSION_END   = time(17, 0)   # 17:00 London
NEW_YORK_SESSION_START = time(8, 0)  # 08:00 New York
NEW_YORK_SESSION_END   = time(17, 0) # 17:00 New York

# ─────────────────────────────────────────────
# Timezones (استفاده از ZoneInfo → پشتیبانی خودکار DST)
# ─────────────────────────────────────────────
LONDON_TZ   = "Europe/London"
NEW_YORK_TZ = "America/New_York"
UTC_TZ      = "UTC"

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
