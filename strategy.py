"""
strategy.py
استراتژی ترکیبی ICT + RSI Divergence.

مفاهیم پیاده‌سازی‌شده:
  1. RSI (Wilder's smoothing) — محاسبه با ewm دقیقاً مطابق تعریف کلاسیک
  2. Swing High/Low (Fractal Pivots) — فقط روی کندل‌های بسته‌شده
  3. FVG (Fair Value Gap) — گپ سه‌کندلی
  4. Liquidity Sweep — شکستن extreme با بسته شدن برگشتی
  5. RSI Divergence — واگرایی روی نقاط swing هم‌نوع
  6. MSS (Market Structure Shift) — تأیید با شکست آخرین ساختار
  7. Bias Filter — فقط معاملات در جهت بایاس ماکرو روزانه

نکات دیباگ کلیدی:
  - هیچ look-ahead در محاسبات نیست (همه با shift و کندل بسته‌شده).
  - pivot نیاز به lookback کندل سمت راست دارد، بنابراین آخرین 'lookback'
    کندل نمی‌توانند pivot باشند (جلوگیری از repaint).
  - سیگنال فقط روی آخرین کندل بسته‌شده تولید می‌شود.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────
@dataclass
class Signal:
    """خروجی استراتژی — یک ستاپ معاملاتی کامل."""
    direction: str = "NONE"          # BUY / SELL / NONE
    entry: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    rsi: float = 0.0
    bias: str = "NEUTRAL"
    confidence: float = 0.0
    reason: str = ""

    @property
    def is_valid(self) -> bool:
        return self.direction in ("BUY", "SELL") and self.entry > 0

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "rsi": round(self.rsi, 2),
            "bias": self.bias,
            "confidence": round(self.confidence, 2),
            "reason": self.reason,
        }


# ─────────────────────────────────────────────
# Strategy
# ─────────────────────────────────────────────
class ICT_RSI_Strategy:
    """
    ICT + RSI Divergence Strategy.

    پارامترها از config.py خوانده می‌شوند. نمونه‌سازی:
        strategy = ICT_RSI_Strategy()
        df = connector.get_candles()
        df = strategy.calculate_indicators(df)
        signal = strategy.generate_signal(df, daily_bias="BULLISH")
    """

    def __init__(self,
                 rsi_period: int = config.RSI_PERIOD,
                 swing_lookback: int = config.SWING_LOOKBACK,
                 swing_min_distance: int = config.SWING_MIN_DISTANCE,
                 sweep_buffer_pts: float = config.SWEEP_BUFFER_PTS,
                 mss_lookback: int = config.MSS_LOOKBACK,
                 rr_ratio: float = 2.0):
        self.rsi_period = rsi_period
        self.swing_lookback = swing_lookback
        self.swing_min_distance = swing_min_distance
        self.sweep_buffer_pts = sweep_buffer_pts
        self.mss_lookback = mss_lookback
        self.rr_ratio = rr_ratio
        logger.info("ICT+RSI Strategy initialized | RSI=%d, SwingLB=%d, RR=%.1f",
                    rsi_period, swing_lookback, rr_ratio)

    # ─────────────────────────────────────────────
    # 1. RSI (Wilder's Smoothing)
    # ─────────────────────────────────────────────
    def _compute_rsi(self, close: pd.Series) -> pd.Series:
        """
        محاسبه RSI با روش Wilder (EMA با alpha = 1/period).
        این روش استاندارد ترجینگ‌ویو است؛ SMA اشتباه است.
        """
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)

        # Wilder smoothing = EMA با alpha = 1/period
        avg_gain = gain.ewm(alpha=1.0 / self.rsi_period,
                            min_periods=self.rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / self.rsi_period,
                            min_periods=self.rsi_period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        # پر کردن NaN اولیه با 50 (neutral)
        return rsi.fillna(50.0)

    # ─────────────────────────────────────────────
    # 2. Swing Highs/Lows (Fractal Pivots)
    # ─────────────────────────────────────────────
    def _detect_swings(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        تشخیص فراکتال‌ها: نقطه‌ای که 'lookback' کندل سمت چپ و راست
        آن همگی lower (برای swing high) یا higher (برای swing low) باشند.

        دیباگ: آخرین 'lookback' کندل نمی‌توانند pivot باشند چون هنوز
        سمت راستشان کامل نشده. این از repaint جلوگیری می‌کند.
        """
        lb = self.swing_lookback
        highs = df['high'].values
        lows = df['low'].values
        n = len(df)

        is_swing_high = np.zeros(n, dtype=bool)
        is_swing_low = np.zeros(n, dtype=bool)

        for i in range(lb, n - lb):
            window_high = highs[i - lb: i + lb + 1]
            window_low = lows[i - lb: i + lb + 1]
            # نقطه مرکزی باید سختیرین/بالاترین باشد (بزرگ‌ترین < max با تکرار → use unique check)
            if highs[i] == window_high.max() and np.sum(window_high == highs[i]) == 1:
                is_swing_high[i] = True
            if lows[i] == window_low.min() and np.sum(window_low == lows[i]) == 1:
                is_swing_low[i] = True

        df['swing_high'] = np.where(is_swing_high, df['high'], np.nan)
        df['swing_low'] = np.where(is_swing_low, df['low'], np.nan)

        n_high = int(is_swing_high.sum())
        n_low = int(is_swing_low.sum())
        logger.debug("Detected %d swing highs and %d swing lows.", n_high, n_low)
        return df

    # ─────────────────────────│─────────────────
    # 3. FVG Detection (3-candle pattern)
    # ─────────────────────────────────────────────
    def _detect_fvg(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Fair Value Gap — گپ بین کندل اول و سوم در یک پترن سه‌کندلی.

        Bullish FVG: high[i-2] < low[i]  (گپ رو به بالا)
        Bearish FVG: low[i-2]  > high[i] (گپ رو به پایین)

        دیباگ: گپ روی کندل میانی ثبت می‌شود ولی با کندل‌های i-2 و i
        تعریف می‌شود. این طبیعی است.
        """
        # استفاده از shift برای جلوگیری از look-ahead
        h_prev2 = df['high'].shift(2)
        l_prev2 = df['low'].shift(2)
        low_cur = df['low']
        high_cur = df['high']

        # Bullish FVG: gap up between candle[i-2].high and candle[i].low
        df['fvg_bull'] = np.where(h_prev2 < low_cur, 1, 0)
        df['fvg_bull_top'] = np.where(df['fvg_bull'] == 1, low_cur, np.nan)
        df['fvg_bull_bot'] = np.where(df['fvg_bull'] == 1, h_prev2, np.nan)

        # Bearish FVG: gap down between candle[i-2].low and candle[i].high
        df['fvg_bear'] = np.where(l_prev2 > high_cur, 1, 0)
        df['fvg_bear_top'] = np.where(df['fvg_bear'] == 1, l_prev2, np.nan)
        df['fvg_bear_bot'] = np.where(df['fvg_bear'] == 1, high_cur, np.nan)

        n_bull = int(df['fvg_bull'].sum())
        n_bear = int(df['fvg_bear'].sum())
        logger.debug("Detected %d bullish FVG and %d bearish FVG.", n_bull, n_bear)
        return df

    # ─────────────────────────────────────────────
    # 4. Liquidity Sweep
    # ─────────────────────────────────────────────
    def _detect_sweep(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Liquidity Sweep = وقتی کندل extreme اخیر را با wick می‌شکند ولی
        بسته شدن در داخل محدوده برگشت می‌خورد.

        دیباگ: extreme از swing‌های قبلی محاسبه می‌شود، نه از همین کندل.
        بافر از config برای محاسبه ناحیه تنور حرارت اضافه می‌شود.
        """
        # محاسبه rolling extreme از swing‌های تأییدشده
        # ناحیه بالای آخرین swing high = "buy-side liquidity"
        # ناحیه پایین آخرین swing low = "sell-side liquidity"
        df['prev_swing_high'] = df['swing_high'].shift(1).ffill()
        df['prev_swing_low'] = df['swing_low'].shift(1).ffill()

        buf = self.sweep_buffer_pts

        # Bullish sweep: کندل پایین آخرین swing low را می‌شکند (take sell-side liq)
        # then closes back above it (rejection of lower prices).
        took_liquid_low = (df['low'] < df['prev_swing_low'] - buf)
        closed_back_up = (df['close'] > df['prev_swing_low'])
        df['sweep_bull'] = np.where(took_liquid_low & closed_back_up, 1, 0)

        # Bearish sweep: کندل بالای آخرین swing high را می‌شکند (take buy-side liq)
        # then closes back below it (rejection of higher prices).
        took_liquid_high = (df['high'] > df['prev_swing_high'] + buf)
        closed_back_down = (df['close'] < df['prev_swing_high'])
        df['sweep_bear'] = np.where(took_liquid_high & closed_back_down, 1, 0)

        n_bull = int(df['sweep_bull'].sum())
        n_bear = int(df['sweep_bear'].sum())
        logger.debug("Detected %d bullish sweeps and %d bearish sweeps.", n_bull, n_bear)
        return df

    # ─────────────────────────────────────────────
    # 5. RSI Divergence (on swings)
    # ─────────────────────────────────────────────
    def _detect_divergence(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        واگرایی بین دو نقطه‌ی swing هم‌نوع.

        Bullish divergence: price Lower Low + RSI Higher Low
        Bearish divergence: price Higher High + RSI Lower High

        دیباگ: فقط بین دو swing هم‌نوع با حداقل فاصله مقایسه می‌شود.
        """
        df['div_bull'] = 0
        df['div_bear'] = 0

        # پیدا کردن positional index‌های swing‌های تأییدشده (NaN نیستند)
        # دیباگ: از positional (iloc position) استفاده می‌کنیم نه Timestamp،
        # زیرا تفاضل Timestamp با int قابل مقایسه نیست.
        high_pos = np.flatnonzero(df['swing_high'].notna().values)
        low_pos = np.flatnonzero(df['swing_low'].notna().values)

        # --- Bearish divergence (Higher High price + Lower High RSI) ---
        if len(high_pos) >= 2:
            for k in range(1, len(high_pos)):
                prev_p = high_pos[k - 1]
                curr_p = high_pos[k]
                # حداقل فاصله (بر اساس تعداد کندل)
                if (curr_p - prev_p) < self.swing_min_distance:
                    continue
                price_hh = df['high'].iloc[curr_p] > df['high'].iloc[prev_p]
                rsi_lh = df['rsi'].iloc[curr_p] < df['rsi'].iloc[prev_p]
                if price_hh and rsi_lh:
                    df.iloc[curr_p, df.columns.get_loc('div_bear')] = 1

        # --- Bullish divergence (Lower Low price + Higher Low RSI) ---
        if len(low_pos) >= 2:
            for k in range(1, len(low_pos)):
                prev_p = low_pos[k - 1]
                curr_p = low_pos[k]
                if (curr_p - prev_p) < self.swing_min_distance:
                    continue
                price_ll = df['low'].iloc[curr_p] < df['low'].iloc[prev_p]
                rsi_hl = df['rsi'].iloc[curr_p] > df['rsi'].iloc[prev_p]
                if price_ll and rsi_hl:
                    df.iloc[curr_p, df.columns.get_loc('div_bull')] = 1

        n_bull = int(df['div_bull'].sum())
        n_bear = int(df['div_bear'].sum())
        logger.debug("Detected %d bullish divergence and %d bearish divergence.",
                     n_bull, n_bear)
        return df

    # ─────────────────────────────────────────────
    # 6. MSS (Market Structure Shift)
    # ─────────────────────────────────────────────
    def _detect_mss(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Market Structure Shift = قیمت آخرین swing high/low را می‌شکند
        که نشانگر تغییر روند است.

        Bullish MSS: close بالای آخرین swing high (در mss_lookback کندل اخیر)
        Bearish MSS: close پایین آخرین swing low (در mss_lookback کندل اخیر)
        """
        df['mss_bull'] = 0
        df['mss_bear'] = 0

        # آخرین swing high/low معتبر قبل از کندل فعلی
        df['last_sh'] = df['swing_high'].replace(0, np.nan).ffill()
        df['last_sl'] = df['swing_low'].replace(0, np.nan).ffill()

        # Bullish MSS: close > last swing high
        df['mss_bull'] = np.where(df['close'] > df['last_sh'], 1, 0)

        # Bearish MSS: close < last swing low
        df['mss_bear'] = np.where(df['close'] < df['last_sl'], 1, 0)

        n_bull = int(df['mss_bull'].sum())
        n_bear = int(df['mss_bear'].sum())
        logger.debug("MSS detection: bull=%d, bear=%d", n_bull, n_bear)
        return df

    # ─────────────────────────۲──────────────────
    # Public: Calculate all indicators
    # ─────────────────────────────────────────────
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        محاسبه تمام اندیکاتورها روی دیتافریم کندل‌ها.
        دیتافریم اصلی mutate می‌شود (ستون‌های جدید اضافه می‌کند).

        Args:
            df: DataFrame با ستون‌های high, low, close, volume
        """
        if df.empty:
            logger.warning("Empty dataframe in calculate_indicators.")
            return df
        if len(df) < self.rsi_period + self.swing_lookback * 2 + 5:
            logger.warning("Not enough candles (%d) for strategy.", len(df))
            return df

        df = df.copy()
        df = self._compute_rsi_inline(df)
        df = self._detect_swings(df)
        df = self._detect_fvg(df)
        df = self._detect_sweep(df)
        df = self._detect_divergence(df)
        df = self._detect_mss(df)
        return df

    def _compute_rsi_inline(self, df: pd.DataFrame) -> pd.DataFrame:
        """Wrapper برای محاسبه RSI و اضافه کردن ستون."""
        df['rsi'] = self._compute_rsi(df['close'])
        return df

    # ─────────────────────────────────────────────
    # Public: Generate signal on latest closed candle
    # ─────────────────────────────────────────────
    def generate_signal(self, df: pd.DataFrame, daily_bias: str) -> Signal:
        """
        بررسی آخرین کندل بسته‌شده و تولید سیگنال در صورت تکمیل ستاپ.

        منطق ستاپ:
          BUY setup:
            - بایاس روزانه BULLISH یا NEUTRAL
            - Liquidity Sweep به سمت پایین (sweep_bull == 1)
            - واگرایی صعودی RSI (div_bull == 1) در همان ناحیه
            - MSS صعودی (mss_bull == 1) تأیید کند
            - FVG صعودی در ناحیه ورود
          SELL setup:
            - بایاس روزانه BEARISH یا NEUTRAL
            - Liquidity Sweep به سمت بالا (sweep_bear == 1)
            - واگرایی نزولی RSI (div_bear == 1)
            - MSS نزولی (mss_bear == 1)
            - FVG نزولی

        Args:
            df: DataFrame پس از calculate_indicators()
            daily_bias: "BULLISH" / "BEARISH" / "NEUTRAL"

        Returns:
            Signal dataclass با direction="NONE" اگر ستاپی نباشد.
        """
        if df.empty:
            return Signal(reason="empty dataframe")
        bias = str(daily_bias).upper().strip()

        # استفاده از کندل آخر (بسته‌شده، تاریخ گذشته) + پنجره اخیر
        lookback = self.mss_lookback
        recent = df.iloc[-lookback:]
        last = df.iloc[-1]

        # ── BUY setup ──
        if bias in ("BULLISH", "NEUTRAL"):
            has_sweep = recent['sweep_bull'].sum() > 0
            has_div = recent['div_bull'].sum() > 0
            has_mss = recent['mss_bull'].sum() > 0
            has_fvg = recent['fvg_bull'].sum() > 0
            if has_sweep and has_div and has_mss and has_fvg:
                # SL = پایین wick sweep, TP = entry + RR * risk
                entry = float(last['close'])
                sweep_low = float(recent['low'].min())
                risk = entry - sweep_low
                if risk <= 0:
                    logger.debug("BUY risk<=0, skipping.")
                else:
                    return self._build_signal(
                        direction="BUY", entry=entry,
                        stop_loss=sweep_low - self.sweep_buffer_pts,
                        rsi=last['rsi'], bias=bias, df_recent=recent,
                        reason=f"BULLISH bias | sweep+div+mss | FVG={int(has_fvg)}"
                    )

        # ── SELL setup ──
        if bias in ("BEARISH", "NEUTRAL"):
            has_sweep = recent['sweep_bear'].sum() > 0
            has_div = recent['div_bear'].sum() > 0
            has_mss = recent['mss_bear'].sum() > 0
            has_fvg = recent['fvg_bear'].sum() > 0
            if has_sweep and has_div and has_mss and has_fvg:
                entry = float(last['close'])
                sweep_high = float(recent['high'].max())
                risk = sweep_high - entry
                if risk <= 0:
                    logger.debug("SELL risk<=0, skipping.")
                else:
                    return self._build_signal(
                        direction="SELL", entry=entry,
                        stop_loss=sweep_high + self.sweep_buffer_pts,
                        rsi=last['rsi'], bias=bias, df_recent=recent,
                        reason=f"BEARISH bias | sweep+div+mss | FVG={int(has_fvg)}"
                    )
        return Signal(reason=f"no setup | bias={bias}")

    def _build_signal(self, direction, entry, stop_loss, rsi, bias, df_recent, reason):
        """ساخت شیء Signal با محاسبه TP بر اساس RR ratio."""
        risk = abs(entry - stop_loss)
        if risk <= 0:
            return Signal(reason="risk<=0")
        if direction == "BUY":
            take_profit = entry + self.rr_ratio * risk
        else:
            take_profit = entry - self.rr_ratio * risk
        confidence = min(100.0, (risk / entry) * 1000 * 10)  # heuristic
        return Signal(
            direction=direction, entry=round(entry, 5),
            stop_loss=round(stop_loss, 5),
            take_profit=round(take_profit, 5),
            rsi=float(rsi), bias=bias,
            confidence=round(confidence, 2),
            reason=reason
        )
