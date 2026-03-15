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

    async def get_15m_btc_market(self) -> list:
        """
        Der 'Game-Changer': Berechnet den Slug für den aktuellen 15-Minuten BTC Up/Down Markt
        und ruft diesen direkt ab. Das ist 10x schneller und umgeht das Indexing-Lag der Gamma API.
        Prüft sowohl die aktuelle als auch die nächste Periode, da Märkte oft schon vorab gelistet werden
        oder die aktuelle Periode kurz vor Ablauf geschlossen wird.
        """
        import time
        from datetime import datetime, timezone
        import re
        
        now = int(time.time())
        # 900 Sekunden = 15 Minuten. Wir runden ab auf den Start der aktuellen Periode.
        period_start = (now // 900) * 900
        
        # Wir prüfen die aktuelle und die nächste Periode
        periods_to_check = [period_start, period_start + 900]
        btc_markets = []
        
        async with aiohttp.ClientSession() as session:
            for ts in periods_to_check:
                slug = f"btc-updown-15m-{ts}"
                url = f"{self.gamma_url}/events?slug={slug}"
                
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            events = await response.json()
                            if not events:
                                continue
                                
                            event = events[0]
                            # Überspringe geschlossene Events
                            if event.get("closed", False):
                                continue
                                
                            markets = event.get("markets", [])
                            
                            for market in markets:
                                # Überspringe geschlossene Märkte
                                if market.get("closed", False):
                                    continue
                                    
                                question = market.get("question", "")
                                description = market.get("description", "")
                                
                                # Strike-Preis aus der Description oder Question extrahieren
                                strike = None
                                
                                # Bei Up/Down Märkten steht der Strike oft in der Description ("The strike price is $65,432.10" oder "Strike: $65000")
                                match = re.search(r'strike(?: price)?(?: is)?\s*\$?([0-9,]+(\.[0-9]+)?)', description, re.IGNORECASE)
                                if match:
                                    strike = float(match.group(1).replace(',', ''))
                                else:
                                    # Fallback: Suche nach Zahlen im Titel
                                    match = re.search(r'\$?([0-9]{2,}(,[0-9]{3})*(\.[0-9]+)?)[kKmM]?', question)
                                    if match:
                                        val_str = match.group(1).replace(',', '')
                                        multiplier = 1
                                        if 'k' in match.group(0).lower(): multiplier = 1000
                                        elif 'm' in match.group(0).lower(): multiplier = 1000000
                                        try:
                                            potential_strike = float(val_str) * multiplier
                                            if 20000 <= potential_strike <= 500000:
                                                strike = potential_strike
                                        except ValueError:
                                            pass
                                            
                                # Wenn kein Strike gefunden wurde, ist es ein echter "Up/Down from current price" Markt.
                                # Wir setzen den Strike vorerst auf 0 und markieren ihn, damit main.py den aktuellen BTC Preis einsetzt.
                                needs_current_price = False
                                if not strike:
                                    strike = 0.0
                                    needs_current_price = True
                                    
                                end_date_str = market.get("endDate")
                                if not end_date_str:
                                    continue
                                    
                                try:
                                    clean_date_str = end_date_str.split('.')[0].replace('Z', '')
                                    end_date = datetime.strptime(clean_date_str, "%Y-%m-%dT%H:%M:%S")
                                    now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
                                    days_to_expiry = (end_date - now_dt).total_seconds() / 86400.0
                                    
                                    if days_to_expiry <= 0:
                                        continue
                                except Exception:
                                    continue
                                    
                                outcomes = market.get("outcomes", [])
                                token_ids = market.get("clobTokenIds", [])
                                
                                import json
                                if isinstance(outcomes, str):
                                    try:
                                        outcomes = json.loads(outcomes)
                                    except:
                                        outcomes = []
                                if isinstance(token_ids, str):
                                    try:
                                        token_ids = json.loads(token_ids)
                                    except:
                                        token_ids = []
                                
                                try:
                                    # Bei Up/Down Märkten heißen die Outcomes "Up" und "Down", nicht "Yes" und "No"!
                                    yes_index = next(i for i, x in enumerate(outcomes) if x.lower() in ["yes", "up"])
                                    yes_token_id = token_ids[yes_index]
                                except (ValueError, StopIteration):
                                    print(f"[DEBUG] Konnte 'Up'/'Yes' Outcome nicht finden. Outcomes: {outcomes}")
                                    continue
                                    
                                btc_markets.append({
                                    "question": question,
                                    "strike": strike,
                                    "days_to_expiry": days_to_expiry,
                                    "token_id": yes_token_id,
                                    "expiry_date_str": end_date.strftime("%Y-%m-%d %H:%M:%S"),
                                    "is_15m_updown": True,
                                    "needs_current_price": needs_current_price
                                })
                                
                except Exception as e:
                    print(f"[FEHLER] get_15m_btc_market für {slug}: {e}")
                    
        return btc_markets

    async def get_active_btc_markets(self) -> list:
        """
        Sucht in der Polymarket Gamma API nach aktiven Bitcoin-Märkten.
        Nutzt den /events Endpoint (effizienter als /markets) und Pagination.
        """
        import re
        from datetime import datetime, timezone
        
        btc_markets = []
        limit = 100
        offset = 0
        max_pages = 10 # 1000 Events scannen
        
        async with aiohttp.ClientSession() as session:
            for page in range(max_pages):
                # Wir nutzen /events statt /markets, da Events die zugehörigen Märkte gebündelt mitliefern
                url = f"{self.gamma_url}/events?limit={limit}&offset={offset}&active=true&closed=false"
                
                try:
                    async with session.get(url) as response:
                        if response.status != 200:
                            break
                            
                        events = await response.json()
                        if not events:
                            break
                            
                        for event in events:
                            title = event.get("title", "").lower()
                            description = event.get("description", "").lower()
                            
                            # Ist es ein Bitcoin Event?
                            if "bitcoin" not in title and "btc" not in title and "bitcoin" not in description:
                                continue
                                
                            markets = event.get("markets", [])
                            for market in markets:
                                question = market.get("question", "")
                                market_desc = market.get("description", "")
                                
                                strike = None
                                search_texts = [title, question, market_desc]
                                
                                for text in search_texts:
                                    if not text:
                                        continue
                                        
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
                                            if 20000 <= potential_price <= 500000:
                                                strike = potential_price
                                                break
                                        except ValueError:
                                            continue
                                    if strike:
                                        break
                                        
                                if not strike:
                                    continue
                                    
                                end_date_str = market.get("endDate")
                                if not end_date_str:
                                    continue
                                    
                                try:
                                    clean_date_str = end_date_str.split('.')[0].replace('Z', '')
                                    end_date = datetime.strptime(clean_date_str, "%Y-%m-%dT%H:%M:%S")
                                    now = datetime.now(timezone.utc).replace(tzinfo=None)
                                    days_to_expiry = (end_date - now).total_seconds() / 86400.0
                                    
                                    if days_to_expiry <= 0:
                                        continue
                                except Exception:
                                    continue
                                
                                outcomes = market.get("outcomes", [])
                                token_ids = market.get("clobTokenIds", [])
                                
                                import json
                                if isinstance(outcomes, str):
                                    try:
                                        outcomes = json.loads(outcomes)
                                    except:
                                        outcomes = []
                                if isinstance(token_ids, str):
                                    try:
                                        token_ids = json.loads(token_ids)
                                    except:
                                        token_ids = []
                                
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
                                    "expiry_date_str": end_date.strftime("%Y-%m-%d %H:%M:%S"),
                                    "is_15m_updown": False
                                })
                                
                        offset += limit
                        
                except aiohttp.ClientPayloadError as e:
                    print(f"[WARNUNG] get_active_btc_markets Pagination (Payload Error): {e} - Versuche nächste Seite...")
                    offset += limit
                    continue
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
