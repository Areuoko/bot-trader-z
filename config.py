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
# AI Macro Bias (OpenRouter)
# مدل و API از طریق OpenRouter در دسترس هستند.
# API key به‌صورت امن از متغیر محیطی خوانده می‌شود.
# ─────────────────────────────────────────────
import os
from dotenv import load_dotenv

load_dotenv()  # بارگذاری فایل .env در صورت وجود

AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
AI_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
AI_TEMPERATURE = 0.2   # دما پایین → پاسخ‌های قطعی‌تر برای بایاس
AI_MAX_TOKENS = 400
AI_TIMEOUT = 60        # ثانیه
AI_MAX_RETRIES = 3

# ─────────────────────────────────────────────
# Bias Cache (جلوگیری از مصرف اضافی توکن)
# ─────────────────────────────────────────────
BIAS_CACHE_FILE = "bias_cache.json"

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
