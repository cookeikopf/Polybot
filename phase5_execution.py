import os
import time
from dotenv import load_dotenv

# Versuche den offiziellen Polymarket Client zu importieren
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False

load_dotenv()

class PolymarketExecutor:
    def __init__(self, live_mode: bool = False):
        self.live_mode = live_mode
        self.private_key = os.getenv("PRIVATE_KEY")
        self.host = os.getenv("POLYMARKET_HOST", "https://clob.polymarket.com")
        self.chain_id = int(os.getenv("POLYMARKET_CHAIN_ID", "137")) # 137 = Polygon Mainnet
        self.client = None

        if self.live_mode:
            if not CLOB_AVAILABLE:
                raise ImportError("py_clob_client ist nicht installiert! Bitte 'pip install py_clob_client' ausführen.")
            if not self.private_key:
                raise ValueError("PRIVATE_KEY fehlt in der .env Datei für den Live-Modus!")
            
            print("[EXECUTION] Initialisiere Polymarket CLOB Client (LIVE MODE)...")
            self.client = ClobClient(self.host, key=self.private_key, chain_id=self.chain_id)
            # API Credentials ableiten (Standard-Prozess bei Polymarket)
            self.client.set_api_creds(self.client.create_or_derive_api_creds())
            print("[EXECUTION] ⚠️ LIVE TRADING AKTIV ⚠️")
        else:
            print("[EXECUTION] Paper Trading Modus aktiv.")

    def execute_trade(self, action: str, token_id: str, price: float, size_usd: float) -> float:
        """
        Führt einen Trade aus (Paper oder Live).
        Gibt die Anzahl der gehandelten Shares zurück.
        """
        shares = size_usd / price

        if not self.live_mode:
            # Paper Trading Logik
            print(f"[PAPER TRADE] {action} {shares:.2f} Shares von Token {token_id} zu ${price:.4f}")
            time.sleep(0.5) # Simuliere Latenz
            return shares

        # LIVE TRADING LOGIK (Gamma API / CLOB)
        print(f"[LIVE TRADE] Sende {action} Order an Polymarket CLOB...")
        try:
            side = BUY if action.upper() == "BUY" else SELL
            
            # FOK (Fill or Kill) Order erstellen, um Teilausführungen zu vermeiden
            order_args = OrderArgs(
                price=price,
                size=shares,
                side=side,
                token_id=token_id
            )
            
            signed_order = self.client.create_order(order_args)
            response = self.client.post_order(signed_order, OrderType.FOK)
            
            if response and response.get("success"):
                print(f"[LIVE TRADE ERFOLGREICH] {shares:.2f} Shares zu ${price:.4f} gehandelt. OrderID: {response.get('orderID')}")
                return shares
            else:
                print(f"[LIVE TRADE ABGELEHNT] Polymarket Response: {response}")
                return 0.0
                
        except Exception as e:
            print(f"[LIVE TRADE FEHLER] {e}")
            return 0.0
