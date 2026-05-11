import type { Adjustment, PlayerProjection } from "../types";

function ImpactPill({ label, value }: { label: string; value: number }) {
  const tone = value > 0 ? "text-success" : "text-warning";
  const prefix = value > 0 ? "+" : "";
  return (
    <span className="rounded-full border border-white/8 bg-black/20 px-3 py-1 text-xs">
      {label} <strong className={tone}>{prefix}{value}</strong>
    </span>
  );
}

function AdjustmentCard({ adjustment }: { adjustment: Adjustment }) {
  return (
    <div className="rounded-3xl border border-white/8 bg-black/20 p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h4 className="font-display text-lg text-white">{adjustment.title}</h4>
        <span className="rounded-full border border-accent/30 bg-accent/10 px-3 py-1 text-xs uppercase tracking-[0.2em] text-accent">
          {adjustment.side}
        </span>
      </div>
      <p className="text-sm text-electric">{adjustment.trigger}</p>
      <p className="mt-3 text-sm leading-6 text-muted">{adjustment.explanation}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {adjustment.counters.map((counter) => (
          <span key={counter} className="rounded-full border border-white/8 px-3 py-1 text-xs text-ink">
            {counter}
          </span>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {Object.entries(adjustment.impact).map(([key, value]) => (
          <ImpactPill key={key} label={key} value={Number(value.toFixed ? value.toFixed(2) : value)} />
        ))}
      </div>
    </div>
  );
}

export function CoachingAdjustmentPanel({ players }: { players: PlayerProjection[] }) {
  const featured = players.slice(0, 2).flatMap((player) =>
    player.adjustments.map((adjustment) => ({ player, adjustment })),
  );

  return (
    <section className="panel p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="panel-title">Adaptive Coaching Engine</h3>
        <span className="text-sm text-muted">Coverage, pace, and rotation changes</span>
      </div>
      <div className="space-y-4">
        {featured.map(({ player, adjustment }) => (
          <div key={`${player.playerId}-${adjustment.title}`}>
            <p className="mb-2 text-xs uppercase tracking-[0.3em] text-muted">{player.playerName}</p>
            <AdjustmentCard adjustment={adjustment} />
          </div>
        ))}
      </div>
    </section>
  );
}

