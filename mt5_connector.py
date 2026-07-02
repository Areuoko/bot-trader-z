"""
mt5_connector.py
اتصال به MetaTrader 5، تأیید حساب و دریافت کندل‌های M15.
"""
import logging
from datetime import datetime, timezone

import MetaTrader5 as mt5
import pandas as pd

import config

logger = logging.getLogger(__name__)


class MT5Connector:
    """مدیریت کانکشن و دریافت داده از MetaTrader 5."""

    def __init__(self,
                 path: str = config.MT5_PATH,
                 login: int = config.MT5_LOGIN,
                 password: str = config.MT5_PASSWORD,
                 server: str = config.MT5_SERVER):
        self.path = path
        self.login = login
        self.password = password
        self.server = server
        self._connected = False

    # ─────────────────────────────────────────────
    # Connection Management
    # ─────────────────────────────────────────────
    def connect(self) -> bool:
        """اتصال به ترمینال و لاگین به حساب. در صورت خطا False برمی‌گرداند."""
        # مقداردهی اولیه ترمینال با مسیر نصب
        if not mt5.initialize(path=self.path,
                              login=self.login,
                              password=self.password,
                              server=self.server):
            err = mt5.last_error()
            logger.error("initialize() failed: %s", err)
            self._connected = False
            return False

        # تأیید حساب
        info = mt5.account_info()
        if info is None:
            logger.error("account_info() returned None — cannot verify login.")
            self._connected = False
            return False

        logger.info("Connected ✓ | login=%s | server=%s | balance=%.2f %s",
                    info.login, info.server, info.balance, info.currency)
        self._connected = True
        return True

    def disconnect(self) -> None:
        """قطع اتصال تمیز از ترمینال."""
        if self._connected:
            mt5.shutdown()
            self._connected = False
            logger.info("Disconnected from MetaTrader 5.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ─────────────────────────────────────────CTS
    # Market Data
    # ─────────────────────────────────────────────
    def get_candles(self,
                    symbol: str = config.SYMBOL,
                    timeframe=mt5.TIMEFRAME_M15,
                    count: int = config.CANDLE_COUNT) -> pd.DataFrame:
        """
        دریافت آخرین 'count' کندل برای سمبل و تایم‌فریم مشخص‌شده.

        خروجی: DataFrame با ستون‌های time(OHLCV) و اندیس تایم‌زون‌دار UTC.
        در صورت بروز خطا، DataFrame خالی برمی‌گرداند.
        """
        if not self._connected:
            logger.error("get_candles() called before successful connect().")
            return pd.DataFrame()

        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            logger.error("copy_rates_from_pos returned no data for %s.", symbol)
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        # تبدیل ثانیه epoch → datetime آگاه از تایم‌زون UTC
        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
        df.set_index('time', inplace=True)
        # ست اضافی _tick_volume و spread_real -> تغییر نام برای خوانایی
        if 'spread' in df.columns:
            df.rename(columns={'spread': 'spread_pts'}, inplace=True)

        logger.info("Fetched %d M15 candles for %s | from %s to %s",
                    len(df), symbol, df.index[0], df.index[-1])
        return df

    # ─────────────────────────────────────────────
    # Symbol info helper
    # ─────────────────────────────────────────────
    def get_symbol_info(self, symbol: str = config.SYMBOL):
        """اطلاعات سمبل (point, digits, contract_size, ...)."""
        if not self._connected:
            logger.error("get_symbol_info() called before connect().")
            return None
        info = mt5.symbol_info(symbol)
        if info is None:
            logger.error("symbol_info(%s) returned None.", symbol)
        return info

    # ─────────────────────────────────────────────
    # Context manager support
    # ─────────────────────────────────────────────
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
