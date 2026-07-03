"""
main.py
حلقه‌ی اصلی ربات تریدر.

ترتیب چک‌ها در هر چرخه (هر 15 ثانیه):
  1. اتصال MT5 فعال است؟
  2. چک سشن (لندن/نیویورک)
  3. چک اخبار مهم (blackout)
  4. چک قانون 3 ضرر
  5. بسته شدن کندل جدید M15؟
  6. دریافت بایاس روزانه از هوش مصنوعی
  7. دریافت سیگنال از استراتژی
  8. چک RR توسط RiskManager
  9. ارسال سفارش به MT5

نکات دیباگ کلیدی:
  - try/except دور کل حلقه → ربات هرگز کرش نمی‌کند
  - آخرین کندل فرمینگ حذف می‌شود (df.iloc[:-1]) → جلوگیری از repaint
  - تشخیص کندل جدید با open_time واقعی MT5 (نه ساعت سیستم)
  - مطمئن می‌شویم قبلاً پوزیشن باز نداریم (تک‌پوزیشن)
  - بررسی deal‌های بسته‌شده برای به‌روزرسانی loss counter
"""
import logging
import logging.handlers
import signal
import sys
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5
import pandas as pd

import config
from mt5_connector import MT5Connector
from session_manager import SessionManager
from ai_bias import AIBiasAnalyzer
from strategy import ICT_RSI_Strategy
from risk_manager import RiskManager
from news_filter import NewsFilter
from execution import TradeExecutor

logger = logging.getLogger("main")


# ─────────────────────────────────────────────
# Logging Setup
# ─────────────────────────────────────────────
def setup_logging():
    """راه‌اندازی لاگ‌گذاری هم در کنسول و هم در فایل."""
    fmt = logging.Formatter(config.LOG_FORMAT)
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.LOG_LEVEL))

    # کنسول
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    # فایل (با rotation روزانه)
    try:
        fh = logging.handlers.TimedRotatingFileHandler(
            config.LOG_FILE, when="midnight", backupCount=7, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception as e:
        logger.warning("Cannot setup file logging: %s", e)


# ─────────────────────────────────────────────
# Main Bot
# ─────────────────────────────────────────────
class TradingBot:
    """هماهنگ‌کننده‌ی تمام لایه‌ها در یک حلقه‌ی واحد."""

    def __init__(self):
        logger.info("=" * 60)
        logger.info("Bot Trader Z — Initializing")
        logger.info("=" * 60)

        # 1. MT5 Connection
        self.connector = MT5Connector()
        if not self.connector.connect():
            raise RuntimeError("Cannot connect to MT5. Aborting.")

        # 2. Symbol info
        self.symbol_info = mt5.symbol_info(config.SYMBOL)
        if self.symbol_info is None:
            raise RuntimeError(f"Cannot get symbol_info for {config.SYMBOL}")

        # 3. Components
        self.session = SessionManager()
        self.ai_bias = AIBiasAnalyzer()
        self.strategy = ICT_RSI_Strategy()
        self.news = NewsFilter()
        self.executor = TradeExecutor(symbol=config.SYMBOL)

        # State
        self._last_bar_time = None     # برای تشخیص کندل جدید
        self._last_deal_id = 0         # برای tracking wins/losses
        self._running = True

        # Persistent RiskManager for loss tracking (avoids new instance each tick)
        acc = mt5.account_info()
        self.risk_mgr = RiskManager(
            balance=acc.balance if acc else 0.0,
            symbol_info=self.symbol_info,
        )

        logger.info("All components initialized. Bot ready.")
        logger.info("=" * 60)

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────
    def stop(self, signum=None, frame=None):
        """توقف تمیز ربات."""
        logger.info("Stop signal received. Shutting down...")
        self._running = False

    def run(self):
        """حلقه‌ی اصلی — هر LOOP_INTERVAL_SECONDS ثانیه یک چرخه."""
        logger.info("Main loop started (interval=%ds)", config.LOOP_INTERVAL_SECONDS)
        while self._running:
            try:
                self._tick()
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt. Stopping.")
                break
            except Exception as e:
                # مهم‌ترین دیباگ: حلقه هرگز نباید کرش کند
                logger.exception("Unhandled exception in loop: %s", e)
                logger.info("Continuing after exception...")
            time.sleep(config.LOOP_INTERVAL_SECONDS)

        self.connector.disconnect()
        logger.info("Bot stopped cleanly.")

    # ─────────────────────────────────────────────
    # Single Tick (one cycle of checks)
    # ─────────────────────────────────────────────
    def _tick(self):
        """اجرای یک چرخه‌ی کامل از چک‌ها."""

        # ── 0. بررسی اتصال ──
        if not self.connector.is_connected:
            logger.warning("MT5 disconnected. Reconnecting...")
            if not self.connector.connect():
                logger.error("Reconnect failed. Skipping tick.")
                return

        # ── 0b. بررسی deal‌های بسته‌شده (برای قانون 3 ضرر) ──
        self._check_closed_deals()

        # ── 1. چک سشن ──
        status = self.session.get_status()
        if not status["can_trade"]:
            logger.debug("Outside trading session (London/NY). "
                         "London=%s NY=%s",
                         status["london_open"], status["new_york_open"])
            return
        logger.debug("✓ Session OK (London=%s NY=%s)",
                      status["london_open"], status["new_york_open"])

        # ── 2. چک اخبار ──
        if self.news.is_blackout():
            nxt = self.news.get_next_high_impact()
            nxt_str = (f"{nxt['event']} @ {nxt['time'].isoformat()}"
                       if nxt else "none scheduled")
            logger.info("⏸ News blackout active. Next: %s", nxt_str)
            return
        logger.debug("✓ News OK (no blackout)")

        # ── 3. چک پوزیشن باز ──
        if self.executor.has_open_position():
            logger.debug("Position already open. Managing (waiting for close).")
            return

        # ── 4. تشخیص کندل جدید M15 ──
        df = self.connector.get_candles(count=config.CANDLE_COUNT)
        if df.empty:
            logger.warning("No candle data. Skipping.")
            return

        # دیباگ: آخرین کندل در حال تشکیل است → حذف برای جلوگیری از repaint
        df_closed = df.iloc[:-1]
        latest_closed_time = df_closed.index[-1]

        if self._last_bar_time == latest_closed_time:
            # هنوز کندل جدیدی بسته نشده
            logger.debug("No new M15 bar (last=%s).", latest_closed_time)
            return

        logger.info("New M15 bar detected: %s", latest_closed_time)
        self._last_bar_time = latest_closed_time

        # ── 5. محاسبه اندیکاتورها + سیگنال ──
        df_ind = self.strategy.calculate_indicators(df_closed)
        if df_ind.empty:
            logger.warning("Indicator calculation returned empty.")
            return

        # ── 6. بایاس روزانه از AI ──
        bias_data = self.ai_bias.get_daily_bias()
        daily_bias = bias_data.get("bias", "NEUTRAL")
        logger.info("Daily bias: %s (confidence=%d%%) — %s",
                    daily_bias, bias_data.get("confidence", 0),
                    bias_data.get("reasoning", "")[:80])

        # ── 7. تولید سیگنال ──
        signal_obj = self.strategy.generate_signal(df_ind, daily_bias)
        if not signal_obj.is_valid:
            logger.info("No valid signal this bar. Reason: %s", signal_obj.reason)
            return
        logger.info("Signal generated: %s | entry=%.5f SL=%.5f TP=%.5f | %s",
                    signal_obj.direction, signal_obj.entry,
                    signal_obj.stop_loss, signal_obj.take_profit,
                    signal_obj.reason)

        # ── 8. Risk Manager ──
        # اسپرد فعلی
        tick = mt5.symbol_info_tick(config.SYMBOL)
        spread_pts = (tick.ask - tick.bid) / self.symbol_info.point if tick else 9999
        # موجودی به‌روز
        acc = mt5.account_info()
        self.risk_mgr.update_balance(acc.balance if acc else 0.0)
        validation = self.risk_mgr.validate_signal(signal_obj, spread_pts)
        if not validation["approved"]:
            logger.info("✗ Signal rejected by RiskManager: %s",
                        validation["reason"])
            return
        logger.info("✓ RiskManager approved | lots=%.2f RR=1:%.2f risk=$%.2f",
                    validation["lot_size"], validation["rr"],
                    validation["risk_amount"])

        # ── 9. اجرای سفارش ──
        ticket = self.executor.place_order(
            direction=signal_obj.direction,
            lot_size=validation["lot_size"],
            stop_loss=signal_obj.stop_loss,
            take_profit=signal_obj.take_profit,
            entry_hint=signal_obj.entry,
        )
        if ticket is not None:
            logger.info("🎉 Trade opened | ticket=%d | %s %.2f lots",
                        ticket, signal_obj.direction, validation["lot_size"])
        else:
            logger.error("✗ Order execution failed.")

    # ─────────────────────────────────────────────
    # Closed Deal Tracking (3-loss rule update)
    # ─────────────────────────────────────────────
    def _check_closed_deals(self):
        """بررسی معاملات بسته‌شده و به‌روزرسانی loss counter."""
        try:
            new_id, profits = self.executor.check_closed_deals(self._last_deal_id)
            if not profits:
                return
            # به‌روزرسانی موجودی
            acc = mt5.account_info()
            if acc:
                self.risk_mgr.update_balance(acc.balance)
            for p in profits:
                if p >= 0:
                    self.risk_mgr.record_win()
                else:
                    self.risk_mgr.record_loss()
            self._last_deal_id = new_id
            logger.info("Updated trade results: %d deals processed.", len(profits))
        except Exception as e:
            logger.warning("Could not check closed deals: %s", e)


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────
def main():
    setup_logging()
    bot = TradingBot()

    # Signal handlers برای توقف تمیز
    signal.signal(signal.SIGINT, bot.stop)
    signal.signal(signal.SIGTERM, bot.stop)

    bot.run()


if __name__ == "__main__":
    main()
