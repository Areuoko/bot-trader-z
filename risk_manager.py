"""
risk_manager.py
مدیریت ریسک، محاسبه حجم معامله، فیلتر RR و اسپرد، و قانون 3 ضرر.

منطق کلیدی:
  1. محاسبه حجم بر اساس 1% ریسک با استفاده از tick_value واقعی بروکر
  2. بررسی RR ≥ 1:2 قبل از اجازه ورود
  3. فیلتر اسپرد (حداکثر MAX_SPREAD_PTS)
  4. شمارش ضرر روزانه + ریست با تاریخ UTC
  5. persist کردن state در فایل برای زنده ماندن پس از restart
"""
import json
import logging
import math
from datetime import datetime, timezone
from typing import Optional

import config

logger = logging.getLogger(__name__)


class RiskManager:
    """
    مدیریت ریسک مرکزی و مشترک بین همه‌ی نمادها.

    دیباگ مهم: این کلاس دیگر به یک symbol_info ثابت بسته نمی‌شود، چون در
    حالت چندنمادی (XAUUSD/XAGUSD/EURUSD) هر نماد digits/tick_value/volume_step
    متفاوتی دارد. به‌جایش symbol_info به‌عنوان پارامتر متد calculate_lot_size
    داده می‌شود، ولی شمارنده‌ی 3-ضرر (state.json) سراسری و مشترک بین همه‌ی
    نمادها باقی می‌ماند — پس باید فقط یک نمونه از RiskManager در کل ربات ساخته
    شود و بین همه‌ی نمادها به اشتراک گذاشته شود (نه یک نمونه به‌ازای هر نماد).

    نمونه‌سازی:
        rm = RiskManager(balance=acc.balance)
        validation = rm.validate_signal(signal, spread, symbol_info,
                                         open_positions_total, has_position_this_symbol)
    """

    def __init__(self,
                 balance: float,
                 risk_percent: float = config.RISK_PERCENT,
                 min_rr: float = config.MIN_RR_RATIO,
                 max_spread_pts: float = config.MAX_SPREAD_PTS,
                 max_daily_losses: int = config.MAX_DAILY_LOSSES,
                 max_consecutive_losses: int = config.MAX_CONSECUTIVE_LOSSES,
                 max_open_positions_total: int = config.MAX_OPEN_POSITIONS_TOTAL):
        self.balance = float(balance)
        self.risk_percent = risk_percent
        self.min_rr = min_rr
        self.max_spread_pts = max_spread_pts
        self.max_daily_losses = max_daily_losses
        self.max_consecutive_losses = max_consecutive_losses
        self.max_open_positions_total = max_open_positions_total

        # بارگذاری state برای loss counter (سراسری بین همه‌ی نمادها)
        self._state = self._load_state()
        logger.info("RiskManager ready | balance=%.2f | risk=%.1f%% | minRR=1:%.1f | "
                    "maxOpenTotal=%d",
                    self.balance, self.risk_percent, self.min_rr,
                    self.max_open_positions_total)

    # ─────────────────────────────────────────────
    # Symbol/Account helpers
    # ─────────────────────────────────────────────
    def update_balance(self, balance: float) -> None:
        """به‌روزرسانی موجودی حساب (قبل از هر معامله صدا زده شود)."""
        self.balance = float(balance)

    # ─────────────────────────────────────────────
    # Core Math: RR Calculation
    # ─────────────────────────────────────────────
    @staticmethod
    def compute_rr(entry: float, sl: float, tp: float, direction: str) -> float:
        """
        محاسبه دقیق RR از روی قیمت‌های خام.

        RR = reward / risk = |TP - entry| / |entry - SL|

        دیباگ: از مقادیر خام قیمت استفاده می‌کنیم نه P/L، چون
        commission/swap در RR نیامده و باید مستقل از آن باشد.
        """
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        if risk <= 0:
            return 0.0
        return reward / risk

    # ─────────────────────────────────────────────
    # Core Math: Lot Size (1% Risk)
    # ─────────────────────────────────────────────
    def calculate_lot_size(self, entry: float, stop_loss: float, symbol_info) -> float:
        """
        محاسبه حجم معامله برای دقیقاً risk_percent از موجودی، مخصوص یک نماد مشخص.

        فرمول:
            risk_amount = balance * (risk_percent / 100)
            sl_distance = |entry - stop_loss|   (در واحد قیمت)
            ticks = sl_distance / tick_size
            value_per_lot = ticks * tick_value
            lots = risk_amount / value_per_lot

        Args:
            symbol_info: خروجی mt5.symbol_info(symbol) مخصوص همان نمادی که
                         سیگنال روی آن گرفته شده (هر نماد digits/tick متفاوت دارد).

        دیباگ‌های کلیدی:
          - تقسیم بر صفر اگر tick_size یا tick_value صفر باشند
          - normalize به volume_step با floor (نه round که banker's rounding دارد)
          - clamp به محدوده مجاز بروکر
          - fallback به contract_size اگر tick_value = 0
        """
        # 1. ریسک به پول
        risk_amount = self.balance * (self.risk_percent / 100.0)
        if risk_amount <= 0:
            logger.warning("Risk amount <= 0 (balance=%.2f).", self.balance)
            return 0.0

        # 2. فاصله SL در واحد قیمت
        sl_distance = abs(entry - stop_loss)
        if sl_distance <= 0:
            logger.warning("SL distance <= 0 (entry=%s, sl=%s).", entry, stop_loss)
            return 0.0

        # 3. استخراج مقادیر از symbol_info مخصوص این نماد
        tick_size = float(symbol_info.trade_tick_size)
        tick_value = float(symbol_info.trade_tick_value)
        volume_min = float(symbol_info.volume_min)
        volume_max = float(symbol_info.volume_max)
        volume_step = float(symbol_info.volume_step) or 0.01
        digits = int(symbol_info.digits)
        symbol_name = getattr(symbol_info, "name", "?")

        # 4. محاسبه ارزش هر لات کامل
        if tick_size <= 0 or tick_value <= 0:
            # Fallback: محاسبه از contract_size (بدیاتر ولی کار می‌کند)
            logger.warning("tick_value/tick_size is zero for %s! Using contract_size fallback.",
                           symbol_name)
            value_per_lot = self._estimate_value_per_lot(sl_distance, symbol_info)
        else:
            ticks = sl_distance / tick_size
            value_per_lot = ticks * tick_value

        if value_per_lot <= 0:
            logger.error("value_per_lot <= 0 for %s. Cannot compute lot size.", symbol_name)
            return 0.0

        # 5. محاسبه لات خام
        raw_lots = risk_amount / value_per_lot

        # 6. Normalize به volume_step با floor (جلوگیری از round up که ریسک را زیاد می‌کند)
        lots = math.floor(raw_lots / volume_step) * volume_step

        # 7. Clamp به محدوده مجاز بروکر
        lots = max(volume_min, min(volume_max, lots))

        # اگر لات خام کمتر از volume_min بود، یعنی ریسک حتی با حداقل لات هم بیشتر از 1% است
        if raw_lots < volume_min:
            logger.warning("Computed lots (%.4f) below volume_min (%.2f) for %s. "
                           "Using volume_min but risk exceeds %.1f%%.",
                           raw_lots, volume_min, symbol_name, self.risk_percent)

        logger.info("Lot size [%s]: %.2f | risk_amount=%.2f | sl_dist=%.5f | val/lot=%.2f",
                    symbol_name, lots, risk_amount, sl_distance, value_per_lot)
        return round(lots, digits)

    @staticmethod
    def _estimate_value_per_lot(sl_distance: float, symbol_info) -> float:
        """
        Fallback برای محاسبه ارزش هر لات وقتی tick_value صفر است.
        این روش دقیق نیست ولی از کرش جلوگیری می‌کند.
        """
        try:
            contract_size = float(symbol_info.trade_contract_size)
            # تقریب: ارزش جابجایی قیمت برابر contract_size است
            # (برای XAUUSD با contract_size=100، هر 1.0 حرکت قیمت = 100 دلار)
            return sl_distance * contract_size
        except (AttributeError, TypeError):
            logger.error("Cannot estimate value_per_lot (no contract_size).")
            return 0.0

    # ─────────────────────────────────────────────
    # Filters: RR & Spread
    # ─────────────────────────────────────────────
    def check_rr(self, entry: float, sl: float, tp: float, direction: str) -> bool:
        """بررسی RR ≥ min_rr. True اگر قابل قبول باشد."""
        rr = self.compute_rr(entry, sl, tp, direction)
        ok = rr >= self.min_rr
        if ok:
            logger.info("RR check PASS: 1:%.2f (min 1:%.1f)", rr, self.min_rr)
        else:
            logger.info("RR check FAIL: 1:%.2f < 1:%.1f → rejected", rr, self.min_rr)
        return ok

    def check_spread(self, spread_points: float) -> bool:
        """بررسی اسپرد ≤ max. True اگر قابل قبول باشد."""
        ok = spread_points <= self.max_spread_pts
        if ok:
            logger.debug("Spread OK: %.1f pts (max %.1f)", spread_points, self.max_spread_pts)
        else:
            logger.info("Spread too high: %.1f > %.1f → rejected",
                        spread_points, self.max_spread_pts)
        return ok

    # ─────────────────────────────────────────────
    # Daily Loss Tracking (3-loss rule)
    # ─────────────────────────────────────────────
    def _today_key(self) -> str:
        """کلید تاریخ امروز UTC برای ریست روزانه."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load_state(self) -> dict:
        """بارگذاری state از فایل (برای persist پس از restart)."""
        try:
            with open(config.STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return self._default_state()
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load state: %s. Resetting.", e)
            return self._default_state()

    @staticmethod
    def _default_state() -> dict:
        return {
            "date": "",
            "daily_losses": 0,
            "consecutive_losses": 0,
        }

    def _save_state(self) -> None:
        """ذخیره state در فایل."""
        try:
            with open(config.STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2)
        except OSError as e:
            logger.warning("Failed to save state: %s", e)

    def _check_daily_reset(self) -> None:
        """اگر تاریخ عوض شده، شمارنده‌ها رو ریست کن."""
        today = self._today_key()
        if self._state.get("date") != today:
            logger.info("New trading day (%s). Resetting daily loss counter "
                        "(was %d).",
                        today, self._state.get("daily_losses", 0))
            self._state["date"] = today
            self._state["daily_losses"] = 0
            # توجه: consecutive_losses ریست نمی‌شود چون فقط با WIN ریست می‌شود
            self._save_state()

    def record_loss(self) -> None:
        """ثبت یک ضرر. باید بعد از بسته شدن هر معامله‌ی بازنده صدا زده شود."""
        self._check_daily_reset()
        self._state["daily_losses"] = self._state.get("daily_losses", 0) + 1
        self._state["consecutive_losses"] = self._state.get("consecutive_losses", 0) + 1
        self._save_state()
        logger.warning("Loss recorded | daily=%d/%d | consecutive=%d/%d",
                       self._state["daily_losses"], self.max_daily_losses,
                       self._state["consecutive_losses"], self.max_consecutive_losses)

    def record_win(self) -> None:
        """ثبت یک برد. consecutive counter را ریست می‌کند."""
        self._check_daily_reset()
        self._state["consecutive_losses"] = 0
        # daily_losses را افزایش نمی‌دهیم
        self._save_state()
        logger.info("Win recorded. Consecutive losses reset to 0.")

    def can_open_new_trade(self) -> bool:
        """
        آیا مجاز به باز کردن معامله‌ی جدید هستیم؟

        قانون: اگر daily_losses >= MAX_DAILY_LOSSES یا
               consecutive_losses >= MAX_CONSECUTIVE_LOSSES
               → توقف تا فردا.
        """
        self._check_daily_reset()
        daily = self._state.get("daily_losses", 0)
        consec = self._state.get("consecutive_losses", 0)

        if daily >= self.max_daily_losses:
            logger.warning("Daily loss limit reached (%d/%d). Trading halted on ALL symbols until tomorrow.",
                           daily, self.max_daily_losses)
            return False
        if consec >= self.max_consecutive_losses:
            logger.warning("Consecutive loss limit reached (%d/%d). Trading halted on ALL symbols.",
                           consec, self.max_consecutive_losses)
            return False
        return True

    # ─────────────────────────────────────────────
    # Master Check (combines all filters)
    # ─────────────────────────────────────────────
    def validate_signal(self, signal, spread_points: float, symbol_info,
                         open_positions_total: int,
                         has_position_this_symbol: bool) -> dict:
        """
        اجرای تمام فیلترها روی یک سیگنال. خروجی dict با نتیجه و دلیل.

        Args:
            signal: شیء Signal از strategy.py (دارای entry, stop_loss, take_profit, direction)
            spread_points: اسپرد فعلی بازار (از symbol_info_tick)
            symbol_info: خروجی mt5.symbol_info(symbol) مخصوص نمادی که سیگنال روی آن است
            open_positions_total: تعداد کل پوزیشن‌های باز ربات روی همه‌ی نمادها (قبل از این سیگنال)
            has_position_this_symbol: آیا از قبل روی همین نماد پوزیشن باز است؟

        Returns:
            dict: {
                "approved": bool,
                "reason": str,
                "lot_size": float (0 if rejected),
                "rr": float,
                "risk_amount": float,
            }
        """
        result = {
            "approved": False,
            "reason": "",
            "lot_size": 0.0,
            "rr": 0.0,
            "risk_amount": 0.0,
        }

        # 1. سیگنال معتبر است؟
        if not signal.is_valid:
            result["reason"] = "Invalid signal (direction=NONE or entry=0)"
            return result

        # 2. آیا از قبل روی همین نماد پوزیشن باز است؟ (حداکثر یک پوزیشن به‌ازای هر نماد)
        if has_position_this_symbol:
            result["reason"] = "Position already open on this symbol"
            return result

        # 3. سقف کل پوزیشن‌های باز روی همه‌ی نمادها
        if open_positions_total >= self.max_open_positions_total:
            result["reason"] = (f"Max total open positions reached "
                               f"({open_positions_total}/{self.max_open_positions_total})")
            return result

        # 4. قانون 3 ضرر (سراسری، روی همه‌ی نمادها)
        if not self.can_open_new_trade():
            result["reason"] = "Daily/consecutive loss limit reached"
            return result

        # 5. فیلتر اسپرد
        if not self.check_spread(spread_points):
            result["reason"] = f"Spread {spread_points:.1f} > max {self.max_spread_pts}"
            return result

        # 6. فیلتر RR
        rr = self.compute_rr(signal.entry, signal.stop_loss,
                             signal.take_profit, signal.direction)
        result["rr"] = round(rr, 2)
        if rr < self.min_rr:
            result["reason"] = f"RR 1:{rr:.2f} < 1:{self.min_rr:.1f}"
            return result

        # 7. محاسبه لات (مخصوص همین نماد)
        lots = self.calculate_lot_size(signal.entry, signal.stop_loss, symbol_info)
        if lots <= 0:
            result["reason"] = "Lot size = 0 (SL too tight or balance issue)"
            return result

        # 8. محاسبه ریسک واقعی پس از clamp لات
        risk_amount = self.balance * (self.risk_percent / 100.0)
        result["risk_amount"] = round(risk_amount, 2)

        result["approved"] = True
        result["lot_size"] = lots
        result["reason"] = "All checks passed"
        return result


# ─────────────────────────────────────────────
# Smoke test — python risk_manager.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)

    # Mock symbol_info شبیه‌سازی‌شده برای XAUUSD
    class MockSymbolInfo:
        name = "XAUUSD_o"
        point = 0.01
        digits = 2
        trade_tick_size = 0.01
        trade_tick_value = 0.01   # هر tick = 0.01 دلار برای 1 لات
        volume_min = 0.01
        volume_max = 100.0
        volume_step = 0.01
        trade_contract_size = 100

    print("=== RiskManager Test ===")
    rm = RiskManager(balance=10000.0)
    mock_info = MockSymbolInfo()

    # Test 1: محاسبه لات استاندارد
    print("\n--- Test 1: Standard lot calc ---")
    entry, sl, tp = 2000.00, 1990.00, 2020.00  # risk=10, reward=20 → RR=2
    lots = rm.calculate_lot_size(entry, sl, mock_info)
    print(f"Entry={entry}, SL={sl}, TP={tp}")
    print(f"Lot size = {lots}")
    rr = rm.compute_rr(entry, sl, tp, "BUY")
    print(f"RR = 1:{rr:.2f}")

    # Test 2: RR filter
    print("\n--- Test 2: RR filter ---")
    print(f"RR 2.0 >= 2.0? {rm.check_rr(2000, 1990, 2020, 'BUY')}")  # True
    print(f"RR 1.5 < 2.0?  {rm.check_rr(2000, 1990, 2005, 'BUY')}")  # False (reward=5)

    # Test 3: Spread filter
    print("\n--- Test 3: Spread filter ---")
    print(f"Spread 30 ok? {rm.check_spread(30)}")  # True
    print(f"Spread 60 ok? {rm.check_spread(60)}")  # False

    # Test 4: Loss tracking
    print("\n--- Test 4: Loss tracking ---")
    print(f"Can trade initially? {rm.can_open_new_trade()}")  # True
    rm.record_loss()
    rm.record_loss()
    print(f"After 2 losses, can trade? {rm.can_open_new_trade()}")  # True
    rm.record_loss()
    print(f"After 3 losses, can trade? {rm.can_open_new_trade()}")  # False

    # Cleanup test state
    import os
    if os.path.exists(config.STATE_FILE):
        os.remove(config.STATE_FILE)
    print("\n=== All tests done ===")
