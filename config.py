"""
config.py
تنظیمات مرکزی ربات تریدر.
تمام مقادیر قابل تغییر در همین فایل جمع‌آوری شده‌اند.
"""
import os
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
# Strategy Parameters (ICT + RSI)
# ─────────────────────────────────────────────
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# Swing detection (Fractal pivots)
SWING_LOOKBACK = 3      # تعداد کندل‌های اطراف برای تأیید pivot
SWING_MIN_DISTANCE = 5  # حداقل فاصله بین دو swing هم‌نوع

# FVG detection (3-candle pattern)
FVG_MIN_SIZE_PIPS = 0   # حداقل اندازه گپ (0 = همه گپ‌ها)

# Liquidity Sweep
SWEEP_BUFFER_PTS = 2    # بافر نقاط بالاتر/پایین‌تر از extreme برای sweep

# MSS (Market Structure Shift)
MSS_LOOKBACK = 10       # بررسی break آخرین ساختار در N کندل اخیر

# ─────────────────────────────────────────────
# Risk Management
# ─────────────────────────────────────────────
RISK_PERCENT = 1.0           # ریسک دقیقاً 1٪ از موجودی حساب
MIN_RR_RATIO = 2.0           # حداقل ریوارد-تو-ریسک (زیر 1:2 = رد)
MAX_SPREAD_PTS = 50          # حداکثر اسپرد مجاز (points)
MAX_DAILY_LOSSES = 3         # قانون 3 ضرر
MAX_CONSECUTIVE_LOSSES = 3   # قانون 3 ضرر پشت‌سرهم
RR_DAILY_RESET_UTC_HOUR = 0  # ریست روزانه در نیمه‌شب UTC

# State file (persist برای زنده ماندن loss counter بعد از restart)
STATE_FILE = "state.json"

# ─────────────────────────────────────────────
# News Filter
# ─────────────────────────────────────────────
NEWS_CALENDAR_FILE = "news_calendar.json"   # فایل محلی تقویم اخبار
NEWS_BLACKOUT_MINUTES = 30                  # ±30 دقیقه قبل/بعد خبر High Impact
NEWS_RELEVANT_CURRENCIES = ["USD"]          # فقط اخبار USD برای XAUUSD
NEWS_FETCH_ENABLED = False                  # آیا از API فتچ کنیم؟ (نیازمند FMP_API_KEY)
FMP_API_KEY = os.getenv("FMP_API_KEY", "")  # Financial Modeling Prep (free tier)
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3/economic_calendar"
NEWS_FETCH_DAYS_AHEAD = 3                   # فتچ اخبار N روز آینده

# ─────────────────────────────────────────────
# Execution & Main Loop
# ─────────────────────────────────────────────
MAGIC_NUMBER = 234567            # شناسه‌ی یکتای ربات برای تشخیص سفارش‌های خودش
SLIPPAGE_DEVIATION = 20          # حداکثر انحراف مجاز (points)
MAX_OPEN_POSITIONS = 1           # استراتژی تک‌پوزیشن
BOT_COMMENT = "BotTraderZ"
LOOP_INTERVAL_SECONDS = 15       # فاصله‌ی هر چرخه (دقیقاً طبق درخواست)
LOG_FILE = "bot.log"             # فایل لاگ

# ─────────────────────────────────────────────
# AI Macro Bias (OpenRouter)
# مدل و API از طریق OpenRouter در دسترس هستند.
# API key به‌صورت امن از متغیر محیطی خوانده می‌شود.
# ─────────────────────────────────────────────
from dotenv import load_dotenv

load_dotenv()  # بارگذاری فایل .env در صورت وجود

AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
AI_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
AI_TEMPERATURE = 0.2   # دما پایین → پاسخ‌های قطعی‌تر برای بایاس
AI_MAX_TOKENS = 800
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
