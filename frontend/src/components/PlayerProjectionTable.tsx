import type { PlayerProjection } from "../types";

export function PlayerProjectionTable({
  players,
  onOpenPlayer,
}: {
  players: PlayerProjection[];
  onOpenPlayer: (playerId: string) => void;
}) {
  return (
    <section className="panel p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="panel-title">Player Stat Predictions</h3>
        <span className="text-sm text-muted">Projected final stat lines</span>
      </div>

      <div className="overflow-hidden rounded-3xl border border-white/6">
        <table className="w-full text-left text-sm">
          <thead className="bg-black/25 text-muted">
            <tr>
              <th className="px-4 py-3">Player</th>
              <th className="px-4 py-3">PTS</th>
              <th className="px-4 py-3">3PM</th>
              <th className="px-4 py-3">REB</th>
              <th className="px-4 py-3">AST</th>
              <th className="px-4 py-3">TOV</th>
              <th className="px-4 py-3">USG</th>
              <th className="px-4 py-3">FG%</th>
            </tr>
          </thead>
          <tbody>
            {players.map((player) => (
              <tr
                key={player.playerId}
                className="cursor-pointer border-t border-white/6 bg-white/[0.02] transition hover:bg-white/[0.06]"
                onClick={() => onOpenPlayer(player.playerId)}
              >
                <td className="px-4 py-4">
                  <div>
                    <p className="font-medium text-white">{player.playerName}</p>
                    <p className="text-xs uppercase tracking-[0.2em] text-muted">{player.teamId}</p>
                    <p className="mt-1 text-xs text-electric">Open player page</p>
                  </div>
                </td>
                <td className="px-4 py-4 text-ink">{player.projectedStats.mean.points}</td>
                <td className="px-4 py-4 text-ink">{player.projectedStats.mean.threesMade}</td>
                <td className="px-4 py-4 text-ink">{player.projectedStats.mean.rebounds}</td>
                <td className="px-4 py-4 text-ink">{player.projectedStats.mean.assists}</td>
                <td className="px-4 py-4 text-ink">{player.projectedStats.mean.turnovers}</td>
                <td className="px-4 py-4 text-electric">
                  {(player.projectedStats.mean.usageRate * 100).toFixed(0)}%
                </td>
                <td className="px-4 py-4 text-ink">
                  {(player.projectedStats.mean.fieldGoalPct * 100).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
