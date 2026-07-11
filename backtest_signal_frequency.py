"""
backtest_signal_frequency.py
سنجش فرکانس واقعی سیگنال ICT+RSI روی داده‌ی تاریخی، مستقل از بایاس AI.

منطق:
  - بایاس داخلی همیشه NEUTRAL فرض می‌شود (چون NEUTRAL هم BUY و هم SELL را
    مجاز می‌شمارد در strategy.py) → یعنی فرکانس واقعی خودِ ستاپ ICT سنجیده
    می‌شود، مستقل از این‌که AI چه بایاسی می‌داد.
  - walk-forward: در هر گام فقط کندل‌های تا همان نقطه دیده می‌شود (بدون
    look-ahead)، دقیقاً مثل رفتار واقعی ربات در main.py.
  - کندل‌های متوالیِ هم‌جهت که فاصله‌شان ≤3 کندل است یک "فرصت" واحد
    محسوب می‌شوند (جلوگیری از شمارش تکراری یک رخداد واحد).

اجرا:
    python backtest_signal_frequency.py --symbol XAUUSD_o --candles 5000
    python backtest_signal_frequency.py --symbol XAGUSD_o --candles 5000
    python backtest_signal_frequency.py --symbol EURUSD_o --candles 5000
"""
import argparse

import config
from mt5_connector import MT5Connector
from strategy import ICT_RSI_Strategy


def cluster_signals(signals: list) -> list:
    """کندل‌های متوالی با سیگنال هم‌جهت را یک 'فرصت' واحد در نظر می‌گیرد."""
    if not signals:
        return []
    clusters = [signals[0]]
    for s in signals[1:]:
        last = clusters[-1]
        if s["direction"] == last["direction"] and (s["bar_index"] - last["bar_index"]) <= 3:
            continue  # ادامه‌ی همان رخداد، شمارش نمی‌شود
        clusters.append(s)
    return clusters


def run_backtest(symbol: str, candle_count: int) -> None:
    connector = MT5Connector()
    if not connector.connect():
        print("❌ اتصال MT5 ناموفق بود.")
        return

    print(f"دریافت {candle_count} کندل M15 برای {symbol}...")
    df = connector.get_candles(symbol=symbol, count=candle_count)
    if df.empty:
        print(f"❌ داده‌ای برای {symbol} دریافت نشد (نماد در MarketWatch فعال است؟).")
        connector.disconnect()
        return

    buffer = config.SWEEP_BUFFER_BY_SYMBOL.get(symbol, config.SWEEP_BUFFER_PTS)
    print(f"SWEEP_BUFFER_PTS برای {symbol}: {buffer}")
    strategy = ICT_RSI_Strategy(sweep_buffer_pts=buffer)
    df_ind = strategy.calculate_indicators(df)
    if df_ind.empty:
        print("❌ محاسبه‌ی اندیکاتور شکست خورد (تعداد کندل کافی نیست؟).")
        connector.disconnect()
        return

    lookback = strategy.mss_lookback
    raw_signals = []

    start_i = lookback + strategy.swing_lookback * 2 + strategy.rsi_period
    for i in range(start_i, len(df_ind)):
        window = df_ind.iloc[: i + 1]
        sig = strategy.generate_signal(window, daily_bias="NEUTRAL")
        if sig.is_valid:
            raw_signals.append({
                "bar_index": i,
                "time": df_ind.index[i],
                "direction": sig.direction,
                "entry": sig.entry,
                "sl": sig.stop_loss,
                "tp": sig.take_profit,
            })

    clusters = cluster_signals(raw_signals)
    n_buy = sum(1 for c in clusters if c["direction"] == "BUY")
    n_sell = sum(1 for c in clusters if c["direction"] == "SELL")
    days = (df_ind.index[-1] - df_ind.index[0]).total_seconds() / 86400

    print("\n=== نتیجه ===")
    print(f"نماد: {symbol}")
    print(f"بازه: {df_ind.index[0]} → {df_ind.index[-1]}  (~{days:.0f} روز)")
    print(f"فرصت‌های معاملاتی مجزا: {len(clusters)}  (BUY={n_buy}, SELL={n_sell})")
    if clusters:
        print(f"میانگین فاصله: هر ~{days / len(clusters):.1f} روز یک فرصت")
    print("\nنکته: این عدد هنوز فیلتر بایاس AI، سشن، و بلک‌اوت خبری اعمال نشده؛")
    print("تعداد معامله‌ی واقعی ربات معمولاً کمتر از این خواهد بود.")

    connector.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="سنجش فرکانس سیگنال ICT+RSI روی داده‌ی تاریخی")
    parser.add_argument("--symbol", default=config.SYMBOLS[0],
                        help="نماد برای بک‌تست (مثلاً XAUUSD_o)")
    parser.add_argument("--candles", type=int, default=5000,
                        help="تعداد کندل M15 تاریخی (پیش‌فرض 5000، ~52 روز)")
    args = parser.parse_args()

    run_backtest(args.symbol, args.candles)
