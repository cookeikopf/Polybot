import asyncio
import time
import json
import os
import csv
from datetime import datetime

# Importiere die Module aus den vorherigen Phasen
try:
    from phase1_oracle import DeribitOracle
    from phase2_polymarket import PolymarketClient
except ImportError:
    print("[WARNUNG] Phase 1 & 2 Module nicht gefunden. Bitte Dateinamen prüfen.")

from phase4_risk import RiskManager
from phase5_execution import PolymarketExecutor

# ==========================================
# 🚀 NEXT-LEVEL QUANT CONFIGURATION
# ==========================================
CONFIG = {
    "LIVE_MODE": False,               # Forward-Test Modus (Paper Trading)
    "ACCOUNT_BALANCE": 1000.0,        # Virtuelles Startkapital
    "MAX_TRADE_SIZE": 100.0,          # Hartes Limit pro Trade in USD
    
    # --- Dynamic Targeting ---
    "MAX_STRIKE_DISTANCE_PCT": 0.08,  # Max 8% vom aktuellen BTC Preis (Fokus auf ATM)
    "MIN_DAYS_TO_EXPIRY": 1.0,        # Keine Märkte unter 24h (Gamma-Risiko minimieren)
    
    # --- Hysteresis (Anti-Churning) ---
    "ENTRY_EDGE": 0.05,               # BUY: Wir steigen erst ab 5% echtem Edge ein
    "EXIT_EDGE": 0.01,                # SELL: Wir steigen aus, wenn der Edge unter 1% fällt (Convergence)
    
    # --- System ---
    "SLEEP_TIME": 15                  # Pause zwischen den Scans in Sekunden
}

INVENTORY_FILE = "inventory.json"
JOURNAL_FILE = "trade_journal.csv"

def load_inventory():
    if os.path.exists(INVENTORY_FILE):
        with open(INVENTORY_FILE, "r") as f:
            return json.load(f)
    return {}

def save_inventory(inventory):
    with open(INVENTORY_FILE, "w") as f:
        json.dump(inventory, f, indent=4)

def log_trade(action, token_id, strike, price, shares, edge, usd_value):
    file_exists = os.path.exists(JOURNAL_FILE)
    with open(JOURNAL_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Timestamp", "Action", "TokenID", "Strike", "Price", "Shares", "Edge", "USD_Value"])
        writer.writerow([datetime.utcnow().isoformat(), action, token_id, strike, price, shares, edge, usd_value])

async def main():
    print("===================================================")
    print("🧠 STATARB BOT - INSTITUTIONAL GRADE (V2.0)")
    print("===================================================")
    print(f"Live Mode:      {CONFIG['LIVE_MODE']}")
    print(f"Entry Edge:     {CONFIG['ENTRY_EDGE']:.2%}")
    print(f"Exit Edge:      {CONFIG['EXIT_EDGE']:.2%}")
    print(f"Max Distance:   {CONFIG['MAX_STRIKE_DISTANCE_PCT']:.2%}")
    print("===================================================")

    inventory = load_inventory()
    risk_manager = RiskManager(account_balance=CONFIG["ACCOUNT_BALANCE"], max_kelly_fraction=0.5)
    executor = PolymarketExecutor(live_mode=CONFIG["LIVE_MODE"])

    while True:
        try:
            timestamp = datetime.utcnow().strftime("%H:%M:%S")
            
            # 1. ORACLE DATEN ABRUFEN
            oracle = DeribitOracle()
            btc_price = await oracle.get_index_price("BTC")
            iv = await oracle.get_implied_volatility("BTC")
            
            if not btc_price or not iv:
                await asyncio.sleep(CONFIG["SLEEP_TIME"])
                continue
                
            print(f"\n[{timestamp}] 🌐 ORACLE UPDATE | BTC: ${btc_price:.2f} | IV: {iv:.2%}")

            # 2. MÄRKTE ABRUFEN
            pm_client = PolymarketClient()
            
            # Hole alle aktiven BTC-Märkte von Polymarket (Events Endpoint)
            markets = await pm_client.get_active_btc_markets()
            
            # Hole zusätzlich den aktuellen 15-Minuten Up/Down Markt (Game-Changer)
            m15_markets = await pm_client.get_15m_btc_market()
            if m15_markets:
                markets.extend(m15_markets)
            
            # FALLBACK: Wenn die API keine kurzfristigen Märkte liefert (Polymarket Liquiditätsproblem),
            # fügen wir manuell einen bekannten Markt hinzu, um das System am Laufen zu halten.
            if not markets:
                print(f"[{timestamp}] ⚠️ Keine dynamischen BTC-Märkte gefunden. Nutze Fallback-Markt.")
                markets = [{
                    "question": "Will bitcoin hit $1m before GTA VI?",
                    "strike": 1000000.0,
                    "days_to_expiry": 365.0, # Grobe Schätzung für GTA VI Release
                    "token_id": "21742633143463906290569050155826241533067272736897614950488156847949938836055",
                    "expiry_date_str": "2026-12-31 00:00:00"
                }]
                
            print(f"[{timestamp}] 🔍 {len(markets)} BTC-Märkte gefunden. Analysiere Edge...")
            
            for m in markets:
                strike = m.get("strike")
                days_to_expiry = m.get("days_to_expiry")
                token_id = m.get("token_id")
                is_15m = m.get("is_15m_updown", False)
                
                # --- FILTER 1: GAMMA/THETA RISIKO ---
                # 15m Märkte sind extrem kurzfristig, wir lassen sie explizit durch
                if not is_15m and days_to_expiry < CONFIG["MIN_DAYS_TO_EXPIRY"]:
                    continue
                    
                # --- FILTER 2: DYNAMIC ATM TARGETING ---
                strike_distance = abs(strike - btc_price) / btc_price
                # Wir lockern den Filter für den Fallback-Markt ($1M), damit das Script weiterläuft
                if strike_distance > CONFIG["MAX_STRIKE_DISTANCE_PCT"] and strike != 1000000.0:
                    continue

                # 3. FAIR VALUE BERECHNEN (BSM)
                # T in Jahren berechnen
                T = days_to_expiry / 365.25
                oracle_prob = oracle.calculate_probability(S=btc_price, K=strike, T=T, sigma=iv)
                
                # 4. ORDERBUCH ABRUFEN
                try:
                    prices = await pm_client.get_best_prices(token_id)
                    pm_bid = prices["best_bid"]
                    pm_ask = prices["best_ask"]
                except Exception as e:
                    print(f"Fehler beim Abrufen des Orderbuchs für {token_id}: {e}")
                    continue
                
                if not pm_bid or not pm_ask or pm_ask <= 0 or pm_bid <= 0:
                    continue

                # 5. EDGE BERECHNUNG (Realistisch mit Spread)
                # Wenn wir kaufen, zahlen wir den Ask-Preis.
                buy_edge = oracle_prob - pm_ask
                # Wenn wir verkaufen, bekommen wir den Bid-Preis.
                sell_edge = oracle_prob - pm_bid

                current_shares = inventory.get(token_id, 0)

                # ==========================================
                # 🟢 ENTRY LOGIC (BUY)
                # ==========================================
                if current_shares == 0 and buy_edge >= CONFIG["ENTRY_EDGE"]:
                    kelly_size_usd = risk_manager.calculate_kelly_size(win_prob=oracle_prob, pm_ask_price=pm_ask)
                    trade_size_usd = min(kelly_size_usd, CONFIG["MAX_TRADE_SIZE"])
                    
                    if trade_size_usd >= 5.0: # Polymarket Minimum
                        print(f"[{timestamp}] 🟢 BUY SIGNAL | Strike: ${strike} | Edge: {buy_edge:.2%} | Size: ${trade_size_usd:.2f}")
                        
                        executed_shares = executor.execute_trade("BUY", token_id, pm_ask, trade_size_usd)
                        if executed_shares > 0:
                            inventory[token_id] = executed_shares
                            save_inventory(inventory)
                            log_trade("BUY", token_id, strike, pm_ask, executed_shares, buy_edge, trade_size_usd)

                # ==========================================
                # 🔴 EXIT LOGIC (SELL / TAKE PROFIT / CUT LOSS)
                # ==========================================
                elif current_shares > 0:
                    # Wir verkaufen, wenn der Markt unseren Fair Value erreicht hat (Convergence)
                    # ODER wenn das Oracle fällt und wir im Minus-Edge sind (Stop Loss)
                    if sell_edge <= CONFIG["EXIT_EDGE"]:
                        print(f"[{timestamp}] 🎯 EXIT SIGNAL | Strike: ${strike} | Remaining Edge: {sell_edge:.2%}")
                        
                        trade_size_usd = current_shares * pm_bid
                        executed_shares = executor.execute_trade("SELL", token_id, pm_bid, trade_size_usd)
                        
                        if executed_shares > 0:
                            inventory[token_id] = 0 # Position geschlossen
                            save_inventory(inventory)
                            log_trade("SELL", token_id, strike, pm_bid, current_shares, sell_edge, trade_size_usd)

        except Exception as e:
            print(f"[FEHLER] Hauptschleife: {e}")
        
        await asyncio.sleep(CONFIG["SLEEP_TIME"])

if __name__ == "__main__":
    asyncio.run(main())
