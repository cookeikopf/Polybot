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

    async def get_active_btc_markets(self) -> list:
        """
        Sucht in der Polymarket Gamma API nach aktiven Bitcoin-Märkten.
        Nutzt Pagination, um ALLE Märkte zu scannen (nicht nur die Top 1000).
        Extrahiert den Strike-Preis dynamisch, unabhängig vom exakten Wording.
        """
        import re
        from datetime import datetime
        
        btc_markets = []
        limit = 500
        offset = 0
        max_pages = 20 # Max 10.000 Märkte scannen, um Endlosschleifen zu vermeiden
        
        async with aiohttp.ClientSession() as session:
            for page in range(max_pages):
                url = f"{self.gamma_url}/markets?limit={limit}&offset={offset}&active=true&closed=false"
                
                try:
                    async with session.get(url) as response:
                        if response.status != 200:
                            print(f"[FEHLER] Gamma API Status: {response.status}")
                            break
                            
                        markets = await response.json()
                        if not markets:
                            break # Keine weiteren Märkte
                            
                        for market in markets:
                            question = market.get("question", "")
                            description = market.get("description", "")
                            group_title = market.get("groupItemTitle", "")
                            
                            # 1. Ist es ein Bitcoin-Markt? (Check in Titel oder Beschreibung)
                            text_to_search = f"{question} {description}".lower()
                            if "bitcoin" not in text_to_search and "btc" not in text_to_search:
                                continue
                                
                            # 2. Dynamische Strike-Preis Extraktion
                            # Wir suchen nach JEDER Zahl, die ein plausibler BTC-Preis sein könnte (z.B. 20k bis 500k)
                            # Wir checken zuerst den groupItemTitle (oft bei gebündelten Preis-Märkten genutzt wie "$70,000")
                            # Dann die Frage, dann die Beschreibung.
                            
                            strike = None
                            search_texts = [group_title, question, description]
                            
                            for text in search_texts:
                                if not text:
                                    continue
                                    
                                # Finde alle Zahlen-Muster (mit oder ohne $, mit Komma, mit k/m)
                                # Matcht: 70000, 70,000, $70k, 70.5k, 100000
                                matches = re.finditer(r'\$?([0-9]{1,3}(,[0-9]{3})*(\.[0-9]+)?|[0-9]+(\.[0-9]+)?)[kKmM]?', text)
                                
                                for match in matches:
                                    val_str = match.group(0).lower().replace('$', '').replace(',', '')
                                    
                                    multiplier = 1
                                    if 'k' in val_str:
                                        multiplier = 1000
                                        val_str = val_str.replace('k', '')
                                    elif 'm' in val_str:
                                        multiplier = 1000000
                                        val_str = val_str.replace('m', '')
                                        
                                    try:
                                        potential_price = float(val_str) * multiplier
                                        # Plausibilitätscheck: Ist das ein BTC Preis? (20k - 500k)
                                        if 20000 <= potential_price <= 500000:
                                            strike = potential_price
                                            break # Strike gefunden!
                                    except ValueError:
                                        continue
                                        
                                if strike:
                                    break # Wir haben den Strike für diesen Markt gefunden
                                    
                            if not strike:
                                continue # Kein plausibler Strike-Preis gefunden -> Kein Preis-Markt
                                
                            # 3. Ablaufdatum extrahieren
                            end_date_str = market.get("endDate")
                            if not end_date_str:
                                continue
                                
                            try:
                                clean_date_str = end_date_str.split('.')[0].replace('Z', '')
                                end_date = datetime.strptime(clean_date_str, "%Y-%m-%dT%H:%M:%S")
                                now = datetime.utcnow()
                                days_to_expiry = (end_date - now).total_seconds() / 86400.0
                                
                                if days_to_expiry <= 0:
                                    continue
                            except Exception:
                                continue
                            
                            # 4. Token ID für "Yes" Outcome finden
                            outcomes = market.get("outcomes", [])
                            token_ids = market.get("clobTokenIds", [])
                            
                            try:
                                yes_index = next(i for i, x in enumerate(outcomes) if x.lower() == "yes")
                                yes_token_id = token_ids[yes_index]
                            except (ValueError, StopIteration):
                                continue
                                
                            btc_markets.append({
                                "question": question,
                                "strike": strike,
                                "days_to_expiry": days_to_expiry,
                                "token_id": yes_token_id,
                                "expiry_date_str": end_date.strftime("%Y-%m-%d %H:%M:%S")
                            })
                            
                        offset += limit # Nächste Seite
                        
                except Exception as e:
                    print(f"[FEHLER] get_active_btc_markets Pagination: {e}")
                    break
                    
        return btc_markets

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
