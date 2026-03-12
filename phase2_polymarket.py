import asyncio
import aiohttp

class PolymarketClient:
    def __init__(self):
        self.base_url = "https://clob.polymarket.com"
        self.gamma_url = "https://gamma-api.polymarket.com"

    async def find_market_token(self, keyword: str) -> dict:
        """
        Sucht in der Polymarket Gamma API nach aktiven Märkten, die das Keyword enthalten,
        und gibt die Token-ID für das "YES" Outcome zurück.
        """
        # Wir suchen nach aktiven Märkten
        url = f"{self.gamma_url}/markets?limit=100&active=true&closed=false"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        markets = await response.json()
                        
                        # Suche nach dem Keyword in der Frage
                        for market in markets:
                            question = market.get("question", "")
                            if keyword.lower() in question.lower():
                                outcomes = market.get("outcomes", [])
                                token_ids = market.get("clobTokenIds", [])
                                
                                # Finde den Index für "Yes"
                                try:
                                    yes_index = outcomes.index("Yes")
                                    yes_token_id = token_ids[yes_index]
                                    
                                    return {
                                        "question": question,
                                        "token_id": yes_token_id,
                                        "market_slug": market.get("slug")
                                    }
                                except ValueError:
                                    continue # "Yes" nicht gefunden, nächster Markt
                                    
                        raise ValueError(f"Kein aktiver Markt mit dem Keyword '{keyword}' gefunden.")
                    else:
                        raise ValueError(f"Gamma API Fehler: {response.status}")
            except Exception as e:
                raise Exception(f"Fehler bei der Marktsuche: {e}")

    async def get_orderbook(self, token_id: str) -> dict:
        """
        Ruft das Orderbuch für eine spezifische Token-ID über die Polymarket CLOB API ab.
        """
        url = f"{self.base_url}/book?token_id={token_id}"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error_text = await response.text()
                        raise ValueError(f"API Fehler ({response.status}): {error_text}")
            except asyncio.TimeoutError:
                raise TimeoutError(f"Timeout beim Abrufen des Orderbuchs für Token {token_id}")
            except Exception as e:
                raise Exception(f"Netzwerkfehler: {e}")

    async def get_best_prices(self, token_id: str) -> dict:
        """
        Wertet das Orderbuch aus und liefert den besten Bid, Ask und den Spread.
        """
        orderbook = await self.get_orderbook(token_id)
        
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])
        
        # Falls das Orderbuch auf einer Seite leer ist, setzen wir Fallbacks
        if not bids:
            best_bid = 0.0
        else:
            # Bids parsen und den höchsten Preis finden
            best_bid = max(float(bid["price"]) for bid in bids)
            
        if not asks:
            best_ask = 1.0  # Max Preis auf Polymarket ist 1.0 ($1)
        else:
            # Asks parsen und den niedrigsten Preis finden
            best_ask = min(float(ask["price"]) for ask in asks)
            
        spread = best_ask - best_bid
        
        return {
            "token_id": token_id,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread
        }

# --- Test / Ausführung ---
async def main():
    client = PolymarketClient()
    
    # Beispiel Token-ID (YES-Token für einen fiktiven oder realen Markt)
    # Polymarket Token-IDs sind große Integer als Strings
    test_token_id = "21742633143463906290569050155826241533067272736897614950488156847949938836055"
    
    print(f"Rufe Orderbuch für Token {test_token_id[:10]}... ab")
    
    try:
        prices = await client.get_best_prices(test_token_id)
        
        print("\n--- POLYMARKET MARKT ERGEBNIS ---")
        print(f"Best Bid (Käufer zahlt max): ${prices['best_bid']:.4f}")
        print(f"Best Ask (Verkäufer will min): ${prices['best_ask']:.4f}")
        print(f"Spread: ${prices['spread']:.4f}")
        
    except Exception as e:
        print(f"\n[FEHLER] Konnte Polymarket-Daten nicht abrufen: {e}")
        print("Hinweis: Falls die Token-ID inaktiv oder abgelaufen ist, liefert die API möglicherweise ein leeres Orderbuch oder einen 404-Fehler.")

if __name__ == "__main__":
    asyncio.run(main())
