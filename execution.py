"""
execution.py
اجرای معامله و مدیریت پوزیشن‌ها روی MetaTrader 5.

نکات دیباگ کلیدی:
  - SL/TP نرمالایز به digits سمبل (جلوگیری از retcode 10016)
  - لات نرمالایز به volume_step (جلوگیری از retcode 10014)
  - تشخیص خودکار filling mode (جلوگیری از retcode 10030)
  - اعتبارسنجی فاصله SL/TP از stops_level بروکر
  - اجرای تک‌پوزیشن (جلوگیری از ریسک مضاعف)
  - بررسی دقیق retcode بعد از order_send
  - لاگ‌گذاری کامل تمام مراحل
"""
import logging
import math
from typing import Optional

import MetaTrader5 as mt5

import config

logger = logging.getLogger(__name__)


class TradeExecutor:
    """اجرای سفارش‌ها و مدیریت پوزیشن‌های باز روی MT5."""

    def __init__(self, symbol: str = config.SYMBOL, magic: int = config.MAGIC_NUMBER):
        self.symbol = symbol
        self.magic = magic
        self._info = mt5.symbol_info(symbol)
        if self._info is None:
            logger.error("symbol_info(%s) returned None!", symbol)
        else:
            logger.info("TradeExecutor ready | symbol=%s | digits=%d | "
                        "stops_level=%d pts",
                        symbol, self._info.digits, self._info.trade_stops_level)

    # ─────────────────────────────────────────────
    # Helpers: Normalization
    # ─────────────────────────────────────────────
    def _norm_price(self, price: float) -> float:
        """نرمال‌سازی قیمت به digits سمبل (جلوگیری از retcode 10016)."""
        return round(float(price), self._info.digits)

    def _norm_volume(self, volume: float) -> float:
        """
        نرمال‌سازی حجم به volume_step.
        دیباگ: از floor استفاده می‌کنیم (همانند RiskManager) تا حجم نتواند از مقدار محاسبه‌شده بیشتر شود.
        """
        step = self._info.volume_step
        if step <= 0:
            step = 0.01
        lots = math.floor(volume / step) * step
        lots = max(self._info.volume_min, min(self._info.volume_max, lots))
        return round(lots, 2)

    def _detect_filling_mode(self) -> int:
        """
        تشخیص خودکار filling mode پشتیبانی‌شده توسط بروکر.
        دیباگ: اگر نوع اشتباه باشد، بروکر retcode 10030 می‌دهد.
        ترتیب اولویت: IOC, FOK, RETURN.
        """
        filling = self._info.trade_filling_mode
        if filling & mt5.SYMBOL_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        if filling & mt5.SYMBOL_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    def _check_stops_level(self, price: float, sl: float, tp: float) -> bool:
        """
        بررسی اینکه آیا SL/TP حداقل فاصله‌ی stops_level را دارند.
        دیباگ: نزدیک‌تر از این فاصله → retcode 10016.
        """
        stops = self._info.trade_stops_level * self._info.point
        if stops <= 0:
            return True  # بروکر محدودیت خاصی ندارد
        ok_sl = abs(price - sl) >= stops
        ok_tp = abs(price - tp) >= stops
        if not (ok_sl and ok_tp):
            logger.warning("SL/TP too close to stops_level (%.5f). "
                           "SL dist=%.5f, TP dist=%.5f",
                           stops, abs(price - sl), abs(price - tp))
        return ok_sl and ok_tp

    # ─────────────────────────────────────────────
    # Position Management
    # ─────────────────────────────────────────────
    def has_open_position(self) -> bool:
        """آیا پوزیشن باز متعلق به این ربات وجود دارد؟ (تک‌پوزیشن)"""
        positions = mt5.positions_get(symbol=self.symbol)
        if positions is None:
            return False
        return any(p.magic == self.magic for p in positions)

    def _get_trade_price(self, direction: str) -> float:
        """
        قیمت اجرا: BUY → ask فعلی، SELL → bid فعلی.
        دیباگ: market order با قیمت فعلی اجرا می‌شود نه قیمت سیگنال.
        """
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            logger.error("symbol_info_tick returned None!")
            return 0.0
        if direction == "BUY":
            return tick.ask
        return tick.bid

    # ─────────────────────────────────────────────
    # Order Execution
    # ─────────────────────────────────────────────
    def place_order(self, direction: str, lot_size: float,
                    stop_loss: float, take_profit: float,
                    entry_hint: float = 0.0) -> Optional[int]:
        """
        ارسال market order با SL و TP مستقیم روی سرور.

        Args:
            direction: "BUY" or "SELL"
            lot_size: حجم (به‌صورت خام، نرمالایز داخلی می‌شود)
            stop_loss/take_profit: قیمت‌های خام
            entry_hint: فقط برای لاگ (قیمت ورودی سیگنال)

        Returns:
            ticket number در صورت موفقیت، None در صورت شکست.
        """
        # 1. اعتبارسنجی اولیه
        if direction not in ("BUY", "SELL"):
            logger.error("Invalid direction: %s", direction)
            return None
        if lot_size <= 0:
            logger.error("Lot size <= 0, aborting.")
            return None

        # 2. تأیید سمبل در MarketWatch
        if not self._info.visible:
            if not mt5.symbol_select(self.symbol, True):
                logger.error("symbol_select failed for %s", self.symbol)
                return None

        # 3. نرمال‌سازی مقادیر
        price = self._get_trade_price(direction)
        if price <= 0:
            return None
        sl = self._norm_price(stop_loss)
        tp = self._norm_price(take_profit)
        volume = self._norm_volume(lot_size)
        price = self._norm_price(price)

        # 4. اعتبارسنجی جهت SL/TP
        if direction == "BUY":
            if not (sl < price < tp):
                logger.error("BUY geometry invalid: SL=%s < price=%s < TP=%s",
                             sl, price, tp)
                return None
        else:
            if not (tp < price < sl):
                logger.error("SELL geometry invalid: TP=%s < price=%s < SL=%s",
                             tp, price, sl)
                return None

        # 5. اعتبارسنجی stops_level
        if not self._check_stops_level(price, sl, tp):
            return None

        # 6. ساخت request
        filling_mode = self._detect_filling_mode()
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": volume,
            "type": (mt5.ORDER_TYPE_BUY if direction == "BUY"
                     else mt5.ORDER_TYPE_SELL),
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": config.SLIPPAGE_DEVIATION,
            "magic": self.magic,
            "comment": config.BOT_COMMENT,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        logger.info("ORDER SEND | %s %.2f lots @ %s | SL=%s TP=%s",
                    direction, volume, price, sl, tp)

        # 7. ارسال
        result = mt5.order_send(request)
        if result is None:
            err = mt5.last_error()
            logger.error("order_send returned None | error=%s", err)
            return None

        # 8. بررسی نتیجه
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error("ORDER REJECTED | retcode=%d | comment=%s | %s",
                         result.retcode, result.comment,
                         self._decode_retcode(result.retcode))
            return None

        logger.info("ORDER FILLED ✓ | ticket=%d | price=%s | volume=%.2f",
                    result.order, result.price, result.volume)
        return result.order

    @staticmethod
    def _decode_retcode(code: int) -> str:
        """تبدیل retcode عددی به توضیح متنی برای دیباگ."""
        codes = {
            10004: "REQUOTE",
            10006: "REQUEST_REJECTED",
            10013: "INVALID_REQUEST",
            10014: "INVALID_VOLUME",
            10015: "INVALID_PRICE",
            10016: "INVALID_STOPS",
            10018: "MARKET_CLOSED",
            10027: "AUTOTRADING_DISABLED",
            10030: "INVALID_FILL",
        }
        return codes.get(code, f"UNKNOWN({code})")

    # ─────────────────────────────────────────────
    # Result Tracking (for 3-loss rule)
    # ─────────────────────────────────────────────
    def check_closed_deals(self, last_checked_deal_id: int) -> tuple:
        """
        بررسی deal‌های بسته‌شده پس از last_checked_deal_id.

        Returns:
            (new_last_id, list of profits)
            - profit > 0 → win
            - profit < 0 → loss
        """
        from datetime import datetime, timedelta, timezone
        from_date = datetime.now(timezone.utc) - timedelta(days=7)
        deals = mt5.history_deals_get(from_date, datetime.now(timezone.utc))
        if deals is None:
            return last_checked_deal_id, []

        new_profits = []
        max_id = last_checked_deal_id
        for d in deals:
            if d.entry == mt5.DEAL_ENTRY_OUT and d.magic == self.magic:
                if d.ticket > last_checked_deal_id:
                    new_profits.append(float(d.profit))
                    max_id = max(max_id, d.ticket)
        return max_id, new_profits
