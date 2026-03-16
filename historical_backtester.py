import asyncio
import aiohttp
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime, timedelta, timezone
import os
import sys

# Importiere den bestehenden Polymarket Client
from phase2_polymarket import PolymarketClient

# --- BACKTEST CONFIG ---
FEES = 0.02              # 2% Taker Fee auf Polymarket
ASSUMED_SPREAD = 0.05    # 5% angenommener Spread (da historical prices oft Mid-Prices sind)
ENTRY_EDGE = 0.20        # 20% Edge für Entry
EXIT_EDGE = -0.03        # -3% Edge für Profit Exit

def bsm_prob_vec(S, K, T, sigma):
    """Vectorized Black-Scholes-Merton N(d2) für Pandas DataFrames"""
    T = np.maximum(T, 1e-8) # Verhindert Division durch Null
    d2 = (np.log(S / K) - (0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return norm.cdf(d2)

async def fetch_deribit_historical_vol(session, start_ms, end_ms):
    url = f"https://deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&start_timestamp={start_ms}&end_timestamp={end_ms}&resolution=3600"
    async with session.get(url) as resp:
        data = await resp.json()
        if "result" in data and "data" in data["result"] and data["result"]["data"]:
            df = pd.DataFrame(data["result"]["data"], columns=["timestamp", "open", "high", "low", "close"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df["iv"] = df["close"] / 100.0
            return df[["timestamp", "iv"]]
        return pd.DataFrame()

async def fetch_deribit_historical_price(session, start_ms, end_ms):
    url = f"https://deribit.com/api/v2/public/get_tradingview_chart_data?instrument_name=BTC-PERPETUAL&start_timestamp={start_ms}&end_timestamp={end_ms}&resolution=60"
    async with session.get(url) as resp:
        data = await resp.json()
        if "result" in data and data["result"].get("status") in ["ok", "no_data"] or data["result"].get("s") == "ok":
            res = data["result"]
            if not res.get("ticks"): return pd.DataFrame()
            df = pd.DataFrame({
                "timestamp": pd.to_datetime(res["ticks"], unit="ms"),
                "btc_price": res["close"]
            })
            return df
        return pd.DataFrame()

async def fetch_pm_history(session, token_id, start_ts, end_ts):
    url = f"https://clob.polymarket.com/prices-history?market={token_id}&startTs={start_ts}&endTs={end_ts}"
    async with session.get(url) as resp:
        if resp.status == 200:
            data = await resp.json()
            history = data.get("history", [])
            if history:
                df = pd.DataFrame(history)
                df["timestamp"] = pd.to_datetime(df["t"], unit="s")
                df["pm_price"] = df["p"]
                return df[["timestamp", "pm_price"]]
        return pd.DataFrame()

async def main():
    print("🚀 STARTE VECTORIZED HISTORICAL BACKTESTER...")
    
    # Zeitraum: Letzte 3 Tage
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=3)
    
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    start_s = int(start_dt.timestamp())
    end_s = int(end_dt.timestamp())

    async with aiohttp.ClientSession() as session:
        print("📥 Lade historische Deribit Daten (BTC Preis & DVOL)...")
        df_btc = await fetch_deribit_historical_price(session, start_ms, end_ms)
        df_iv = await fetch_deribit_historical_vol(session, start_ms, end_ms)
        
        if df_btc.empty or df_iv.empty:
            print("❌ Fehler: Konnte Deribit Daten nicht laden.")
            return

        # Resampling auf Minuten-Ebene (Forward Fill für stündliche IV)
        df_iv.set_index("timestamp", inplace=True)
        df_btc.set_index("timestamp", inplace=True)
        df_deribit = df_btc.join(df_iv, how="outer").ffill().dropna()

        print("🔍 Suche nach einem aktiven Polymarket BTC Markt...")
        pm_client = PolymarketClient()
        markets = await pm_client.get_active_btc_markets()
        
        target_market = None
        for m in markets:
            if m["days_to_expiry"] > 0.5: # Markt muss noch mindestens 12h laufen
                target_market = m
                break
                
        if not target_market:
            print("❌ Keinen passenden Markt gefunden.")
            return

        token_id = target_market["token_id"]
        strike = target_market["strike"]
        
        # Enddatum parsen
        end_date_str = target_market.get("endDate", target_market.get("end_date", ""))
        clean_date_str = end_date_str.split('.')[0].replace('Z', '')
        expiry_dt = datetime.strptime(clean_date_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        
        print(f"📥 Lade historische Polymarket Daten für Strike ${strike:,.2f}...")
        df_pm = await fetch_pm_history(session, token_id, start_s, end_s)
        
        if df_pm.empty:
            print("❌ Keine historischen Polymarket Daten gefunden.")
            return
            
        df_pm.set_index("timestamp", inplace=True)
        
        # Merge Deribit & Polymarket
        df = df_deribit.join(df_pm, how="inner").dropna()
        print(f"✅ Daten gemerged: {len(df)} 1-Minuten-Kerzen für Backtest bereit.")
        
        # --- VECTORIZED BACKTEST ---
        print("🧮 Berechne BSM Oracle Probabilities & Edges...")
        
        # T in Jahren berechnen
        df["T"] = (expiry_dt - df.index).total_seconds() / (365.25 * 24 * 3600)
        df = df[df["T"] > 0].copy()
        
        # BSM Wahrscheinlichkeit vektorisiert berechnen (1000x schneller als Loops)
        df["oracle_prob"] = bsm_prob_vec(df["btc_price"], strike, df["T"], df["iv"])
        
        # Spread & Fees simulieren
        df["pm_ask"] = df["pm_price"] * (1 + ASSUMED_SPREAD/2)
        df["pm_bid"] = df["pm_price"] * (1 - ASSUMED_SPREAD/2)
        
        df["pm_ask_fee"] = df["pm_ask"] * (1 + FEES)
        df["pm_bid_fee"] = df["pm_bid"] * (1 - FEES)
        
        df["buy_edge"] = df["oracle_prob"] - df["pm_ask_fee"]
        df["sell_edge"] = df["oracle_prob"] - df["pm_bid_fee"]
        
        # --- TRADE SIMULATION ---
        position = 0
        entry_price = 0
        trades = []
        
        for timestamp, row in df.iterrows():
            if position == 0:
                if row["buy_edge"] >= ENTRY_EDGE and 0.1 < row["pm_ask"] < 0.9:
                    position = 1
                    entry_price = row["pm_ask"]
                    trades.append({"type": "BUY", "time": timestamp, "price": entry_price, "edge": row["buy_edge"]})
            elif position == 1:
                is_profitable = row["pm_bid_fee"] > (entry_price * 1.02)
                profit_exit = (row["sell_edge"] <= EXIT_EDGE) and is_profitable
                thesis_invalid = (row["sell_edge"] <= -0.10) and not is_profitable
                stop_loss = row["pm_bid"] <= entry_price * 0.50
                
                if profit_exit or thesis_invalid or stop_loss:
                    exit_price = row["pm_bid"]
                    # PnL inkl. 2% Fee beim Kauf und 2% Fee beim Verkauf
                    pnl_pct = (exit_price * (1 - FEES) - entry_price * (1 + FEES)) / (entry_price * (1 + FEES))
                    reason = "Profit" if profit_exit else "Stop/Invalid"
                    trades.append({"type": "SELL", "time": timestamp, "price": exit_price, "pnl_pct": pnl_pct, "reason": reason})
                    position = 0
                    entry_price = 0
                    
        # --- REPORT ---
        print("\n" + "="*60)
        print("📊 VECTORIZED BACKTEST REPORT (V4.2)")
        print("="*60)
        print(f"Markt: BTC > ${strike:,.2f}")
        print(f"Zeitraum: {start_dt.strftime('%Y-%m-%d')} bis {end_dt.strftime('%Y-%m-%d')}")
        print(f"Datenpunkte (Minuten): {len(df)}")
        print(f"Angenommener Spread: {ASSUMED_SPREAD*100:.1f}% | Taker Fees: {FEES*100:.1f}%")
        print("-" * 60)
        
        sells = [t for t in trades if t["type"] == "SELL"]
        if not sells:
            print("Keine abgeschlossenen Trades in diesem Zeitraum.")
        else:
            wins = [t for t in sells if t["pnl_pct"] > 0]
            win_rate = len(wins) / len(sells)
            avg_pnl = np.mean([t["pnl_pct"] for t in sells])
            total_pnl = np.sum([t["pnl_pct"] for t in sells])
            
            print(f"Abgeschlossene Trades: {len(sells)}")
            print(f"Win Rate:              {win_rate:.2%}")
            print(f"Ø PnL pro Trade:       {avg_pnl:.2%}")
            print(f"Kumulierter PnL:       {total_pnl:.2%}")
            print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
