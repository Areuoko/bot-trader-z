"""
telegram_notifier.py
لایه اعلان‌های تلگرام برای ربات تریدر.

امکانات:
  1. ارسال پیام متنی ساده
  2. ارسال اعلان باز شدن معامله (با فرمت زیبا و ایموجی)
  3. ارسال اعلان بسته شدن معامله (با نتیجه مالی)
  4. ارسال تحلیل بایاس روزانه هوش مصنوعی

نکات دیباگ کلیدی:
  - خواندن توکن و Chat ID از فایل .env (امنیت)
  - استفاده از try/except برای جلوگیری از کرش در قطعی اینترنت
  - لاگ کامل خطاها برای دیباگ
"""
import logging
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """ارسال اعلان‌های تلگرام برای ربات تریدر."""

    def __init__(self,
                 token: str = config.TELEGRAM_BOT_TOKEN,
                 chat_id: str = config.TELEGRAM_CHAT_ID):
        self.token = token
        self.chat_id = chat_id
        self._enabled = bool(token and chat_id)
        if self._enabled:
            logger.info("TelegramNotifier enabled | chat_id=%s", chat_id)
        else:
            logger.warning("TelegramNotifier DISABLED (missing token or chat_id).")

    def _send(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        ارسال پیام به تلگرام.

        Args:
            text: متن پیام (پشتیبانی از HTML markdown)
            parse_mode: حالت پارس (HTML یا Markdown)

        Returns:
            True در صورت موفقیت، False در صورت شکست.
        """
        if not self._enabled:
            logger.debug("Telegram disabled, skipping send.")
            return False

        url = TELEGRAM_API_URL.format(token=self.token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    logger.info("Telegram message sent successfully.")
                    return True
                else:
                    logger.error("Telegram API error: %s", data.get("description", "Unknown"))
                    return False
            else:
                logger.error("Telegram HTTP error %d: %s", resp.status_code, resp.text[:200])
                return False
        except requests.exceptions.Timeout:
            logger.error("Telegram request timed out.")
            return False
        except requests.exceptions.ConnectionError:
            logger.error("Telegram connection error (internet disconnected?).")
            return False
        except requests.exceptions.RequestException as e:
            logger.error("Telegram request failed: %s", e)
            return False
        except Exception as e:
            logger.error("Unexpected error sending Telegram message: %s", e)
            return False

    def send_message(self, text: str) -> bool:
        """
        ارسال یک پیام متنی ساده به تلگرام.

        Args:
            text: متن پیام

        Returns:
            True در صورت موفقیت
        """
        return self._send(text)

    def send_trade_opened(self, symbol: str, direction: str, entry: float,
                          sl: float, tp: float, lot_size: float) -> bool:
        """
        ارسال اعلان باز شدن معامله با فرمت زیبا.

        Args:
            symbol: نماد معاملاتی (مثلاً XAUUSD)
            direction: نوع معامله (BUY یا SELL)
            entry: نقطه ورود
            sl: حد ضرر (Stop Loss)
            tp: حد سود (Take Profit)
            lot_size: حجم معامله
        """
        emoji = "🟢" if direction == "BUY" else "🔴"
        direction_fa = "خرید" if direction == "BUY" else "فروش"

        text = (
            f"{emoji} <b>معامله جدید باز شد</b> {emoji}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>نماد:</b> <code>{symbol}</code>\n"
            f"📈 <b>نوع:</b> {direction} ({direction_fa})\n"
            f"💰 <b>حجم:</b> <code>{lot_size:.2f}</code> لات\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>ورود:</b> <code>{entry:.5f}</code>\n"
            f"🛑 <b>حد ضرر:</b> <code>{sl:.5f}</code>\n"
            f"✅ <b>حد سود:</b> <code>{tp:.5f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━"
        )
        return self._send(text)

    def send_trade_closed(self, symbol: str, direction: str, pnl_usd: float,
                          pnl_pips: float, reason: str) -> bool:
        """
        ارسال اعلان بسته شدن معامله با نتیجه مالی.

        Args:
            symbol: نماد معاملاتی
            direction: نوع معامله (BUY یا SELL)
            pnl_usd: سود/ضرر به دلار
            pnl_pips: سود/ضرر به پیپ
            reason: دلیل بسته شدن (SL/TP/手动)
        """
        if pnl_usd >= 0:
            emoji = "💰"
            status = "سود"
            color = "🟢"
        else:
            emoji = "💸"
            status = "ضرر"
            color = "🔴"

        reason_fa = {
            "SL": "حد ضرر",
            "TP": "حد سود",
            "手动": "بستن دستی",
            "manual": "بستن دستی",
        }.get(reason, reason)

        text = (
            f"{color} <b>معامله بسته شد</b> {color}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>نماد:</b> <code>{symbol}</code>\n"
            f"📈 <b>نوع:</b> {direction}\n"
            f"🔒 <b>دلیل:</b> {reason_fa}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} <b>نتیجه:</b> {status}\n"
            f"💵 <b>مبلغ:</b> <code>{pnl_usd:+.2f}</code> $\n"
            f"📏 <b>پیپ:</b> <code>{pnl_pips:+.1f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━"
        )
        return self._send(text)

    def send_daily_ai_bias(self, bias_text: str) -> bool:
        """
        ارسال تحلیل بایاس روزانه هوش مصنوعی.

        Args:
            bias_text: متن تحلیل AI (شامل bias، confidence و reasoning)
        """
        text = (
            f"🤖 <b>تحلیل بایاس روزانه هوش مصنوعی</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{bias_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━"
        )
        return self._send(text)


# ─────────────────────────────────────────────
# Smoke test — python telegram_notifier.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    notifier = TelegramNotifier()
    print("\n=== Testing Telegram Notifier ===")
    notifier.send_message("🧪 Test message from Bot Trader Z")
