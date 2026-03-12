import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv

# Importiere die 5 Phasen-Module
from phase1_oracle import DeribitOracle
from phase2_polymarket import PolymarketClient
from phase3_papertrader import PaperTrader
from phase4_riskmanager import RiskManager
from phase5_execution import PolymarketExecutor

async def main():
    # Lade Umgebungsvariablen für die API Keys
    load_dotenv()

    # Zentrale Konfiguration für Diversifikation und Market Making
    config = {
        "BANKROLL": 1000.0,
        "LIVE_MODE": False,  # Standardmäßig auf Sicherheit (Paper Trading)
        "CHECK_INTERVAL": 60, # Sekunden
        "MIN_EDGE": 0.02,     # Minimaler Edge (2%), um einen Trade auszulösen
        "MARKETS": [
            {
                "CURRENCY": "BTC",
                "TARGET_PRICE": 100000.0,
                "EXPIRY_DATE": "2026-12-31 08:00:00",
                "KEYWORD": "Bitcoin above $100,000 in 2026"
            },
            {
                "CURRENCY": "ETH",
                "TARGET_PRICE": 4000.0,
                "EXPIRY_DATE": "2026-12-31 08:00:00",
                "KEYWORD": "Ethereum above $4,000 in 2026"
            }
        ]
    }

    # Instanziierung der Klassen
    oracle = DeribitOracle()
    pm_client = PolymarketClient()
    risk_manager = RiskManager()
    executor = PolymarketExecutor(live_mode=config["LIVE_MODE"])

    print("="*50)
    print("🚀 STATARB TRADING BOT (MULTI-MARKET) 🚀")
    print("="*50)
    print("Suche nach passenden Märkten auf Polymarket...")
    
    # Cache für die gefundenen Token-IDs und Logger
    active_markets = []
    
    for m in config["MARKETS"]:
        try:
            market_info = await pm_client.find_market_token(m["KEYWORD"])
            m["TOKEN_ID"] = market_info["token_id"]
            
            # Logger für jeden Markt initialisieren
            market_config = {
                "currency": m["CURRENCY"],
                "target_price": m["TARGET_PRICE"],
                "expiry_date": m["EXPIRY_DATE"],
                "token_id": m["TOKEN_ID"]
            }
            m["LOGGER"] = PaperTrader(oracle, pm_client, market_config)
            
            active_markets.append(m)
            print(f"✅ Markt gefunden: '{market_info['question']}' -> ID: {m['TOKEN_ID'][:8]}...")
        except Exception as e:
            print(f"❌ Markt nicht gefunden für '{m['KEYWORD']}': {e}")

    if not active_markets:
        print("Keine aktiven Märkte gefunden. Beende Bot.")
        return

    print("="*50)
    print(f"Live Mode:   {config['LIVE_MODE']}")
    print(f"Bankroll:    ${config['BANKROLL']:,.2f}")
    print(f"Min Edge:    {config['MIN_EDGE']:.2%}")
    print("="*50)

    # Asynchrone Endlosschleife
    while True:
        try:
            for m in active_markets:
                # Schritt 1: Oracle-Ergebnis holen (Fair Value)
                oracle_res = await oracle.evaluate_target(m["CURRENCY"], m["TARGET_PRICE"], m["EXPIRY_DATE"])
                
                # Schritt 2: Polymarket-Preise holen (Bid und Ask)
                pm_res = await pm_client.get_best_prices(m["TOKEN_ID"])
                
                if oracle_res and pm_res:
                    oracle_prob = oracle_res['probability_yes']
                    pm_ask = pm_res['best_ask']
                    pm_bid = pm_res['best_bid']
                    
                    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{timestamp}] {m['CURRENCY']} | Oracle: {oracle_prob:.2%} | PM Bid: {pm_bid:.2%} | PM Ask: {pm_ask:.2%}")
                    
                    # --- BUY LOGIC (Unterbewertet) ---
                    buy_edge = oracle_prob - pm_ask
                    if buy_edge > config["MIN_EDGE"]:
                        trade_size_usd = risk_manager.calculate_position_size(config["BANKROLL"], oracle_prob, pm_ask)
                        if trade_size_usd > 0:
                            print(f"\n[{timestamp}] 🟢 BUY EDGE DETECTED ({buy_edge:+.2%}) für {m['CURRENCY']}! Size: ${trade_size_usd:.2f}")
                            executor.execute_trade(m["TOKEN_ID"], pm_ask, trade_size_usd, side="BUY")
                            m["LOGGER"].log_trade(oracle_prob, pm_ask, buy_edge, "BUY_YES")
                            await asyncio.sleep(5) # Kurzer Cooldown nach Trade
                            continue
                            
                    # --- SELL LOGIC (Überbewertet) ---
                    sell_edge = pm_bid - oracle_prob
                    if sell_edge > config["MIN_EDGE"]:
                        # Hinweis: Im Live-Modus würde die API die Order ablehnen, wenn wir keine Shares haben.
                        # Für ein perfektes System müsste hier der aktuelle Share-Bestand abgefragt werden.
                        # Wir berechnen die Size basierend auf dem Edge, als würden wir "Short" gehen oder Gewinne mitnehmen.
                        trade_size_usd = risk_manager.calculate_position_size(config["BANKROLL"], pm_bid, oracle_prob) # Parameter getauscht für Sell-Risk
                        if trade_size_usd > 0:
                            print(f"\n[{timestamp}] 🔴 SELL EDGE DETECTED ({sell_edge:+.2%}) für {m['CURRENCY']}! Size: ${trade_size_usd:.2f}")
                            executor.execute_trade(m["TOKEN_ID"], pm_bid, trade_size_usd, side="SELL")
                            m["LOGGER"].log_trade(oracle_prob, pm_bid, sell_edge, "SELL_YES")
                            await asyncio.sleep(5) # Kurzer Cooldown nach Trade
                            continue
                            
        except Exception as e:
            print(f"[FEHLER] Main Loop Exception: {e}")
            
        # Warten bis zum nächsten Check-Zyklus
        await asyncio.sleep(config["CHECK_INTERVAL"])

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Bot durch Benutzer beendet (CTRL+C). System fährt sicher herunter.")
