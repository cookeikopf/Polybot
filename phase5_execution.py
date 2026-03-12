import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType

class PolymarketExecutor:
    def __init__(self, live_mode: bool = False):
        self.live_mode = live_mode
        
        # Lade Umgebungsvariablen
        self.pk = os.getenv("PK")
        self.chain_id = int(os.getenv("CHAIN_ID", "137"))
        self.api_key = os.getenv("CLOB_API_KEY")
        self.api_secret = os.getenv("CLOB_SECRET")
        self.api_passphrase = os.getenv("CLOB_PASS_PHRASE")
        self.host = "https://clob.polymarket.com"
        
        # Initialisiere den ClobClient
        if self.api_key and self.api_secret and self.api_passphrase and self.pk:
            self.client = ClobClient(
                self.host,
                key=self.api_key,
                secret=self.api_secret,
                passphrase=self.api_passphrase,
                chain_id=self.chain_id,
                signature_type=1,  # 1 für EOA (Externally Owned Account)
                funder=self.pk     # Private Key für die Signatur der Order
            )
        else:
            self.client = None
            if self.live_mode:
                print("\n[WARNUNG] Fehlende API Credentials im .env File. Live-Modus wird fehlschlagen.")

    def execute_trade(self, token_id: str, price: float, trade_size_usd: float, side: str = "BUY"):
        """
        Führt den Trade (BUY oder SELL) auf Polymarket aus (oder simuliert ihn im Paper-Trading-Modus).
        """
        # 1. Anzahl der Shares berechnen (Polymarket unterstützt max 2 Nachkommastellen)
        shares = round(trade_size_usd / price, 2)
        
        if shares <= 0:
            print("Trade Size zu klein (0 Shares). Abbruch.")
            return

        # 2. Order Argumente vorbereiten
        order_args = OrderArgs(
            price=price,
            size=shares,
            side=side,
            token_id=token_id
        )

        # ANSI Farbcodes für die Konsole
        YELLOW = '\033[93m'
        GREEN = '\033[92m'
        RESET = '\033[0m'

        # 3. Paper Trading Modus (live_mode = False)
        if not self.live_mode:
            print(f"\n{YELLOW}[PAPER TRADE - EXECUTION WÜRDE STARTEN]{RESET}")
            print(f"{YELLOW}Aktion:        {side}{RESET}")
            print(f"{YELLOW}Token ID:      {token_id[:15]}...{RESET}")
            print(f"{YELLOW}Preis:         ${price:.2f}{RESET}")
            print(f"{YELLOW}Shares:        {shares:.2f}{RESET}")
            print(f"{YELLOW}Gesamtvolumen: ${trade_size_usd:.2f}{RESET}")
            return

        # 4. Live Execution Modus (live_mode = True)
        print(f"\n{GREEN}[LIVE TRADE - SENDE ORDER AN POLYMARKET]{RESET}")
        try:
            if not self.client:
                raise ValueError("ClobClient ist nicht initialisiert. Überprüfe die .env Datei.")

            # Order erstellen und kryptografisch signieren (Fill-Or-Kill)
            signed_order = self.client.create_order(
                order_args, 
                OrderType.FOK
            )
            
            # Order an das Orderbuch senden
            response = self.client.post_order(signed_order)
            
            print(f"{GREEN}Order erfolgreich gesendet!{RESET}")
            print(f"{GREEN}API Response: {response}{RESET}")
            
        except Exception as e:
            print(f"\n[FEHLER] Fehler bei der Live-Ausführung: {e}")

# --- Test / Ausführung ---
if __name__ == "__main__":
    # Lädt die .env Datei aus dem aktuellen Verzeichnis
    load_dotenv()
    
    # Instanziere den Executor im sicheren Paper-Trading-Modus
    executor = PolymarketExecutor(live_mode=False)
    
    # Fiktiver Trade aus Szenario A (Phase 4)
    test_token = "21742633143463906290569050155826241533067272736897614950488156847949938836055"
    pm_ask = 0.50
    trade_size = 65.00  # 65 USDC
    
    executor.execute_trade(
        token_id=test_token, 
        pm_ask_price=pm_ask, 
        trade_size_usd=trade_size
    )
