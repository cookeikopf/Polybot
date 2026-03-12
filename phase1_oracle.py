import asyncio
import aiohttp
import math
from datetime import datetime
import scipy.stats as stats

class DeribitOracle:
    def __init__(self):
        self.base_url = "https://deribit.com/api/v2/public"

    async def get_index_price(self, currency: str) -> float:
        """Holt den aktuellen Index-Preis für die Währung (z.B. BTC, ETH)."""
        url = f"{self.base_url}/get_index_price?index_name={currency.lower()}_usd"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                if "result" in data:
                    return data["result"]["index_price"]
                raise ValueError(f"Fehler beim Abrufen des Index-Preises: {data}")

    async def get_implied_volatility(self, currency: str) -> float:
        """Holt die aktuelle Implied Volatility (DVOL) für die Währung."""
        # Nutze den direkten Index-Preis für DVOL (z.B. btc_dvol_usd)
        url = f"{self.base_url}/get_index_price?index_name={currency.lower()}_dvol_usd"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                if "result" in data and "index_price" in data["result"]:
                    # DVOL ist in Prozentpunkten (z.B. 45.5), wir brauchen Dezimal (0.455)
                    return float(data["result"]["index_price"]) / 100.0
                raise ValueError(f"Fehler beim Abrufen der IV: {data}")

    def calculate_probability(self, S: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
        """
        Berechnet die Wahrscheinlichkeit N(d2), dass der Preis bei Verfall über dem Strike (K) liegt.
        S: Aktueller Preis
        K: Strike Preis (Ziel-Level)
        T: Zeit bis zum Verfall in Jahren
        sigma: Implied Volatility (annualisiert)
        r: Risikofreier Zinssatz
        """
        if T <= 0:
            return 1.0 if S >= K else 0.0

        # Black-Scholes d1 und d2
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        # N(d2) ist die risikoneutrale Wahrscheinlichkeit, dass die Option In-The-Money verfällt
        probability = stats.norm.cdf(d2)
        return probability

    async def evaluate_target(self, currency: str, target_price: float, expiry_date_str: str) -> dict:
        """
        Evaluiert die Wahrscheinlichkeit für ein spezifisches Preisziel und Datum.
        expiry_date_str: Format 'YYYY-MM-DD HH:MM:SS' (UTC)
        """
        try:
            # 1. Zeit bis zum Verfall berechnen (T in Jahren)
            expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d %H:%M:%S")
            now = datetime.utcnow()
            time_to_expiry_seconds = (expiry_date - now).total_seconds()

            if time_to_expiry_seconds <= 0:
                raise ValueError("Verfallsdatum liegt in der Vergangenheit.")

            T = time_to_expiry_seconds / (365.25 * 24 * 3600)

            # 2. Aktuellen Preis und IV asynchron abrufen
            S, sigma = await asyncio.gather(
                self.get_index_price(currency),
                self.get_implied_volatility(currency)
            )

            # 3. Wahrscheinlichkeit berechnen (N(d2))
            prob = self.calculate_probability(S=S, K=target_price, T=T, sigma=sigma)

            return {
                "currency": currency.upper(),
                "current_price": S,
                "target_price": target_price,
                "implied_volatility": sigma,
                "time_to_expiry_years": T,
                "probability_yes": prob,
                "probability_no": 1 - prob
            }

        except Exception as e:
            print(f"[ERROR] Oracle Evaluation fehlgeschlagen: {e}")
            return None

# --- Test / Ausführung ---
async def main():
    oracle = DeribitOracle()
    currency = "BTC"
    target_price = 100000.0
    # Beispiel: Verfall in der Zukunft (UTC)
    expiry = "2026-12-31 08:00:00"

    print(f"Starte Oracle für {currency} > {target_price} am {expiry}...")
    result = await oracle.evaluate_target(currency, target_price, expiry)

    if result:
        print("\n--- ORACLE ERGEBNIS ---")
        print(f"Aktueller Preis:   ${result['current_price']:,.2f}")
        print(f"Implied Vol (IV):  {result['implied_volatility']*100:.2f}%")
        print(f"Zeit (Jahre):      {result['time_to_expiry_years']:.4f}")
        print(f"Wahrscheinlichkeit (YES): {result['probability_yes']*100:.2f}%")
        print(f"Wahrscheinlichkeit (NO):  {result['probability_no']*100:.2f}%")

if __name__ == "__main__":
    asyncio.run(main())
