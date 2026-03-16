import asyncio
import csv
import os
import math
from datetime import datetime, timezone
from phase1_oracle import DeribitOracle
from phase2_polymarket import PolymarketClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "raw_market_data.csv")

async def main():
    print("🚀 STARTE QUANT DATA COLLECTOR (15s Intervall)...")
    oracle = DeribitOracle()
    pm_client = PolymarketClient()

    # CSV Header initialisieren
    file_exists = os.path.isfile(DATA_FILE)
    with open(DATA_FILE, mode='a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "timestamp", "token_id", "strike", "days_to_expiry", 
                "btc_price", "iv", "oracle_prob", "pm_bid", "pm_ask", "spread_pct"
            ])

    while True:
        try:
            now = datetime.now(timezone.utc)
            timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
            
            # 1. Oracle Daten
            btc_price = await oracle.get_index_price("BTC")
            iv = await oracle.get_implied_volatility("BTC")
            if not btc_price or not iv:
                print(f"[{timestamp}] ⚠️ Warte auf Deribit-Daten...")
                await asyncio.sleep(15)
                continue
                
            # 2. Polymarket Märkte
            markets = await pm_client.get_active_btc_markets()
            
            rows_to_write = []
            for m in markets:
                token_id = m["token_id"]
                strike = m["strike"]
                days_to_expiry = m["days_to_expiry"]
                
                # Ignoriere abgelaufene oder extrem kurze Märkte (< 1 Minute)
                if days_to_expiry < 0.0007:
                    continue
                    
                T = days_to_expiry / 365.25
                oracle_prob = oracle.calculate_probability(S=btc_price, K=strike, T=T, sigma=iv)
                
                try:
                    prices = await pm_client.get_best_prices(token_id)
                    pm_bid = prices["best_bid"]
                    pm_ask = prices["best_ask"]
                except Exception as e:
                    continue # Skip bei 404 oder leeren Orderbüchern
                    
                if pm_bid <= 0 or pm_ask <= 0:
                    continue
                    
                spread_pct = (pm_ask - pm_bid) / pm_ask
                
                rows_to_write.append([
                    timestamp, token_id, strike, round(days_to_expiry, 4),
                    round(btc_price, 2), round(iv, 4), round(oracle_prob, 4),
                    round(pm_bid, 4), round(pm_ask, 4), round(spread_pct, 4)
                ])
            
            # Batch Write für Performance
            if rows_to_write:
                with open(DATA_FILE, mode='a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerows(rows_to_write)
                print(f"[{timestamp}] ✅ {len(rows_to_write)} Märkte geloggt. BTC: ${btc_price:.2f} | IV: {iv:.2%}")
                
        except Exception as e:
            print(f"[{timestamp}] ⚠️ Fehler im Collector-Loop: {e}")
            
        await asyncio.sleep(15)

if __name__ == "__main__":
    asyncio.run(main())
