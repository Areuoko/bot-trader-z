from mt5_connector import MT5Connector

conn = MT5Connector()
if conn.connect():
    df = conn.get_candles(count=10)
    print(df)
    conn.disconnect()