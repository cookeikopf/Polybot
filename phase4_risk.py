class RiskManager:
    """
    Phase 4: Risk Management & Position Sizing
    Implementiert das Kelly-Kriterium für Binäre Optionen zur optimalen Kapitalallokation.
    INKLUSIVE realistischer Simulation von Slippage und Polymarket Taker Fees!
    """
    def __init__(self, initial_bankroll: float, kelly_multiplier: float = 0.5, min_bet_size: float = 5.0, max_bet_size: float = 100.0, default_slippage: float = 0.003):
        self.bankroll = initial_bankroll
        self.kelly_multiplier = kelly_multiplier  # Standard: Half-Kelly (0.5) für geringere Volatilität
        self.min_bet_size = min_bet_size
        self.max_bet_size = max_bet_size
        self.default_slippage = default_slippage  # Standard: 0.3% Slippage

    def update_bankroll(self, current_balance: float):
        """Aktualisiert den Kontostand für dynamisches Sizing."""
        self.bankroll = current_balance

    def calculate_taker_fee(self, shares: float, price: float, is_crypto: bool = True) -> float:
        """
        Berechnet die dynamische Polymarket Taker Fee.
        Crypto Märkte (Up/Down): fee_rate = 0.25, exponent = 2
        """
        fee_rate = 0.25 if is_crypto else 0.0175
        exponent = 2 if is_crypto else 1
        return shares * price * fee_rate * (price * (1.0 - price))**exponent

    def calculate_position_size(self, true_prob: float, market_price: float, is_crypto: bool = True) -> dict:
        """
        Berechnet die optimale Positionsgröße basierend auf dem Kelly-Kriterium.
        Berücksichtigt Slippage und Taker Fees für ein realistisches Paper-Trading.
        """
        # 1. Slippage anwenden (Wir zahlen als Taker immer etwas mehr als den Mid-Price/Best Ask)
        effective_price = market_price + self.default_slippage
        if effective_price >= 1.0:
            return {"bet_size": 0.0, "kelly_pct": 0.0, "reason": "Price + Slippage >= 1.0"}

        # 2. Taker Fee pro Share berechnen (Simulation für 1 Share)
        fee_per_share = self.calculate_taker_fee(1.0, effective_price, is_crypto)
        
        # 3. Totale Kosten pro Share
        total_cost = effective_price + fee_per_share

        # 4. Realistischen Edge prüfen
        edge = true_prob - total_cost
        if edge <= 0:
            return {
                "bet_size": 0.0,
                "kelly_pct": 0.0,
                "reason": f"No Edge after costs (Cost: {total_cost:.4f})"
            }

        # 5. Full Kelly Fraction berechnen (angepasst an totale Kosten)
        # f* = (p - C) / (1 - C)
        full_kelly_pct = (true_prob - total_cost) / (1.0 - total_cost)

        # 6. Fractional Kelly anwenden (Risiko-Dämpfung)
        adj_kelly_pct = full_kelly_pct * self.kelly_multiplier

        # 7. Absolute Positionsgröße berechnen
        raw_bet_size = self.bankroll * adj_kelly_pct

        # 8. Min/Max Limits anwenden
        if raw_bet_size < self.min_bet_size:
            final_bet_size = 0.0
            reason = f"Bet size too small (< {self.min_bet_size} USDC)"
        else:
            final_bet_size = min(raw_bet_size, self.max_bet_size)
            reason = "Valid"

        return {
            "bet_size": round(final_bet_size, 2),
            "kelly_pct": round(adj_kelly_pct * 100, 2),
            "raw_kelly_pct": round(full_kelly_pct * 100, 2),
            "edge_pct": round(edge * 100, 2),
            "effective_price": round(effective_price, 4),
            "fee_per_share": round(fee_per_share, 4),
            "total_cost": round(total_cost, 4),
            "reason": reason
        }

# --- Test-Logik ---
if __name__ == "__main__":
    # Test-Szenario: 1000 USDC Bankroll, Half-Kelly, 0.3% Slippage
    rm = RiskManager(initial_bankroll=1000.0, kelly_multiplier=0.5, min_bet_size=5.0, max_bet_size=150.0, default_slippage=0.003)
    
    print("--- REALISTIC KELLY CRITERION TEST (incl. Fees & Slippage) ---")
    # Szenario 1: Starker Edge
    res1 = rm.calculate_position_size(true_prob=0.65, market_price=0.50)
    print(f"Szenario 1 (BSM: 65%, Market: 50c):")
    print(f"  -> Eff. Price: {res1.get('effective_price')} | Fee/Share: {res1.get('fee_per_share')} | Total Cost: {res1.get('total_cost')}")
    print(f"  -> Edge {res1['edge_pct']}%, Bet: ${res1['bet_size']} ({res1['kelly_pct']}% Bankroll)\n")
    
    # Szenario 2: Schwacher Edge (wird durch Fees/Slippage gefressen!)
    res2 = rm.calculate_position_size(true_prob=0.52, market_price=0.50)
    print(f"Szenario 2 (BSM: 52%, Market: 50c):")
    if res2['bet_size'] == 0:
        print(f"  -> REJECTED: {res2['reason']}\n")
    else:
        print(f"  -> Edge {res2['edge_pct']}%, Bet: ${res2['bet_size']} ({res2['kelly_pct']}% Bankroll)\n")
