import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useEffect, useState } from "react";
import { InsightPanel } from "../components/InsightPanel";
import { fetchPlayerDetail } from "../lib/api";
import type { BreakoutStats, PlayerDetail } from "../types";

function DetailStatCard({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-3xl border border-white/8 bg-panelAlt/80 p-5">
      <p className="text-xs uppercase tracking-[0.25em] text-muted">{label}</p>
      <p className={`mt-2 font-display text-3xl ${accent ? "text-electric" : "text-white"}`}>{value}</p>
    </div>
  );
}

function BreakoutPanel({ stats }: { stats: BreakoutStats }) {
  const pct = Math.round(stats.breakoutProbability * 100);
  const alert = stats.breakoutAlert;
  return (
    <section className={`panel p-6 ${alert ? "border border-orange-400/40 bg-orange-400/5" : ""}`}>
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="panel-title">Breakout Game Profile</h2>
          {alert && (
            <span className="rounded-full bg-orange-400/20 px-3 py-1 text-xs font-semibold uppercase tracking-widest text-orange-300">
              Alert
            </span>
          )}
        </div>
        <div className="text-right">
          <p className="text-xs uppercase tracking-[0.25em] text-muted">30+ pt probability</p>
          <p className={`font-display text-3xl ${alert ? "text-orange-300" : "text-white"}`}>{pct}%</p>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {[
          { label: "Pts on Big Nights", value: stats.meanPts },
          { label: "Ast on Big Nights", value: stats.meanAst },
          { label: "Reb on Big Nights", value: stats.meanReb },
          { label: "3PM on Big Nights", value: stats.meanFg3m },
          { label: "Stl on Big Nights", value: stats.meanStl },
          { label: "Blk on Big Nights", value: stats.meanBlk },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-2xl border border-white/8 bg-white/3 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.2em] text-muted">{label}</p>
            <p className="mt-1 font-display text-2xl text-white">{value.toFixed(1)}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

export function PlayerDetailPage({
  gameId,
  playerId,
  onBackToGame,
}: {
  gameId: string;
  playerId: string;
  onBackToGame: () => void;
}) {
  const [detail, setDetail] = useState<PlayerDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadPlayer() {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchPlayerDetail(gameId, playerId);
        if (!cancelled) setDetail(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load player");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadPlayer();
    return () => { cancelled = true; };
  }, [gameId, playerId]);

  if (loading) {
    return (
      <main className="min-h-screen bg-black flex flex-col items-center justify-center gap-8 px-4">
        <div className="relative flex items-center justify-center">
          <div className="absolute h-32 w-32 rounded-full border border-white/10 animate-ping" style={{ animationDuration: "2s" }} />
          <div className="absolute h-24 w-24 rounded-full border border-white/20 animate-ping" style={{ animationDuration: "1.4s" }} />
          <img
            src="/logo.png"
            alt="BALLTALK"
            className="relative h-16 w-16 object-contain"
            style={{ animation: "logoBreath 2s ease-in-out infinite" }}
          />
        </div>
        <div className="flex flex-col items-center gap-3">
          <div className="flex items-center gap-2">
            <p className="font-mono text-sm font-bold uppercase tracking-[0.35em] text-white">Predicting Player Stats</p>
            <span className="flex gap-1">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="h-1 w-1 rounded-full bg-white"
                  style={{ animation: "dotBounce 1.2s ease-in-out infinite", animationDelay: `${i * 0.2}s` }}
                />
              ))}
            </span>
          </div>
        </div>
        <style>{`
          @keyframes logoBreath {
            0%, 100% { opacity: 0.7; transform: scale(1); }
            50% { opacity: 1; transform: scale(1.08); }
          }
          @keyframes dotBounce {
            0%, 80%, 100% { opacity: 0.2; transform: translateY(0); }
            40% { opacity: 1; transform: translateY(-4px); }
          }
        `}</style>
      </main>
    );
  }

  if (error || !detail) {
    return (
      <main className="min-h-screen bg-grid bg-[size:22px_22px] px-4 py-6 md:px-8">
        <div className="mx-auto max-w-7xl flex flex-col gap-6">
          <section className="panel p-6">
            <button
              type="button"
              onClick={onBackToGame}
              className="mb-4 rounded-full border border-white/10 px-4 py-2 text-sm text-ink transition hover:border-white/20 hover:bg-white/5"
            >
              Back to matchup
            </button>
            <p className="text-sm font-semibold text-red-400">Error loading player</p>
            <p className="mt-2 text-sm text-muted">{error ?? "No data returned from API"}</p>
          </section>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-grid bg-[size:22px_22px] px-4 py-6 md:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <section className="panel p-6">
          <button
            type="button"
            onClick={onBackToGame}
            className="mb-4 rounded-full border border-white/10 px-4 py-2 text-sm text-ink transition hover:border-white/20 hover:bg-white/5"
          >
            Back to matchup
          </button>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="metric-chip mb-3">Player prediction page</p>
              <h1 className="font-display text-4xl text-white md:text-5xl">{detail.playerName}</h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-muted">
                {detail.teamName} vs {detail.opponentTeamName}. {detail.coachCounterSummary}
              </p>
            </div>
            <div className="rounded-3xl border border-white/10 bg-white/5 px-5 py-4 text-right">
              <p className="text-xs uppercase tracking-[0.3em] text-muted">Pressure</p>
              <p className="mt-1 font-display text-3xl text-electric">
                {(detail.confidence.pressure * 100).toFixed(0)}%
              </p>
              <p className="text-sm text-muted">{detail.teamId.toUpperCase()}</p>
            </div>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <DetailStatCard label="Projected Points" value={detail.projection.projectedStats.mean.points.toFixed(1)} accent />
          <DetailStatCard label="Projected Assists" value={detail.projection.projectedStats.mean.assists.toFixed(1)} />
          <DetailStatCard label="Projected Rebounds" value={detail.projection.projectedStats.mean.rebounds.toFixed(1)} />
          <DetailStatCard label="Projected 3PM" value={detail.projection.projectedStats.mean.threesMade.toFixed(1)} />
          <DetailStatCard label="Projected Steals" value={detail.projection.projectedStats.mean.steals.toFixed(1)} />
          <DetailStatCard label="Projected Blocks" value={detail.projection.projectedStats.mean.blocks.toFixed(1)} />
        </section>

        <section className="panel p-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="panel-title">Confidence Range</h2>
            <span className="text-sm text-muted">Floor to ceiling scoring band</span>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <DetailStatCard label="Floor" value={detail.confidence.floorPoints.toFixed(1)} />
            <DetailStatCard label="Median" value={detail.confidence.medianPoints.toFixed(1)} accent />
            <DetailStatCard label="Ceiling" value={detail.confidence.ceilingPoints.toFixed(1)} />
          </div>
        </section>

        {detail.breakoutStats && <BreakoutPanel stats={detail.breakoutStats} />}

        <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <section className="panel p-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="panel-title">Quarter Breakdown</h2>
              <span className="text-sm text-muted">Projected game flow by quarter</span>
            </div>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={detail.quarterBreakdown}>
                  <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                  <XAxis dataKey="quarter" stroke="#89a3ba" />
                  <YAxis stroke="#89a3ba" />
                  <Tooltip
                    contentStyle={{
                      background: "#0d1c2b",
                      borderRadius: 16,
                      border: "1px solid rgba(255,255,255,0.08)",
                    }}
                  />
                  <Legend />
                  <Bar dataKey="points" fill="#6ee7ff" radius={[8, 8, 0, 0]} />
                  <Bar dataKey="assists" fill="#f97316" radius={[8, 8, 0, 0]} />
                  <Bar dataKey="rebounds" fill="#34d399" radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="panel p-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="panel-title">Matchup Factors</h2>
              <span className="text-sm text-muted">What is moving the projection</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {detail.matchupFactors.map((factor) => (
                <span key={factor} className="rounded-full border border-white/8 px-3 py-2 text-sm text-ink">
                  {factor}
                </span>
              ))}
            </div>
            <div className="mt-6 rounded-3xl border border-accent/20 bg-accent/10 p-5">
              <h3 className="font-display text-2xl text-white">Coach Counter Summary</h3>
              <p className="mt-3 text-sm leading-6 text-muted">{detail.coachCounterSummary}</p>
            </div>
          </section>
        </div>

        <InsightPanel
          insights={detail.playerInsights}
          title="AI Player Insights"
          subtitle="Why this player's projection is moving"
        />

        <section className="panel p-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="panel-title">Live vs Final Projection</h2>
            <span className="text-sm text-muted">Current stats versus end-of-game projection</span>
          </div>
          {detail.statProfile.every((s) => s.live === 0) ? (
            <div className="flex h-40 items-center justify-center rounded-2xl border border-white/6 bg-white/3">
              <p className="text-sm text-muted">Live stats will appear once the game starts</p>
            </div>
          ) : (
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={detail.statProfile} margin={{ top: 20, right: 10, left: -10, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                  <XAxis dataKey="label" stroke="#89a3ba" tick={{ fontSize: 12 }} />
                  <YAxis stroke="#89a3ba" tick={{ fontSize: 12 }} />
                  <Tooltip
                    contentStyle={{
                      background: "#0d1c2b",
                      borderRadius: 16,
                      border: "1px solid rgba(255,255,255,0.08)",
                    }}
                  />
                  <Legend />
                  <Bar dataKey="live" name="Live" fill="#64748b" radius={[6, 6, 0, 0]}>
                    <LabelList dataKey="live" position="top" style={{ fill: "#89a3ba", fontSize: 11 }} />
                  </Bar>
                  <Bar dataKey="projected" name="Projected" fill="#6ee7ff" radius={[6, 6, 0, 0]}>
                    <LabelList dataKey="projected" position="top" style={{ fill: "#6ee7ff", fontSize: 11 }} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
