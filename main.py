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
from telegram_notifier import TelegramNotifier

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
        logger.info("Bot Trader Z — Initializing (multi-symbol)")
        logger.info("=" * 60)

        # 1. MT5 Connection
        self.connector = MT5Connector()
        if not self.connector.connect():
            raise RuntimeError("Cannot connect to MT5. Aborting.")

        # 2. Symbols & their info (یکی به‌ازای هر نماد)
        self.symbols = config.SYMBOLS
        self.symbol_infos = {}
        for sym in self.symbols:
            info = mt5.symbol_info(sym)
            if info is None:
                raise RuntimeError(f"Cannot get symbol_info for {sym}")
            if not info.visible:
                if not mt5.symbol_select(sym, True):
                    raise RuntimeError(f"symbol_select failed for {sym}")
                info = mt5.symbol_info(sym)  # دوباره بخوان بعد از select
            self.symbol_infos[sym] = info

        # 3. Shared components (بین همه‌ی نمادها مشترک)
        self.session = SessionManager()
        self.telegram = TelegramNotifier()
        self.news = NewsFilter()

        # 4. Per-symbol components
        self.ai_biases = {sym: AIBiasAnalyzer(symbol=sym, telegram=self.telegram)
                          for sym in self.symbols}
        self.strategies = {
            sym: ICT_RSI_Strategy(
                sweep_buffer_pts=config.SWEEP_BUFFER_BY_SYMBOL.get(sym, config.SWEEP_BUFFER_PTS)
            )
            for sym in self.symbols
        }
        self.executors = {sym: TradeExecutor(symbol=sym, telegram=self.telegram)
                          for sym in self.symbols}

        # State (per-symbol جایی که لازم است)
        self._last_bar_time = {sym: None for sym in self.symbols}  # تشخیص کندل جدید هر نماد
        self._last_deal_id = 0         # برای tracking wins/losses (سراسری کافی است، magic مشترک است)
        self._running = True

        # Persistent RiskManager — سراسری و مشترک بین همه‌ی نمادها
        # (شمارنده‌ی 3-ضرر باید بین همه‌ی نمادها یکی باشد، پس فقط یک نمونه ساخته می‌شود)
        acc = mt5.account_info()
        self.risk_mgr = RiskManager(balance=acc.balance if acc else 0.0)

        logger.info("All components initialized for symbols: %s. Bot ready.", self.symbols)
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
        """اجرای یک چرخه‌ی کامل از چک‌ها؛ چک‌های سراسری یک‌بار، سپس لوپ روی هر نماد."""

        # ── 0. بررسی اتصال ──
        if not self.connector.is_connected:
            logger.warning("MT5 disconnected. Reconnecting...")
            if not self.connector.connect():
                logger.error("Reconnect failed. Skipping tick.")
                return

        # ── 0b. بررسی deal‌های بسته‌شده (برای قانون 3 ضرر سراسری) ──
        self._check_closed_deals()

        # ── 1. چک سشن (سراسری - مستقل از نماد) ──
        status = self.session.get_status()
        if not status["can_trade"]:
            logger.debug("Outside trading session (London/NY). "
                         "London=%s NY=%s",
                         status["london_open"], status["new_york_open"])
            return
        logger.debug("✓ Session OK (London=%s NY=%s)",
                      status["london_open"], status["new_york_open"])

        # ── 2. چک اخبار (سراسری - USD روی هر سه نماد اثر دارد) ──
        if self.news.is_blackout():
            nxt = self.news.get_next_high_impact()
            nxt_str = (f"{nxt['event']} @ {nxt['time'].isoformat()}"
                       if nxt else "none scheduled")
            logger.info("⏸ News blackout active. Next: %s", nxt_str)
            return
        logger.debug("✓ News OK (no blackout)")

        # ── 3. تعداد کل پوزیشن‌های باز ربات (روی هر executor یکسان است، magic مشترک) ──
        open_total = self.executors[self.symbols[0]].count_open_positions_all_symbols()
        if open_total >= config.MAX_OPEN_POSITIONS_TOTAL:
            logger.debug("Max total open positions reached (%d/%d). Skipping all symbols.",
                         open_total, config.MAX_OPEN_POSITIONS_TOTAL)
            return

        # ── 4. لوپ روی هر نماد ──
        for sym in self.symbols:
            opened = self._tick_symbol(sym, open_total)
            if opened:
                open_total += 1  # جلوگیری از عبور از سقف کل در همین چرخه

    def _tick_symbol(self, sym: str, open_total: int) -> bool:
        """
        اجرای چک‌های مخصوص یک نماد (کندل جدید → اندیکاتور → بایاس → سیگنال → ریسک → اجرا).

        Args:
            sym: نماد مورد بررسی
            open_total: تعداد کل پوزیشن‌های باز ربات (روی همه‌ی نمادها) قبل از این نماد

        Returns:
            True اگر معامله‌ی جدیدی روی این نماد باز شد.
        """
        executor = self.executors[sym]
        symbol_info = self.symbol_infos[sym]

        # ── چک پوزیشن باز مخصوص همین نماد ──
        if executor.has_open_position(sym):
            logger.debug("[%s] Position already open. Skipping.", sym)
            return False

        # ── تشخیص کندل جدید M15 ──
        df = self.connector.get_candles(symbol=sym, count=config.CANDLE_COUNT)
        if df.empty:
            logger.warning("[%s] No candle data. Skipping.", sym)
            return False

        # دیباگ: آخرین کندل در حال تشکیل است → حذف برای جلوگیری از repaint
        df_closed = df.iloc[:-1]
        latest_closed_time = df_closed.index[-1]

        if self._last_bar_time[sym] == latest_closed_time:
            # هنوز کندل جدیدی روی این نماد بسته نشده
            logger.debug("[%s] No new M15 bar (last=%s).", sym, latest_closed_time)
            return False

        logger.info("[%s] New M15 bar detected: %s", sym, latest_closed_time)
        self._last_bar_time[sym] = latest_closed_time

        # ── محاسبه اندیکاتورها + سیگنال ──
        strategy = self.strategies[sym]
        df_ind = strategy.calculate_indicators(df_closed)
        if df_ind.empty:
            logger.warning("[%s] Indicator calculation returned empty.", sym)
            return False

        # ── بایاس روزانه از AI (مخصوص همین نماد، کش جداگانه) ──
        bias_data = self.ai_biases[sym].get_daily_bias()
        daily_bias = bias_data.get("bias", "NEUTRAL")
        logger.info("[%s] Daily bias: %s (confidence=%d%%) — %s",
                    sym, daily_bias, bias_data.get("confidence", 0),
                    bias_data.get("reasoning", "")[:80])

        # ── تولید سیگنال ──
        signal_obj = strategy.generate_signal(df_ind, daily_bias)
        if not signal_obj.is_valid:
            logger.info("[%s] No valid signal this bar. Reason: %s", sym, signal_obj.reason)
            return False
        logger.info("[%s] Signal generated: %s | entry=%.5f SL=%.5f TP=%.5f | %s",
                    sym, signal_obj.direction, signal_obj.entry,
                    signal_obj.stop_loss, signal_obj.take_profit,
                    signal_obj.reason)

        # ── Risk Manager ──
        tick = mt5.symbol_info_tick(sym)
        spread_pts = (tick.ask - tick.bid) / symbol_info.point if tick else 9999
        acc = mt5.account_info()
        self.risk_mgr.update_balance(acc.balance if acc else 0.0)

        validation = self.risk_mgr.validate_signal(
            signal_obj, spread_pts, symbol_info,
            open_positions_total=open_total,
            has_position_this_symbol=False,  # از قبل بالاتر چک شد
        )
        if not validation["approved"]:
            logger.info("[%s] ✗ Signal rejected by RiskManager: %s", sym, validation["reason"])
            return False
        logger.info("[%s] ✓ RiskManager approved | lots=%.2f RR=1:%.2f risk=$%.2f",
                    sym, validation["lot_size"], validation["rr"], validation["risk_amount"])

        # ── اجرای سفارش ──
        ticket = executor.place_order(
            direction=signal_obj.direction,
            lot_size=validation["lot_size"],
            stop_loss=signal_obj.stop_loss,
            take_profit=signal_obj.take_profit,
            entry_hint=signal_obj.entry,
        )
        if ticket is not None:
            logger.info("[%s] 🎉 Trade opened | ticket=%d | %s %.2f lots",
                        sym, ticket, signal_obj.direction, validation["lot_size"])
            return True
        else:
            logger.error("[%s] ✗ Order execution failed.", sym)
            return False

    # ─────────────────────────────────────────────
    # Closed Deal Tracking (3-loss rule update + Telegram notification)
    # ─────────────────────────────────────────────
    def _check_closed_deals(self):
        """
        بررسی معاملات بسته‌شده و به‌روزرسانی loss counter + ارسال اعلان تلگرام.

        دیباگ مهم: check_closed_deals در execution.py بر اساس magic فیلتر می‌کند
        نه symbol، پس دیل‌های همه‌ی نمادها را برمی‌گرداند. چون magic بین همه‌ی
        executorها مشترک است، کافی است فقط یک‌بار (روی یک executor دلخواه) صدا
        زده شود؛ صدا زدن آن برای هر نماد باعث دابل/تریپل‌کانت شدن می‌شود.
        """
        try:
            any_executor = self.executors[self.symbols[0]]
            new_id, closed_deals = any_executor.check_closed_deals(self._last_deal_id)
            if not closed_deals:
                return
            # به‌روزرسانی موجودی
            acc = mt5.account_info()
            if acc:
                self.risk_mgr.update_balance(acc.balance)
            for deal in closed_deals:
                profit = deal["profit"]
                if profit >= 0:
                    self.risk_mgr.record_win()
                else:
                    self.risk_mgr.record_loss()

                # محاسبه پیپ (برای XAUUSD: 1 پیپ = 0.1)
                symbol_info = mt5.symbol_info(deal["symbol"])
                if symbol_info:
                    point = symbol_info.point
                    # محاسبه سود/ضرر به پیپ بر اساس حجم و point
                    pnl_pips = profit / (deal["volume"] * point * 10) if point > 0 else 0
                else:
                    pnl_pips = 0

                # تشخیص دلیل بسته شدن
                reason = "手动"
                if deal["comment"]:
                    comment_lower = deal["comment"].lower()
                    if "sl" in comment_lower or "stop" in comment_lower:
                        reason = "SL"
                    elif "tp" in comment_lower or "take" in comment_lower:
                        reason = "TP"

                # ارسال اعلان تلگرام
                try:
                    self.telegram.send_trade_closed(
                        symbol=deal["symbol"],
                        direction=deal["direction"],
                        pnl_usd=profit,
                        pnl_pips=pnl_pips,
                        reason=reason,
                    )
                except Exception as e:
                    logger.warning("Failed to send Telegram trade closed notification: %s", e)

            self._last_deal_id = new_id
            logger.info("Updated trade results: %d deals processed.", len(closed_deals))
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
