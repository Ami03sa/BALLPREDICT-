import type { Snapshot } from "../types";

export function PossessionFeed({ events }: { events: Snapshot["possessionFeed"] }) {
  const leverageTone = {
    low: "text-muted",
    medium: "text-electric",
    high: "text-warning",
  } as const;

  return (
    <section className="panel p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="panel-title">Live Possession Feed</h3>
        <span className="text-sm text-muted">Tactical events, not just play-by-play</span>
      </div>
      <div className="space-y-3">
        {events.map((event, index) => (
          <div key={`${event.clock}-${index}`} className="rounded-3xl border border-white/6 bg-black/20 p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-display text-white">
                Q{event.quarter} {event.clock}
              </span>
              <span className={`text-xs uppercase tracking-[0.25em] ${leverageTone[event.leverage]}`}>
                {event.leverage}
              </span>
            </div>
            <p className="text-sm leading-6 text-muted">{event.summary}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

