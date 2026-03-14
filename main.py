import asyncio
import time
import json
import os
import csv
import math
from datetime import datetime, timezone

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
    "ACCOUNT_BALANCE": 100.0,         # Virtuelles Startkapital (Reset auf 100)
    "MAX_TRADE_SIZE": 100.0,          # Hartes Limit pro Trade in USD
    
    # --- Dynamic Targeting ---
    "MAX_STRIKE_DISTANCE_PCT": 0.08,  # Max 8% vom aktuellen BTC Preis (Fokus auf ATM)
    "MIN_DAYS_TO_EXPIRY": 0.25,       # Erhöht auf 0.25 (6 Stunden) -> Fokus auf Daily Markets, keine 15m mehr!
    "MAX_DAILY_MOVE_PCT": 0.04,       # Erwartete max. BTC Bewegung pro Tag (4%) - skaliert mit Wurzel der Zeit
    "MIN_PRICE": 0.10,                # Keine "Lotto-Tickets" unter 10 Cent kaufen
    "MAX_PRICE": 0.90,                # Keine sicheren Dinger über 90 Cent kaufen (Capital Tie-up)
    
    # --- Hysteresis (Anti-Churning) ---
    "ENTRY_EDGE": 0.08,               # BUY: Erhöht auf 8% für höhere Win-Rate (Qualität > Quantität)
    "EXIT_EDGE": 0.01,                # SELL: Wir steigen aus, wenn der Edge unter 1% fällt (Convergence)
    
    # --- System ---
    "SLEEP_TIME": 15                  # Pause zwischen den Scans in Sekunden
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INVENTORY_FILE = os.path.join(BASE_DIR, "inventory.json")
JOURNAL_FILE = os.path.join(BASE_DIR, "trade_journal.csv")

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
        writer.writerow([datetime.now(timezone.utc).isoformat(), action, token_id, strike, price, shares, edge, usd_value])

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
    risk_manager = RiskManager(initial_bankroll=CONFIG["ACCOUNT_BALANCE"], kelly_multiplier=0.5, max_bet_size=CONFIG["MAX_TRADE_SIZE"])
    executor = PolymarketExecutor(live_mode=CONFIG["LIVE_MODE"])

    while True:
        try:
            timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            
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
            
            # 15m Märkte wurden deaktiviert, da wir uns auf Daily Markets fokussieren
            # m15_markets = await pm_client.get_15m_btc_market()
            # if m15_markets:
            #     markets.extend(m15_markets)
            
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
                needs_current_price = m.get("needs_current_price", False)
                
                # Wenn es ein reiner Up/Down Markt ohne festen Strike ist,
                # ist der Strike-Preis der aktuelle BTC-Preis zum Zeitpunkt der Markterstellung/Betrachtung.
                if needs_current_price:
                    strike = btc_price
                
                # --- FILTER 1: GAMMA/THETA RISIKO ---
                # Wir filtern alle Märkte, die zu nah an der Expiry sind, AUSSER wir halten bereits Positionen!
                # Fokus liegt jetzt auf Daily Markets (MIN_DAYS_TO_EXPIRY = 0.25)
                
                pos_data = inventory.get(token_id, 0)
                if isinstance(pos_data, dict):
                    current_shares = pos_data.get("shares", 0)
                    entry_price = pos_data.get("entry_price", 0)
                else:
                    current_shares = pos_data
                    entry_price = 0

                if current_shares == 0 and days_to_expiry < CONFIG["MIN_DAYS_TO_EXPIRY"]:
                    continue
                    
                # --- FILTER 2: DYNAMIC ATM TARGETING ---
                strike_distance = abs(strike - btc_price) / btc_price
                # Wir lockern den Filter für den Fallback-Markt ($1M), damit das Script weiterläuft
                if strike_distance > CONFIG["MAX_STRIKE_DISTANCE_PCT"] and strike != 1000000.0:
                    continue

                # --- FILTER 3: GAMMA RISK (SQUARE ROOT OF TIME) ---
                # Volatilität skaliert nicht linear, sondern mit der Wurzel der Zeit!
                # Das erlaubt dynamische Anpassung für 15m, 1h, 12h und Daily Markets.
                if strike != 1000000.0:
                    max_allowed_distance = math.sqrt(days_to_expiry) * CONFIG["MAX_DAILY_MOVE_PCT"]
                    if strike_distance > max_allowed_distance:
                        # print(f"[{timestamp}] ⚠️ GAMMA RISK REJECT | Strike: ${strike} | Dist: {strike_distance:.2%} | Max Allowed: {max_allowed_distance:.2%} | Days: {days_to_expiry:.4f}")
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
                    if "404" not in str(e):
                        print(f"[{timestamp}] ⚠️ Orderbuch-Fehler für {token_id[:8]}... : {e}")
                    continue
                
                if not pm_bid or not pm_ask or pm_ask <= 0 or pm_bid <= 0:
                    continue

                # 5. EDGE BERECHNUNG (Realistisch mit Spread)
                # Wenn wir kaufen, zahlen wir den Ask-Preis.
                buy_edge = oracle_prob - pm_ask
                # Wenn wir verkaufen, bekommen wir den Bid-Preis.
                sell_edge = oracle_prob - pm_bid

                # ==========================================
                # 🟢 ENTRY LOGIC (BUY)
                # ==========================================
                if current_shares == 0 and buy_edge >= CONFIG["ENTRY_EDGE"]:
                    # Anti-Lottery Filter: Keine Optionen unter MIN_PRICE oder über MAX_PRICE kaufen
                    if pm_ask < CONFIG["MIN_PRICE"] or pm_ask > CONFIG["MAX_PRICE"]:
                        continue

                    kelly_result = risk_manager.calculate_position_size(true_prob=oracle_prob, market_price=pm_ask, is_crypto=True)
                    kelly_size_usd = kelly_result.get("bet_size", 0.0)
                    trade_size_usd = min(kelly_size_usd, CONFIG["MAX_TRADE_SIZE"])
                    
                    if trade_size_usd >= 5.0: # Polymarket Minimum
                        print(f"[{timestamp}] 🟢 BUY SIGNAL | Strike: ${strike} | Edge: {buy_edge:.2%} | Size: ${trade_size_usd:.2f}")
                        
                        executed_shares = executor.execute_trade("BUY", token_id, pm_ask, trade_size_usd)
                        if executed_shares > 0:
                            inventory[token_id] = {
                                "shares": executed_shares,
                                "entry_price": pm_ask,
                                "strike": strike
                            }
                            save_inventory(inventory)
                            log_trade("BUY", token_id, strike, pm_ask, executed_shares, buy_edge, trade_size_usd)

                # ==========================================
                # 🔴 EXIT LOGIC (SELL / TAKE PROFIT / CUT LOSS)
                # ==========================================
                elif current_shares > 0:
                    # Wir verkaufen, wenn der Markt unseren Fair Value erreicht hat (Convergence)
                    is_convergence_exit = sell_edge <= CONFIG["EXIT_EDGE"]
                    
                    # --- DYNAMIC STOP LOSS ---
                    # Statt starrer 50%, nutzen wir ein dynamisches Modell:
                    # 1. Wenn die Option extrem billig war (< $0.15), geben wir ihr mehr Raum (70% Drop erlaubt), da kleine Cent-Schwankungen sonst sofort ausstoppen.
                    # 2. Wenn die Option teurer war, greift ein 40% Stop-Loss.
                    # 3. Time-Stop: Wenn der Edge massiv negativ wird (<-15%) UND wir nah an der Expiry sind (< 2 Stunden), cutten wir.
                    is_stop_loss = False
                    if entry_price > 0:
                        if entry_price < 0.15:
                            is_stop_loss = (pm_bid <= entry_price * 0.30) # 70% Drop
                        else:
                            is_stop_loss = (pm_bid <= entry_price * 0.60) # 40% Drop
                            
                        # Time-based Edge Stop
                        if sell_edge < -0.15 and days_to_expiry < (2.0 / 24.0):
                            is_stop_loss = True
                            
                        # HARD TIME STOP: Niemals durch die Expiration halten (Lotterie).
                        # Wenn weniger als ~30 Minuten (0.02 Tage) übrig sind, verkaufen wir.
                        if days_to_expiry < 0.02:
                            is_stop_loss = True

                    if is_convergence_exit or is_stop_loss:
                        if is_stop_loss:
                            print(f"[{timestamp}] 🛑 DYNAMIC STOP LOSS | Strike: ${strike} | Entry: ${entry_price:.2f} | Current: ${pm_bid:.2f} | Edge: {sell_edge:.2%}")
                        else:
                            print(f"[{timestamp}] 🎯 CONVERGENCE EXIT | Strike: ${strike} | Remaining Edge: {sell_edge:.2%}")
                        
                        trade_size_usd = current_shares * pm_bid
                        executed_shares = executor.execute_trade("SELL", token_id, pm_bid, trade_size_usd)
                        
                        if executed_shares > 0:
                            if token_id in inventory:
                                del inventory[token_id] # Position komplett aus dem Dictionary entfernen
                            save_inventory(inventory)
                            log_trade("SELL", token_id, strike, pm_bid, current_shares, sell_edge, trade_size_usd)

            # ==========================================
            # 🧹 CLEANUP: ABGELAUFENE / AUFGELÖSTE MÄRKTE
            # ==========================================
            active_token_ids = {m.get("token_id") for m in markets}
            tokens_to_remove = []
            
            for t_id, pos_data in inventory.items():
                if isinstance(pos_data, dict):
                    shares = pos_data.get("shares", 0)
                    strike = pos_data.get("strike", 0)
                else:
                    shares = pos_data
                    strike = 0
                    
                if shares > 0 and t_id not in active_token_ids:
                    print(f"[{timestamp}] 💀 MARKT ABGELAUFEN / AUFGELÖST | Token: {t_id} | Shares: {shares}")
                    # Logge als Totalverlust (Preis = 0.0)
                    log_trade("LOSS_EXPIRED", t_id, strike, 0.0, shares, 0.0, 0.0)
                    tokens_to_remove.append(t_id)
                    
            for t_id in tokens_to_remove:
                del inventory[t_id]
                
            if tokens_to_remove:
                save_inventory(inventory)

        except Exception as e:
            print(f"[FEHLER] Hauptschleife: {e}")
        
        await asyncio.sleep(CONFIG["SLEEP_TIME"])

if __name__ == "__main__":
    asyncio.run(main())
