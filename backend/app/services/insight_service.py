from app.schemas.game import InsightCard
from app.simulation.state import GameContext


class InsightService:
    def build_game_insights(self, context: GameContext) -> list[InsightCard]:
        star = max(
            context.home_team.players + context.away_team.players,
            key=lambda player: player.points + player.momentum_score * 10,
        )
        return [
            InsightCard(
                title="Primary Defensive Shift",
                body=(
                    f"{star.player_name}'s aggressive start is forcing help-side compression, "
                    "increasing stunt-and-recover frequency and shifting expected creation toward weak-side shooters."
                ),
                severity="warning",
            ),
            InsightCard(
                title="Fatigue Watch",
                body=(
                    "BallPredict is elevating late-game variance because both lead creators are above their expected touch-time load, "
                    "which raises turnover volatility and lowers rim finishing efficiency."
                ),
                severity="info",
            ),
            InsightCard(
                title="Bench Leverage Edge",
                body=(
                    "Second-unit lineup synergy favors the home team due to stronger defensive rebounding continuity and cleaner slot spacing."
                ),
                severity="advantage",
            ),
        ]


insight_service = InsightService()

