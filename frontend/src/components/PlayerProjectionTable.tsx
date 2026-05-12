import type { PlayerProjection } from "../types";

export function PlayerProjectionTable({
  players,
  teamName,
  teamId,
  projectedTeamScore,
  onOpenPlayer,
}: {
  players: PlayerProjection[];
  teamName: string;
  teamId: string;
  projectedTeamScore: number;
  onOpenPlayer: (playerId: string) => void;
}) {
  const orderedPlayers = [...players].sort((left, right) => {
    const statusWeight = (player: PlayerProjection) => {
      if (player.availabilityStatus === "dnp") return 2;
      if (player.rotationRole === "starter") return 0;
      return 1;
    };
    return statusWeight(left) - statusWeight(right);
  });

  const totals = players.reduce(
    (accumulator, player) => ({
      points: accumulator.points + player.projectedStats.mean.points,
      threesMade: accumulator.threesMade + player.projectedStats.mean.threesMade,
      rebounds: accumulator.rebounds + player.projectedStats.mean.rebounds,
      assists: accumulator.assists + player.projectedStats.mean.assists,
      turnovers: accumulator.turnovers + player.projectedStats.mean.turnovers,
      usageRate: accumulator.usageRate + player.projectedStats.mean.usageRate,
    }),
    { points: 0, threesMade: 0, rebounds: 0, assists: 0, turnovers: 0, usageRate: 0 },
  );

  return (
    <section className="panel p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="panel-title">Player Stat Predictions</h3>
          <p className="mt-1 text-sm text-muted">
            {teamName} projected roster output
          </p>
        </div>
        <span className="text-sm text-muted">
          Team score target {projectedTeamScore}
        </span>
      </div>

      <div className="overflow-hidden rounded-3xl border border-white/6">
        <table className="w-full text-left text-sm">
          <thead className="bg-black/25 text-muted">
            <tr>
              <th className="px-4 py-3">Player</th>
              <th className="px-4 py-3">Status</th>
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
            {orderedPlayers.map((player) => (
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
                <td className="px-4 py-4 text-ink">
                  {player.availabilityStatus === "dnp"
                    ? `DNP${player.dnpReason ? ` - ${player.dnpReason}` : ""}`
                    : player.rotationRole === "starter"
                      ? "Starter"
                      : "Bench"}
                </td>
                {player.availabilityStatus === "dnp" ? (
                  <>
                    <td className="px-4 py-4 text-muted">DNP</td>
                    <td className="px-4 py-4 text-muted">DNP</td>
                    <td className="px-4 py-4 text-muted">DNP</td>
                    <td className="px-4 py-4 text-muted">DNP</td>
                    <td className="px-4 py-4 text-muted">DNP</td>
                    <td className="px-4 py-4 text-muted">DNP</td>
                    <td className="px-4 py-4 text-muted">DNP</td>
                  </>
                ) : (
                  <>
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
                  </>
                )}
              </tr>
            ))}
            <tr className="border-t border-electric/20 bg-electric/10">
              <td className="px-4 py-4">
                <div>
                  <p className="font-semibold text-white">{teamName} Totals</p>
                  <p className="text-xs uppercase tracking-[0.2em] text-electric">{teamId.toUpperCase()}</p>
                </div>
              </td>
              <td className="px-4 py-4 font-semibold text-white">Active Rotation</td>
              <td className="px-4 py-4 font-semibold text-white">{totals.points.toFixed(1)}</td>
              <td className="px-4 py-4 font-semibold text-white">{totals.threesMade.toFixed(1)}</td>
              <td className="px-4 py-4 font-semibold text-white">{totals.rebounds.toFixed(1)}</td>
              <td className="px-4 py-4 font-semibold text-white">{totals.assists.toFixed(1)}</td>
              <td className="px-4 py-4 font-semibold text-white">{totals.turnovers.toFixed(1)}</td>
              <td className="px-4 py-4 font-semibold text-electric">{(totals.usageRate * 100).toFixed(0)}%</td>
              <td className="px-4 py-4 font-semibold text-white">Score {projectedTeamScore}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}
