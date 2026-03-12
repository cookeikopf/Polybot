import math

class RiskManager:
    def __init__(self, account_balance: float, max_kelly_fraction: float = 0.5):
        """
        Initialisiert den Risk Manager.
        account_balance: Das gesamte verfügbare Kapital in USD.
        max_kelly_fraction: Ein Sicherheitsfaktor (z.B. 0.5 für Half-Kelly), 
                            um die Volatilität der Bankroll zu reduzieren.
        """
        self.account_balance = account_balance
        self.max_kelly_fraction = max_kelly_fraction

    def calculate_kelly_size(self, win_prob: float, pm_ask_price: float) -> float:
        """
        Berechnet die optimale Positionsgröße in USD basierend auf dem Kelly-Kriterium.
        
        win_prob: Die vom Oracle berechnete Wahrscheinlichkeit (z.B. 0.55 für 55%)
        pm_ask_price: Der Preis für ein "YES" Share auf Polymarket (z.B. 0.49)
        
        Returns: Die empfohlene Trade-Größe in USD.
        """
        # Kelly Formel: f* = (p * b - q) / b
        # p = Wahrscheinlichkeit zu gewinnen (win_prob)
        # q = Wahrscheinlichkeit zu verlieren (1 - win_prob)
        # b = Netto-Quote (Net Odds)
        
        p = win_prob
        q = 1.0 - p
        
        # Auf Polymarket kostet ein Share 'pm_ask_price' (z.B. 0.49$).
        # Wenn wir gewinnen, bekommen wir 1.00$ zurück.
        # Der Netto-Gewinn ist also (1.00 - pm_ask_price).
        # Die Netto-Quote (b) ist: Netto-Gewinn / Einsatz
        b = (1.0 - pm_ask_price) / pm_ask_price
        
        if b <= 0:
            return 0.0

        # Kelly Fraction berechnen
        kelly_fraction = (p * b - q) / b
        
        # Wenn Kelly negativ ist (kein Edge)
        if kelly_fraction <= 0:
            return 0.0
            
        # Half-Kelly (oder anderer Fraction) anwenden für besseres Risk Management
        adjusted_kelly = kelly_fraction * self.max_kelly_fraction
        
        # Maximale Positionsgröße in USD berechnen
        recommended_size_usd = self.account_balance * adjusted_kelly
        
        return recommended_size_usd
