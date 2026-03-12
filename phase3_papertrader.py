import asyncio
import csv
import os
from datetime import datetime

# Importiere die Klassen aus den vorherigen Phasen
from phase1_oracle import DeribitOracle
from phase2_polymarket import PolymarketClient

class PaperTrader:
    def __init__(self, oracle: DeribitOracle, pm_client: PolymarketClient, market_config: dict, edge_threshold: float = 0.05, check_interval: int = 60):
        self.oracle = oracle
        self.pm_client = pm_client
        self.market_config = market_config
        self.edge_threshold = edge_threshold
        self.check_interval = check_interval
        self.csv_file = "paper_trades.csv"
        
        self._init_csv()

    def _init_csv(self):
        """Erstellt die CSV-Datei und den Header, falls sie nicht existiert."""
        if not os.path.exists(self.csv_file):
            with open(self.csv_file, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    "Timestamp", "Currency", "Target_Price", "Expiry", 
                    "Oracle_Prob", "PM_Ask", "Edge", "Action"
                ])

    def log_trade(self, oracle_prob: float, pm_ask: float, edge: float, action: str):
        """Schreibt einen virtuellen Trade in die CSV-Datei."""
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.csv_file, mode='a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([
                timestamp,
                self.market_config['currency'],
                self.market_config['target_price'],
                self.market_config['expiry_date'],
                f"{oracle_prob:.4f}",
                f"{pm_ask:.4f}",
                f"{edge:.4f}",
                action
            ])
        print(f"\n[{timestamp}] 🚨 TRADE LOGGED: {action} | Edge: {edge:.2%} | Oracle: {oracle_prob:.2%} | PM Ask: {pm_ask:.2%}\n")

    async def run(self):
        """Hauptschleife des Forward-Testers."""
        currency = self.market_config['currency']
        target_price = self.market_config['target_price']
        expiry_date = self.market_config['expiry_date']
        token_id = self.market_config['token_id']

        print(f"Starte Paper Trader für {currency} > ${target_price:,.2f} (Verfall: {expiry_date})")
        print(f"Edge Threshold: {self.edge_threshold:.2%} | Intervall: {self.check_interval}s")
        print("-" * 60)

        while True:
            try:
                # a) Oracle Fair Value abrufen
                oracle_result = await self.oracle.evaluate_target(currency, target_price, expiry_date)
                
                # b) Polymarket Preise abrufen
                pm_result = await self.pm_client.get_best_prices(token_id)
                
                if oracle_result and pm_result:
                    oracle_prob = oracle_result['probability_yes']
                    pm_ask = pm_result['best_ask']
                    
                    # c & d) Edge berechnen (Wir kaufen YES, zahlen also den Ask-Preis)
                    edge = oracle_prob - pm_ask
                    
                    current_time = datetime.utcnow().strftime('%H:%M:%S')
                    print(f"[{current_time}] Oracle: {oracle_prob:.2%} | PM Ask: {pm_ask:.2%} | Edge: {edge:.2%}")
                    
                    # e) Trade generieren, wenn Edge groß genug ist
                    if edge >= self.edge_threshold:
                        self.log_trade(oracle_prob, pm_ask, edge, "BUY_YES")
                        
            except Exception as e:
                print(f"[ERROR] Fehler im Paper Trader Loop: {e}")
                
            # Warten bis zum nächsten Check
            await asyncio.sleep(self.check_interval)

# --- Test / Ausführung ---
async def main():
    oracle = DeribitOracle()
    pm_client = PolymarketClient()
    
    # Dummy/Test-Daten für die Konfiguration
    market_config = {
        "currency": "BTC",
        "target_price": 100000.0,
        "expiry_date": "2026-12-31 08:00:00",
        "token_id": "21742633143463906290569050155826241533067272736897614950488156847949938836055"
    }
    
    # Wir setzen das Intervall für den Test auf 10 Sekunden
    trader = PaperTrader(
        oracle=oracle, 
        pm_client=pm_client, 
        market_config=market_config, 
        edge_threshold=0.05, 
        check_interval=10
    )
    
    # Task erstellen, damit wir ihn bei Cancel sauber beenden können
    trader_task = asyncio.create_task(trader.run())
    await trader_task

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Paper Trader durch Benutzer beendet (CTRL+C). System fährt herunter.")
