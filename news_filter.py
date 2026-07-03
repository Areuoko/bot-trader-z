"""
news_filter.py
فیلتر اخبار اقتصادی High Impact.

معماری:
  - منبع اصلی: فایل محلی news_calendar.json (پایدار، بدون rate limit)
  - منبع اختیاری: fetcher از Financial Modeling Prep (free tier)
  - تشخیص blackout: آیا الان در ±30 دقیقه از خبر High Impact هستیم؟

نکات دیباگ کلیدی:
  - همه‌ی زمان‌ها به‌صورت aware datetime در UTC ذخیره و مقایسه می‌شوند
  - parser مقاوم در برابر: فایل مفقود، JSON خراب، فیلد مفقود، فرمت زمان نادرست
  - cache در حافظه با timestamp برای کاهش I/O فایل
  - نرمال‌سازی impact با lower().strip()
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)


class NewsFilter:
    """
    فیلتر اخبار اقتصادی.

    نمونه‌سازی:
        nf = NewsFilter()
        if nf.is_blackout():
            logger.info("News blackout active - skipping trade")
        else:
            ... # proceed with trade
    """

    def __init__(self,
                 calendar_file: str = config.NEWS_CALENDAR_FILE,
                 relevant_currencies: list = None,
                 blackout_minutes: int = config.NEWS_BLACKOUT_MINUTES,
                 fetch_enabled: bool = config.NEWS_FETCH_ENABLED):
        self.calendar_file = calendar_file
        self.relevant_currencies = [c.upper().strip()
                                    for c in (relevant_currencies or config.NEWS_RELEVANT_CURRENCIES)]
        self.blackout_minutes = blackout_minutes
        self.fetch_enabled = fetch_enabled

        # cache در حافظه
        self._events: list = []
        self._cache_loaded_at: Optional[datetime] = None
        self._load_calendar()

    # ─────────────────────────────────────────────
    # Calendar Loading (with robust parsing)
    # ─────────────────────────────────────────────
    def _load_calendar(self) -> None:
        """
        بارگذاری تقویم اخبار از فایل محلی با error handling کامل.

        دیباگ‌های اعمال‌شده:
          - فایل مفقود → لیست خالی + warning (ربات کرش نمی‌کند)
          - JSON خراب → لیست خالی + warning
          - ساختار غیرمنتظره → استخراج بخش 'events' با fallback
          - هر event فیلد مفقود داشته → skip می‌شود نه crash
          - زمان غیرقابل parse → skip + warning
        """
        try:
            with open(self.calendar_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            logger.warning("News calendar file '%s' not found. "
                           "No news filter active.", self.calendar_file)
            self._events = []
            self._cache_loaded_at = datetime.now(timezone.utc)
            return
        except json.JSONDecodeError as e:
            logger.error("News calendar JSON is corrupt: %s. "
                         "No news filter active.", e)
            self._events = []
            self._cache_loaded_at = datetime.now(timezone.utc)
            return
        except OSError as e:
            logger.error("Cannot read news calendar: %s", e)
            self._events = []
            self._cache_loaded_at = datetime.now(timezone.utc)
            return

        # استخراج لیست events (با fallback)
        events = raw.get("events", raw) if isinstance(raw, dict) else raw
        if not isinstance(events, list):
            logger.error("News calendar format unexpected. Expected list, got %s.",
                         type(events).__name__)
            self._events = []
            self._cache_loaded_at = datetime.now(timezone.utc)
            return

        # فیلتر و نرمالایز هر event
        cleaned = []
        for i, ev in enumerate(events):
            try:
                parsed = self._parse_event(ev)
                if parsed is not None:
                    cleaned.append(parsed)
            except (KeyError, ValueError, TypeError) as e:
                logger.warning("Skipping malformed event #%d: %s", i, e)

        self._events = cleaned
        self._cache_loaded_at = datetime.now(timezone.utc)
        logger.info("News calendar loaded: %d valid events (relevant currencies: %s).",
                    len(cleaned), self.relevant_currencies)

    def _parse_event(self, ev: dict) -> Optional[dict]:
        """
        parse و نرمال‌سازی یک event.

        دیباگ:
          - 'time' باید ISO 8601 باشد. اگر timezone نداشت، UTC فرض می‌کنیم.
          - 'impact' نرمالایز با lower/strip
          - اگر 'currency' در relevant نباشد، skip می‌کنیم
        """
        # زمان
        raw_time = ev.get("time")
        if not raw_time:
            raise ValueError("missing 'time' field")
        dt = self._parse_datetime(str(raw_time))
        if dt is None:
            raise ValueError(f"unparseable time: {raw_time}")

        # ارز
        currency = str(ev.get("currency", "")).upper().strip()
        if currency not in self.relevant_currencies:
            return None  # نه خطا، فقط نامرتبط

        # impact
        impact = str(ev.get("impact", "")).lower().strip()
        if impact not in ("high", "medium", "low"):
            logger.debug("Event '%s' has unknown impact '%s', treating as low.",
                         ev.get("event", "?"), impact)
            impact = "low"

        return {
            "time": dt,
            "currency": currency,
            "impact": impact,
            "event": str(ev.get("event", "Unknown"))[:100],
            "forecast": str(ev.get("forecast", "")),
            "previous": str(ev.get("previous", "")),
        }

    @staticmethod
    def _parse_datetime(s: str) -> Optional[datetime]:
        """
        parse یک ISO 8601 datetime. مقاوم در برابر:
          - با timezone: 2026-07-03T12:30:00+00:00
          - بدون timezone: 2026-07-03T12:30:00  (UTC فرض می‌کنیم)
          - با Z: 2026-07-03T12:30:00Z
          - فقط تاریخ: 2026-07-03
        """
        s = s.strip()
        # Try 1: ISO format کامل
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
        # Try 2: فقط تاریخ
        try:
            dt = datetime.fromisoformat(s[:10])
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        return None

    # ─────────────────────────────────────────────
    # Optional: Fetch from API
    # ─────────────────────────────────────────────
    def fetch_updates(self) -> bool:
        """
        فتچ اخبار از Financial Modeling Prep و ذخیره در فایل محلی.
        اختیاری - فقط اگر NEWS_FETCH_ENABLED=True و API key موجود باشد.
        """
        if not self.fetch_enabled:
            logger.debug("News fetch disabled.")
            return False
        if not config.FMP_API_KEY:
            logger.warning("FMP_API_KEY not set. Cannot fetch news.")
            return False

        from_dt = datetime.now(timezone.utc)
        to_dt = from_dt + timedelta(days=config.NEWS_FETCH_DAYS_AHEAD)

        params = {
            "from": from_dt.strftime("%Y-%m-%d"),
            "to": to_dt.strftime("%Y-%m-%d"),
            "apikey": config.FMP_API_KEY,
        }
        try:
            logger.info("Fetching economic calendar from FMP...")
            resp = requests.get(config.FMP_BASE_URL, params=params,
                                timeout=30)
            if resp.status_code != 200:
                logger.error("FMP fetch failed: HTTP %d", resp.status_code)
                return False
            data = resp.json()
            if not isinstance(data, list):
                logger.error("FMP returned non-list: %s", type(data).__name__)
                return False
            self._save_fetched(data)
            self._load_calendar()  # reload cache
            logger.info("Fetched %d events from FMP.", len(data))
            return True
        except requests.exceptions.RequestException as e:
            logger.error("Network error fetching news: %s", e)
            return False
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("Error parsing FMP response: %s", e)
            return False

    def _save_fetched(self, data: list) -> None:
        """ذخیره داده‌های فتچ‌شده در فایل محلی."""
        payload = {
            "_meta": {
                "source": "Financial Modeling Prep",
                "last_updated": datetime.now(timezone.utc).isoformat(),
            },
            "events": data,
        }
        try:
            with open(self.calendar_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.info("Saved fetched news to %s.", self.calendar_file)
        except OSError as e:
            logger.warning("Cannot save fetched news: %s", e)

    # ─────────────────────────────────────────────
    # Core: Blackout Detection
    # ─────────────────────────────────────────────
    def _now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def is_blackout(self, now: datetime = None) -> bool:
        """
        آیا الان در بازه‌ی blackout خبر High Impact هستیم؟
        بازه: [event_time - 30min, event_time + 30min]

        Returns:
            True اگر در blackout هستیم (نباید معامله کنیم)
        """
        if now is None:
            now = datetime.now(timezone.utc)
        # assure aware
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        window = timedelta(minutes=self.blackout_minutes)
        for ev in self._events:
            if ev["impact"] != "high":
                continue
            start = ev["time"] - window
            end = ev["time"] + window
            if start <= now <= end:
                logger.info("NEWS BLACKOUT: %s at %s | now=%s | window=[%s, %s]",
                            ev["event"], ev["time"].isoformat(), now.isoformat(),
                            start.strftime("%H:%M"), end.strftime("%H:%M"))
                return True
        return False

    def get_next_high_impact(self, now: datetime = None) -> Optional[dict]:
        """بازگرداندن نزدیک‌ترین خبر High Impact آینده."""
        if now is None:
            now = datetime.now(timezone.utc)
        upcoming = [e for e in self._events
                    if e["impact"] == "high" and e["time"] > now]
        if not upcoming:
            return None
        return min(upcoming, key=lambda e: e["time"])

    def get_status(self, now: datetime = None) -> dict:
        """وضعیت کامل برای لاگ‌گذاری و دیباگ."""
        if now is None:
            now = datetime.now(timezone.utc)
        next_ev = self.get_next_high_impact(now)
        return {
            "total_events": len(self._events),
            "high_impact_count": sum(1 for e in self._events if e["impact"] == "high"),
            "is_blackout": self.is_blackout(now),
            "next_high_impact": (next_ev["event"] if next_ev else None),
            "next_high_impact_time": (next_ev["time"].isoformat() if next_ev else None),
            "minutes_to_next": (
                int((next_ev["time"] - now).total_seconds() / 60)
                if next_ev else None
            ),
        }


# ─────────────────────────────────────────────
# Smoke test — python news_filter.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    nf = NewsFilter()
    print("\n=== Status ===")
    status = nf.get_status()
    for k, v in status.items():
        print(f"  {k}: {v}")

    # Test blackout window
    print("\n=== Blackout Window Test ===")
    nfp_time = datetime(2026, 7, 3, 12, 30, tzinfo=timezone.utc)  # NFP
    print(f"NFP at {nfp_time.isoformat()}")
    print(f"  t-45min ({nfp_time - timedelta(minutes=45)}): blackout={nf.is_blackout(nfp_time - timedelta(minutes=45))}")  # False
    print(f"  t-20min ({nfp_time - timedelta(minutes=20)}): blackout={nf.is_blackout(nfp_time - timedelta(minutes=20))}")  # True
    print(f"  at event ({nfp_time}): blackout={nf.is_blackout(nfp_time)}")  # True
    print(f"  t+20min ({nfp_time + timedelta(minutes=20)}): blackout={nf.is_blackout(nfp_time + timedelta(minutes=20))}")  # True
    print(f"  t+45min ({nfp_time + timedelta(minutes=45)}): blackout={nf.is_blackout(nfp_time + timedelta(minutes=45))}")  # False
