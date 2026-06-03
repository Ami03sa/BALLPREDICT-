import type { PlayerProjection } from "../types";

// ── Status badge ─────────────────────────────────────────────────────────────
function StatusBadge({ player }: { player: PlayerProjection }) {
  const reason = player.dnpReason ?? "";

  // Confirmed OUT
  if (player.availabilityStatus === "dnp") {
    const injuryText = reason
      .replace(/^DNP\s*[-–]\s*/i, "")
      .replace(/^Injury report:\s*/i, "")
      .replace(/^Missed \d+ of last \d+ games/i, "Missed recent games")
      .replace(/^DNP — 0 minutes in last 5 games/i, "0 min streak")
      .trim();
    return (
      <div className="flex flex-col gap-1">
        <span className="inline-flex w-fit items-center gap-1 rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-red-400 ring-1 ring-red-500/30">
          <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
          OUT
        </span>
        {injuryText && (
          <span className="text-[10px] text-red-400/70">{injuryText}</span>
        )}
      </div>
    );
  }

  // Questionable / Day-To-Day warning (⚠ prefix set by injury_lineup_service)
  if (reason.startsWith("⚠")) {
    const isDtd = reason.toLowerCase().includes("day-to-day");
    const isDoubtful = reason.toLowerCase().includes("doubtful");
    const label = isDoubtful ? "DOUBTFUL" : isDtd ? "DAY-TO-DAY" : "QUESTIONABLE";
    const cleanReason = reason.replace(/^⚠\s*/, "").trim();
    const colour = isDoubtful
      ? "bg-orange-500/15 text-orange-400 ring-orange-500/30"
      : isDtd
        ? "bg-amber-500/15 text-amber-400 ring-amber-500/30"
        : "bg-yellow-500/15 text-yellow-400 ring-yellow-500/30";
    const dot = isDoubtful ? "bg-orange-400" : isDtd ? "bg-amber-400" : "bg-yellow-400";
    return (
      <div className="flex flex-col gap-1">
        <span className={`inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest ring-1 ${colour}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
          {label}
        </span>
        <span className="text-[10px] text-white/40">{cleanReason}</span>
      </div>
    );
  }

  // Active — show rotation role
  const isStarter = player.rotationRole === "starter" || player.rotationRole === "star";
  const isStar    = player.rotationRole === "star";
  if (isStar) {
    return (
      <span className="inline-flex w-fit items-center gap-1 rounded-full bg-electric/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-electric ring-1 ring-electric/30">
        <span className="h-1.5 w-1.5 rounded-full bg-electric" />
        STAR
      </span>
    );
  }
  if (isStarter) {
    return (
      <span className="inline-flex w-fit items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-emerald-400 ring-1 ring-emerald-500/30">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        STARTER
      </span>
    );
  }
  return (
    <span className="inline-flex w-fit items-center gap-1 rounded-full bg-white/8 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-white/50 ring-1 ring-white/10">
      <span className="h-1.5 w-1.5 rounded-full bg-white/30" />
      BENCH
    </span>
  );
}

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
                <td className="px-4 py-4">
                  <StatusBadge player={player} />
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
              <td className="px-4 py-4">
                <span className="inline-flex w-fit items-center gap-1 rounded-full bg-white/8 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-white/60 ring-1 ring-white/10">
                  Active Rotation
                </span>
              </td>
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
