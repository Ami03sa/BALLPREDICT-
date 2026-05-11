import type { Snapshot } from "../types";

export function InsightPanel({ insights }: Pick<Snapshot, "insights">) {
  const severityStyle = {
    info: "border-electric/20 bg-electric/10 text-electric",
    warning: "border-warning/20 bg-warning/10 text-warning",
    advantage: "border-success/20 bg-success/10 text-success",
  } as const;

  return (
    <section className="panel p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="panel-title">AI Insights Panel</h3>
        <span className="text-sm text-muted">Natural-language basketball reasoning</span>
      </div>
      <div className="space-y-4">
        {insights.map((insight) => (
          <article key={insight.title} className="rounded-3xl border border-white/6 bg-black/20 p-4">
            <div className="mb-3 flex items-center justify-between">
              <h4 className="font-display text-lg text-white">{insight.title}</h4>
              <span className={`rounded-full border px-3 py-1 text-xs uppercase tracking-[0.2em] ${severityStyle[insight.severity]}`}>
                {insight.severity}
              </span>
            </div>
            <p className="text-sm leading-6 text-muted">{insight.body}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

