import { motion } from "framer-motion";
import type { PlayerProjection } from "../types";

export function MomentumCard({ player }: { player: PlayerProjection }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-3xl border border-white/8 bg-panelAlt/80 p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-muted">{player.teamId}</p>
          <h4 className="font-display text-2xl text-white">{player.playerName}</h4>
        </div>
        <span className="metric-chip">Pressure {(player.defensivePressure * 100).toFixed(0)}%</span>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3">
        <div className="rounded-2xl bg-black/20 p-3">
          <p className="text-xs text-muted">Live PTS</p>
          <p className="mt-1 text-2xl font-semibold text-white">{player.liveStats.points}</p>
        </div>
        <div className="rounded-2xl bg-black/20 p-3">
          <p className="text-xs text-muted">Proj AST</p>
          <p className="mt-1 text-2xl font-semibold text-white">{player.projectedStats.mean.assists}</p>
        </div>
        <div className="rounded-2xl bg-black/20 p-3">
          <p className="text-xs text-muted">Proj REB</p>
          <p className="mt-1 text-2xl font-semibold text-white">{player.projectedStats.mean.rebounds}</p>
        </div>
      </div>
      <div className="mt-5 space-y-3">
        <div>
          <div className="mb-1 flex justify-between text-xs text-muted">
            <span>Momentum</span>
            <span>{(player.momentumScore * 100).toFixed(0)}%</span>
          </div>
          <div className="h-2 rounded-full bg-white/8">
            <div className="h-2 rounded-full bg-electric" style={{ width: `${player.momentumScore * 100}%` }} />
          </div>
        </div>
        <div>
          <div className="mb-1 flex justify-between text-xs text-muted">
            <span>Fatigue</span>
            <span>{(player.fatigueIndex * 100).toFixed(0)}%</span>
          </div>
          <div className="h-2 rounded-full bg-white/8">
            <div className="h-2 rounded-full bg-accent" style={{ width: `${player.fatigueIndex * 100}%` }} />
          </div>
        </div>
      </div>
    </motion.div>
  );
}

