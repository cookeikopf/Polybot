import os
import time
import json
from typing import Dict, Optional
from dotenv import load_dotenv

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL
    from py_clob_client.exceptions import PolyApiException
    from eth_account import Account
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False

load_dotenv()

class PolymarketExecutor:
    """
    Phase 5: Live Execution Module
    Integriert Web3, Private Key Management und die Polymarket Gamma (CLOB) API.
    Setzt Limit-Orders (FOK/GTC) auf Polygon.
    """
    def __init__(self, live_mode: bool = False, rpc_url: str = "https://polygon-rpc.com"):
        self.live_mode = live_mode
        self.private_key = os.getenv("PRIVATE_KEY")
        self.host = os.getenv("POLYMARKET_HOST", "https://clob.polymarket.com")
        self.chain_id = int(os.getenv("POLYMARKET_CHAIN_ID", "137")) # 137 = Polygon Mainnet
        self.rpc_url = os.getenv("RPC_URL", rpc_url)
        self.client: Optional[ClobClient] = None
        self.creds_file = "pm_api_creds.json"

        if self.live_mode:
            self._initialize_live_client()
        else:
            print("[EXECUTION] 📄 Paper Trading Modus aktiv. Trades werden nur simuliert.")

    def _initialize_live_client(self):
        if not CLOB_AVAILABLE:
            raise ImportError("py_clob_client oder eth_account ist nicht installiert! Bitte 'pip install py_clob_client eth_account' ausführen.")
        if not self.private_key:
            raise ValueError("PRIVATE_KEY fehlt in der .env Datei für den Live-Modus!")
        
        print("[EXECUTION] 🚀 Initialisiere Polymarket CLOB Client (LIVE MODE)...")
        
        # Public Address ableiten
        account = Account.from_key(self.private_key)
        public_address = account.address
        print(f"[EXECUTION] Wallet Address: {public_address}")

        # ClobClient initialisieren
        self.client = ClobClient(
            self.host, 
            key=self.private_key, 
            chain_id=self.chain_id,
            signature_type=1, # EOA Signature (Externally Owned Account)
            funder=public_address
        )

        # L2 API Credentials laden oder neu ableiten
        self._setup_api_credentials()
        
        print("[EXECUTION] ⚠️ LIVE TRADING AKTIV ⚠️ Verbindung zu Polymarket hergestellt.")

    def _setup_api_credentials(self):
        """
        Lädt bestehende L2 Credentials oder signiert neue via L1 Private Key.
        Verhindert, dass bei jedem Neustart eine neue Signatur erzeugt wird.
        """
        if os.path.exists(self.creds_file):
            try:
                with open(self.creds_file, "r") as f:
                    creds = json.load(f)
                self.client.set_api_creds(creds)
                print("[EXECUTION] L2 API Credentials erfolgreich geladen.")
                return
            except Exception as e:
                print(f"[EXECUTION] Fehler beim Laden der Credentials: {e}. Erzeuge neue...")

        print("[EXECUTION] Erzeuge neue L2 API Credentials (benötigt L1 Signatur)...")
        creds = self.client.create_or_derive_api_creds()
        self.client.set_api_creds(creds)
        
        with open(self.creds_file, "w") as f:
            json.dump(creds, f)
        print("[EXECUTION] Neue L2 API Credentials gespeichert.")

    def execute_trade(self, action: str, token_id: str, price: float, size_usd: float) -> float:
        """
        Führt einen Trade aus.
        action: "BUY" oder "SELL"
        token_id: Die Polymarket Asset ID
        price: Der Limit-Preis (z.B. 0.45)
        size_usd: Die Positionsgröße in USD
        
        Gibt die Anzahl der erfolgreich gehandelten Shares zurück.
        """
        # Shares berechnen (Polymarket nutzt Shares als Basis-Einheit)
        shares = round(size_usd / price, 2)
        
        if shares < 5.0:
            print(f"[EXECUTION] Trade zu klein ({shares} Shares). Minimum ist ~5.0. Abbruch.")
            return 0.0

        if not self.live_mode:
            print(f"[PAPER TRADE] {action} {shares:.2f} Shares von Token {token_id} zu ${price:.4f} (Total: ${size_usd:.2f})")
            time.sleep(0.5)
            return shares

        print(f"[LIVE TRADE] Sende {action} Order an Polymarket CLOB...")
        try:
            side = BUY if action.upper() == "BUY" else SELL
            
            # FOK (Fill or Kill) garantiert, dass wir entweder die volle Size zum Limit-Preis bekommen oder nichts.
            # Alternativ: GTC (Good Till Cancelled) als Maker. Wir nutzen hier FOK für sofortige Arbitrage-Execution.
            order_args = OrderArgs(
                price=price,
                size=shares,
                side=side,
                token_id=token_id
            )
            
            # Order lokal signieren
            signed_order = self.client.create_order(order_args)
            
            # Order an das Orderbook senden
            response = self.client.post_order(signed_order, OrderType.FOK)
            
            if response and response.get("success"):
                order_id = response.get('orderID')
                print(f"[LIVE TRADE ERFOLGREICH] {action} {shares:.2f} Shares zu ${price:.4f}. OrderID: {order_id}")
                return shares
            else:
                error_msg = response.get("errorMsg", "Unbekannter Fehler")
                print(f"[LIVE TRADE ABGELEHNT] Polymarket Response: {error_msg}")
                return 0.0
                
        except PolyApiException as e:
            print(f"[LIVE TRADE API FEHLER] {e}")
            return 0.0
        except Exception as e:
            print(f"[LIVE TRADE KRITISCHER FEHLER] {e}")
            return 0.0
