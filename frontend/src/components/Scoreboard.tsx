import { motion } from "framer-motion";
import type { TeamProjection } from "../types";

type ScoreboardProps = {
  quarter: number;
  clock: string;
  homeTeam: TeamProjection;
  awayTeam: TeamProjection;
};

export function Scoreboard({ quarter, clock, homeTeam, awayTeam }: ScoreboardProps) {
  const teamRows = [awayTeam, homeTeam];
  const phaseLabel = quarter === 0 ? "Pregame simulation" : `Q${quarter}`;
  const clockLabel = quarter === 0 ? "Model ready" : clock;

  return (
    <motion.section
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      className="panel overflow-hidden p-6"
    >
      <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="metric-chip mb-3">Live intelligence engine</p>
          <h1 className="font-display text-4xl text-white">BallPredict</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted">
            Quarter-aware NBA simulation that adapts to momentum, coverages, fatigue, lineup context,
            and coaching counters in real time.
          </p>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/5 px-5 py-4 text-right">
          <p className="text-xs uppercase tracking-[0.3em] text-muted">Game state</p>
          <p className="mt-1 font-display text-3xl text-white">{phaseLabel}</p>
          <p className="text-lg text-electric">{clockLabel}</p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {teamRows.map((team) => (
          <div key={team.teamId} className="rounded-3xl border border-white/6 bg-panelAlt/80 p-5">
            <div className="mb-4 flex items-start justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-muted">{team.teamId}</p>
                <h2 className="font-display text-2xl text-white">{team.teamName}</h2>
              </div>
              <div className="text-right">
                <p className="font-display text-5xl text-white">{team.finalScoreMean}</p>
                <p className="text-sm text-muted">
                  CI {team.finalScoreCI[0]}-{team.finalScoreCI[1]}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3 text-sm">
              <div className="rounded-2xl bg-black/20 p-3">
                <p className="text-muted">Win %</p>
                <p className="mt-1 text-xl font-semibold text-electric">
                  {(team.winProbability * 100).toFixed(0)}%
                </p>
              </div>
              <div className="rounded-2xl bg-black/20 p-3">
                <p className="text-muted">Pace</p>
                <p className="mt-1 text-xl font-semibold text-white">{team.pace}</p>
              </div>
              <div className="rounded-2xl bg-black/20 p-3">
                <p className="text-muted">OffRtg</p>
                <p className="mt-1 text-xl font-semibold text-white">{team.offensiveRating}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </motion.section>
  );
}
