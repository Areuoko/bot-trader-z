"""
session_manager.py
مدیریت زمان و تشخیص سشن‌های معاملاتی لندن و نیویورک (مبتنی بر UTC و DST خودکار).
"""
import logging
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo  # پایتون ≥ 3.9 → پشتیبانی خودکار DST

import config

logger = logging.getLogger(__name__)


class SessionManager:
    """
    تشخیص اینکه آیا زمان فعلی در سشن معاملاتی لندن یا نیویورک قرار دارد یا خیر.

    نکته مهم درباره زمان سشن:
      ساعت هر سشن بر اساس «ساعت محلی بورس» تعریف می‌شود، نه UTC ثابت.
      این کلاس با استفاده از ZoneInfo، زمان فعلی را به تایم‌زون محلی بورس
      تبدیل می‌کند، بنابراین تغییرات DST به‌صورت خودکار مدیریت می‌شود.
    """

    def __init__(self,
                 london_tz: str = config.LONDON_TZ,
                 new_york_tz: str = config.NEW_YORK_TZ):
        self._london_tz = ZoneInfo(london_tz)
        self._new_york_tz = ZoneInfo(new_york_tz)

    # ─────────────────────────────────────────────
    # Core Helper
    # ─────────────────────────────────────────────
    @staticmethod
    def _now_utc() -> datetime:
        """
        زمان فعلی آگاه از تایم‌زون UTC.
        از utcnow() استفاده نشد زیرا آن متد naive برمی‌گرداند و در
        Python 3.12+ منسوخ‌شده است.
        """
        return datetime.now(timezone.utc)

    @staticmethod
    def _is_within_session(now_local: datetime,
                           start: time,
                           end: time) -> bool:
        """
        بررسی می‌کند که آیا 'now_local' در بازه [start, end) قرار دارد یا خیر.

        نکته دیباگ: اگر start < end باشد بازه در همان روز است (مثلاً 08:00→17:00).
        ولی اگر بازه از نیمه‌شب عبور کند باید منطق overnight را هم پشتیبانی کنیم.
        این نسخه فقط بازه‌های درون‌روز را پشتیبانی می‌کند که برای سشن‌های فارکس کافی است.
        """
        current = now_local.time()
        return start <= current < end

    # ─────────────────────────────────────────────
    # Session Checks
    # ─────────────────────────────────────────────
    def is_london_open(self, now: datetime = None) -> bool:
        """آیا سشن لندن باز است؟"""
        if now is None:
            now = self._now_utc()
        now_london = now.astimezone(self._london_tz)
        return self._is_within_session(now_london,
                                       config.LONDON_SESSION_START,
                                       config.LONDON_SESSION_END)

    def is_new_york_open(self, now: datetime = None) -> bool:
        """آیا سشن نیویورک باز است؟"""
        if now is None:
            now = self._now_utc()
        now_ny = now.astimezone(self._new_york_tz)
        return self._is_within_session(now_ny,
                                       config.NEW_YORK_SESSION_START,
                                       config.NEW_YORK_SESSION_END)

    def is_trading_session(self, now: datetime = None) -> bool:
        """آیا در یکی از سشن‌های مجاز (لندن یا نیویورک) هستیم؟"""
        return self.is_london_open(now) or self.is_new_york_open(now)

    # ─────────────────────────────────────────────
    # Diagnostic
    # ─────────────────────────────────────────────
    def get_status(self, now: datetime = None) -> dict:
        """وضعیت کامل سشن‌ها برای لاگ‌گذاری و دیباگ."""
        if now is None:
            now = self._now_utc()
        now_london = now.astimezone(self._london_tz)
        now_ny = now.astimezone(self._new_york_tz)

        return {
            'utc': now,
            'london_local': now_london,
            'new_york_local': now_ny,
            'london_open': self.is_london_open(now),
            'new_york_open': self.is_new_york_open(now),
            'can_trade': self.is_trading_session(now),
        }


# ─────────────────────────────────────────────
# Smoke test — اجرا مستقیم: python session_manager.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format=config.LOG_FORMAT)
    sm = SessionManager()
    status = sm.get_status()
    for k, v in status.items():
        print(f"{k:>16}: {v}")
