import { useEffect, useState } from "react";
import { InsightPanel } from "../components/InsightPanel";
import { PlayerProjectionTable } from "../components/PlayerProjectionTable";
import { PossessionFeed } from "../components/PossessionFeed";
import { QuarterProjectionTable } from "../components/QuarterProjectionTable";
import { Scoreboard } from "../components/Scoreboard";
import { WinProbabilityChart } from "../components/WinProbabilityChart";
import { fetchGamePreview, fetchSnapshot } from "../lib/api";
import { mockPreview, mockSnapshot } from "../lib/mockData";
import type { GamePreview, Snapshot } from "../types";

function TeamPreviewCard({
  team,
}: {
  team: GamePreview["homeTeam"] | GamePreview["awayTeam"];
}) {
  return (
    <div className="rounded-3xl border border-white/8 bg-panelAlt/80 p-5">
      <p className="text-xs uppercase tracking-[0.3em] text-muted">{team.teamId}</p>
      <h3 className="mt-2 font-display text-2xl text-white">{team.teamName}</h3>
      <p className="mt-1 text-sm text-electric">{team.coachName}</p>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <div className="rounded-2xl bg-black/20 p-3">
          <p className="text-xs text-muted">OffRtg</p>
          <p className="mt-1 text-xl font-semibold text-white">{team.offensiveRating}</p>
        </div>
        <div className="rounded-2xl bg-black/20 p-3">
          <p className="text-xs text-muted">DefRtg</p>
          <p className="mt-1 text-xl font-semibold text-white">{team.defensiveRating}</p>
        </div>
        <div className="rounded-2xl bg-black/20 p-3">
          <p className="text-xs text-muted">Pace</p>
          <p className="mt-1 text-xl font-semibold text-white">{team.pace}</p>
        </div>
        <div className="rounded-2xl bg-black/20 p-3">
          <p className="text-xs text-muted">Bench Depth</p>
          <p className="mt-1 text-xl font-semibold text-white">{Math.round(team.benchDepth * 100)}%</p>
        </div>
      </div>
    </div>
  );
}

export function GameDetailPage({
  gameId,
  onBack,
  onOpenPlayer,
}: {
  gameId: string;
  onBack: () => void;
  onOpenPlayer: (playerId: string) => void;
}) {
  const [preview, setPreview] = useState<GamePreview>(mockPreview);
  const [snapshot, setSnapshot] = useState<Snapshot>(mockSnapshot);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadGame() {
      setLoading(true);
      try {
        const [previewData, snapshotData] = await Promise.all([
          fetchGamePreview(gameId),
          fetchSnapshot(gameId),
        ]);
        if (!cancelled) {
          setPreview(previewData);
          setSnapshot(snapshotData);
        }
      } catch {
        if (!cancelled) {
          setPreview(mockPreview);
          setSnapshot(mockSnapshot);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadGame();
    return () => {
      cancelled = true;
    };
  }, [gameId]);

  async function rerunPrediction() {
    setRefreshing(true);
    try {
      const snapshotData = await fetchSnapshot(gameId);
      setSnapshot(snapshotData);
    } catch {
      setSnapshot(mockSnapshot);
    } finally {
      setRefreshing(false);
    }
  }

  if (loading) {
    return (
      <main className="min-h-screen bg-grid bg-[size:22px_22px] px-4 py-6 md:px-8">
        <div className="mx-auto max-w-7xl">
          <section className="panel p-6">
            <p className="text-sm text-muted">Loading matchup page...</p>
          </section>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-grid bg-[size:22px_22px] px-4 py-6 md:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <section className="panel p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <button
                type="button"
                onClick={onBack}
                className="mb-4 rounded-full border border-white/10 px-4 py-2 text-sm text-ink transition hover:border-white/20 hover:bg-white/5"
              >
                Back to games
              </button>
              <p className="metric-chip mb-3">Matchup page</p>
              <h1 className="font-display text-4xl text-white md:text-5xl">
                {preview.awayTeam.teamName} at {preview.homeTeam.teamName}
              </h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-muted">{preview.headline}</p>
            </div>
            <div className="rounded-3xl border border-white/10 bg-white/5 px-5 py-4 text-right">
              <p className="text-xs uppercase tracking-[0.3em] text-muted">{preview.status}</p>
              <p className="mt-1 text-lg text-white">{preview.tipoff}</p>
              <p className="text-sm text-electric">{preview.broadcast}</p>
              <p className="mt-1 text-sm text-muted">{preview.arena}</p>
            </div>
          </div>
        </section>

        <div className="grid gap-6 lg:grid-cols-2">
          <TeamPreviewCard team={preview.awayTeam} />
          <TeamPreviewCard team={preview.homeTeam} />
        </div>

        <section className="panel p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="panel-title">Prediction setup</h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted">{preview.predictionSummary}</p>
            </div>
            <button
              type="button"
              onClick={rerunPrediction}
              disabled={refreshing}
              className="rounded-full bg-accent px-5 py-3 font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {refreshing ? "Refreshing..." : "Re-run prediction"}
            </button>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {preview.gameFactors.map((factor) => (
              <span key={factor} className="rounded-full border border-white/8 px-3 py-1 text-xs text-ink">
                {factor}
              </span>
            ))}
          </div>
        </section>

        <Scoreboard
          quarter={snapshot.quarter}
          clock={snapshot.clock}
          homeTeam={snapshot.homeTeam}
          awayTeam={snapshot.awayTeam}
        />

        <InsightPanel
          insights={snapshot.insights}
          title="AI Game Insights"
          subtitle="How the model sees the matchup unfolding"
        />

        <PlayerProjectionTable players={snapshot.playerProjections} onOpenPlayer={onOpenPlayer} />

        <div className="grid gap-6 xl:grid-cols-[1.3fr_0.9fr]">
          <div className="space-y-6">
            <QuarterProjectionTable homeTeam={snapshot.homeTeam} awayTeam={snapshot.awayTeam} />
            <WinProbabilityChart data={snapshot.winProbabilitySeries} />
          </div>
          <div className="space-y-6">
            <PossessionFeed events={snapshot.possessionFeed} />
          </div>
        </div>
      </div>
    </main>
  );
}
