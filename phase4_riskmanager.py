import asyncio

class RiskManager:
    def __init__(self):
        pass

    def calculate_position_size(self, bankroll: float, oracle_prob: float, pm_ask: float, kelly_fraction: float = 0.25, max_risk_pct: float = 0.05) -> float:
        """
        Berechnet die optimale Positionsgröße basierend auf dem Fractional Kelly-Kriterium für Binäre Optionen.
        
        bankroll: Gesamtkapital in USDC
        oracle_prob: Wahrscheinlichkeit laut Oracle (p)
        pm_ask: Preis auf Polymarket (Implied Probability des Marktes)
        kelly_fraction: Bruchteil des Kelly-Wertes zur Risikominimierung (z.B. 0.25 für Quarter-Kelly)
        max_risk_pct: Maximales Risiko pro Trade als Prozentsatz der Bankroll (z.B. 0.05 = 5%)
        """
        # Edge berechnen
        edge = oracle_prob - pm_ask
        
        # Wenn kein Edge vorhanden ist, wird nicht getradet
        if edge <= 0:
            return 0.0
            
        # Kelly-Prozentsatz für Binäre Optionen (Auszahlung 1$)
        # Formel: f* = (p - p_market) / (1 - p_market)
        # Wobei p = oracle_prob und p_market = pm_ask
        
        # Schutz vor Division durch 0 (falls pm_ask = 1.0, was ohnehin keinen Sinn macht zu kaufen)
        if pm_ask >= 1.0:
            return 0.0
            
        kelly_pct = edge / (1 - pm_ask)
        
        # Fractional Kelly anwenden
        fractional_kelly_pct = kelly_pct * kelly_fraction
        
        # Cap auf maximales Risiko anwenden
        final_pct = min(fractional_kelly_pct, max_risk_pct)
        
        # Finale Trade Size in USDC berechnen
        trade_size_usd = bankroll * final_pct
        
        # Auf 2 Nachkommastellen runden
        return round(trade_size_usd, 2)

# --- Test / Ausführung ---
async def main():
    risk_manager = RiskManager()
    bankroll = 1000.0  # 1000 USDC
    
    print(f"--- RISK MANAGEMENT TEST (Bankroll: ${bankroll:,.2f}) ---")
    print("Parameter: Quarter-Kelly (0.25), Max Risk Cap: 5.0%\n")
    
    # Szenario A: Guter Edge
    oracle_a = 0.65
    pm_ask_a = 0.50
    size_a = risk_manager.calculate_position_size(bankroll, oracle_a, pm_ask_a)
    edge_a = oracle_a - pm_ask_a
    print(f"Szenario A (Guter Edge):")
    print(f"  Oracle: {oracle_a:.0%} | PM Ask: ${pm_ask_a:.2f} | Edge: {edge_a:+.0%}")
    print(f"  -> Empfohlene Trade Size: ${size_a:.2f} ({(size_a/bankroll):.2%})\n")
    
    # Szenario B: Schwacher Edge
    oracle_b = 0.52
    pm_ask_b = 0.50
    size_b = risk_manager.calculate_position_size(bankroll, oracle_b, pm_ask_b)
    edge_b = oracle_b - pm_ask_b
    print(f"Szenario B (Schwacher Edge):")
    print(f"  Oracle: {oracle_b:.0%} | PM Ask: ${pm_ask_b:.2f} | Edge: {edge_b:+.0%}")
    print(f"  -> Empfohlene Trade Size: ${size_b:.2f} ({(size_b/bankroll):.2%})\n")
    
    # Szenario C: Negativer Edge
    oracle_c = 0.40
    pm_ask_c = 0.50
    size_c = risk_manager.calculate_position_size(bankroll, oracle_c, pm_ask_c)
    edge_c = oracle_c - pm_ask_c
    print(f"Szenario C (Negativer Edge):")
    print(f"  Oracle: {oracle_c:.0%} | PM Ask: ${pm_ask_c:.2f} | Edge: {edge_c:+.0%}")
    print(f"  -> Empfohlene Trade Size: ${size_c:.2f} ({(size_c/bankroll):.2%})\n")

if __name__ == "__main__":
    asyncio.run(main())
