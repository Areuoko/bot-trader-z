"""
config.py
تنظیمات مرکزی ربات تریدر.
تمام مقادیر قابل تغییر در همین فایل جمع‌آوری شده‌اند.
"""
import os
from datetime import time

from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# MetaTrader 5 Credentials
# مقادیر از فایل .env خوانده می‌شوند.
# ─────────────────────────────────────────────
MT5_PATH = os.getenv("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")

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
# AI Macro Bias — Multi-Provider Support
# پشتیبانی از چندین provider: Gemini (primary) + OpenRouter (fallback).
# API key‌ها به‌صورت امن از فایل .env خوانده می‌شوند.
# ─────────────────────────────────────────────

# Provider انتخابی (gemini | openrouter)
AI_PRIMARY_PROVIDER = os.getenv("AI_PRIMARY_PROVIDER", "gemini").lower()
AI_FALLBACK_PROVIDER = os.getenv("AI_FALLBACK_PROVIDER", "openrouter").lower()

# Gemini / Google AI Studio (OpenAI-compatible endpoint)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
# اگر key شما یک proxy شخصی است، BASE_URL را در .env تغییر دهید.
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
)

# OpenRouter (fallback)
# OPENROUTER_API_KEY اگر خالی باشد، از AI_API_KEY قدیمی استفاده می‌شود.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY",
                               os.getenv("AI_API_KEY", ""))
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL",
                              "nvidia/nemotron-3-ultra-550b-a55b:free")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# تنظیمات مشترک AI
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.2"))
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "800"))
AI_TIMEOUT = 60        # ثانیه
AI_MAX_RETRIES = 3     # تعداد retry برای هر provider

# ─────────────────────────────────────────────
# Bias Cache (جلوگیری از مصرف اضافی توکن)
# ─────────────────────────────────────────────
BIAS_CACHE_FILE = "bias_cache.json"

# ─────────────────────────────────────────────
# Telegram Notifications
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
