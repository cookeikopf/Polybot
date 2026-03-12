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

    # Zentrale Konfiguration
    config = {
        "BANKROLL": 1000.0,
        "LIVE_MODE": False,  # Standardmäßig auf Sicherheit (Paper Trading)
        "CHECK_INTERVAL": 60, # Sekunden
        "TARGET_CURRENCY": "BTC",
        "TARGET_PRICE": 100000.0,
        "EXPIRY_DATE": "2026-12-31 08:00:00",
        "PM_TOKEN_ID": "21742633143463906290569050155826241533067272736897614950488156847949938836055" # Beispiel Token ID
    }

    # Instanziierung der 5 Klassen
    oracle = DeribitOracle()
    pm_client = PolymarketClient()
    
    # Für den Logger (Phase 3) benötigen wir die market_config
    market_config = {
        "currency": config["TARGET_CURRENCY"],
        "target_price": config["TARGET_PRICE"],
        "expiry_date": config["EXPIRY_DATE"],
        "token_id": config["PM_TOKEN_ID"]
    }
    logger = PaperTrader(oracle, pm_client, market_config) # Wir nutzen hier nur die log_trade Methode
    
    risk_manager = RiskManager()
    executor = PolymarketExecutor(live_mode=config["LIVE_MODE"])

    print("="*50)
    print("🚀 STATARB TRADING BOT ORCHESTRATOR 🚀")
    print("="*50)
    print(f"Target:      {config['TARGET_CURRENCY']} > ${config['TARGET_PRICE']:,.2f}")
    print(f"Expiry:      {config['EXPIRY_DATE']}")
    print(f"Live Mode:   {config['LIVE_MODE']}")
    print(f"Bankroll:    ${config['BANKROLL']:,.2f}")
    print("="*50)

    # Asynchrone Endlosschleife
    while True:
        try:
            # Schritt 2: Oracle-Ergebnis holen (Fair Value)
            oracle_res = await oracle.evaluate_target(
                config["TARGET_CURRENCY"], 
                config["TARGET_PRICE"], 
                config["EXPIRY_DATE"]
            )
            
            # Schritt 3: Polymarket-Preise holen
            pm_res = await pm_client.get_best_prices(config["PM_TOKEN_ID"])
            
            if oracle_res and pm_res:
                oracle_prob = oracle_res['probability_yes']
                pm_ask = pm_res['best_ask']
                
                # Schritt 4: Aktuelle Marktlage loggen
                timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{timestamp}] Oracle Prob: {oracle_prob:.2%} | PM Ask: {pm_ask:.2%}")
                
                # Schritt 5: RiskManager berechnet die Trade Size
                trade_size_usd = risk_manager.calculate_position_size(
                    bankroll=config["BANKROLL"],
                    oracle_prob=oracle_prob,
                    pm_ask=pm_ask
                )
                
                # Schritt 6: Ausführung, wenn ein Edge existiert und Trade Size > 0
                if trade_size_usd > 0:
                    edge = oracle_prob - pm_ask
                    print(f"\n[{timestamp}] 🚨 EDGE DETECTED ({edge:+.2%})! Trade Size: ${trade_size_usd:.2f}")
                    
                    # Executor aufrufen (Phase 5)
                    executor.execute_trade(
                        token_id=config["PM_TOKEN_ID"],
                        pm_ask_price=pm_ask,
                        trade_size_usd=trade_size_usd
                    )
                    
                    # Trade in CSV loggen (Phase 3)
                    logger.log_trade(oracle_prob, pm_ask, edge, "BUY_YES")
                    
                    # Cooldown nach einem Trade (1 Stunde = 3600 Sekunden)
                    print(f"[{timestamp}] Trade ausgeführt. Gehe in 1-stündigen Cooldown...\n")
                    await asyncio.sleep(3600)
                    continue # Überspringt den normalen CHECK_INTERVAL Sleep
                    
        except Exception as e:
            # Schritt 1: Try/Except für Stabilität (z.B. bei API Timeouts)
            print(f"[FEHLER] Main Loop Exception: {e}")
            
        # Schritt 7: Warten bis zum nächsten Check
        await asyncio.sleep(config["CHECK_INTERVAL"])

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Bot durch Benutzer beendet (CTRL+C). System fährt sicher herunter.")
