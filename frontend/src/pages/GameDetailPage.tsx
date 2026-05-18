import { useEffect, useState } from "react";
import { fetchGamePreview, fetchSnapshot } from "../lib/api";
import type { GamePreview, PlayerProjection, Snapshot } from "../types";

// NBA team tricode → numeric team ID for logo CDN
const NBA_TEAM_IDS: Record<string, string> = {
  atl: "1610612737", bos: "1610612738", bkn: "1610612751", cha: "1610612766",
  chi: "1610612741", cle: "1610612739", dal: "1610612742", den: "1610612743",
  det: "1610612765", gsw: "1610612744", hou: "1610612745", ind: "1610612754",
  lac: "1610612746", lal: "1610612747", mem: "1610612763", mia: "1610612748",
  mil: "1610612749", min: "1610612750", nop: "1610612740", nyk: "1610612752",
  okc: "1610612760", orl: "1610612753", phi: "1610612755", phx: "1610612756",
  por: "1610612757", sac: "1610612758", sas: "1610612759", tor: "1610612761",
  uta: "1610612762", was: "1610612764",
};

function teamLogoUrl(teamId: string): string {
  const id = NBA_TEAM_IDS[teamId.toLowerCase()];
  if (!id) return "";
  return `https://cdn.nba.com/logos/nba/${id}/global/L/logo.svg`;
}

function playerHeadshotUrl(playerId: string): string {
  // NBA CDN headshots use the numeric personId
  return `https://cdn.nba.com/headshots/nba/latest/1040x760/${playerId}.png`;
}

function TeamLogo({ teamId, teamName, size = 80 }: { teamId: string; teamName: string; size?: number }) {
  const [errored, setErrored] = useState(false);
  const url = teamLogoUrl(teamId);
  const abbr = teamId.toUpperCase().slice(0, 3);

  if (!url || errored) {
    return (
      <div
        style={{ width: size, height: size }}
        className="flex items-center justify-center rounded-full bg-white/10 font-display text-xl font-bold text-white"
      >
        {abbr}
      </div>
    );
  }

  return (
    <img
      src={url}
      alt={teamName}
      width={size}
      height={size}
      className="object-contain drop-shadow-lg"
      onError={() => setErrored(true)}
    />
  );
}

function PlayerFace({
  player,
  onClick,
}: {
  player: PlayerProjection;
  onClick: () => void;
}) {
  const [imgErrored, setImgErrored] = useState(false);
  const isDnp = player.availabilityStatus === "dnp";

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isDnp}
      className={`group flex flex-col items-center gap-2 text-center transition
        ${isDnp
          ? "cursor-default opacity-40"
          : "cursor-pointer active:scale-95"
        }`}
    >
      <div className="relative overflow-hidden rounded-xl border-2 border-white/10 bg-white/5 transition group-hover:border-electric/60"
           style={{ width: 110, height: 120 }}>
        {!imgErrored ? (
          <img
            src={playerHeadshotUrl(player.playerId)}
            alt={player.playerName}
            className="h-full w-full object-cover object-top"
            onError={() => setImgErrored(true)}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-2xl font-bold text-white">
            {player.playerName.split(" ").map((n) => n[0]).join("").slice(0, 2)}
          </div>
        )}
        {player.rotationRole === "starter" && !isDnp && (
          <span className="absolute bottom-1.5 left-1.5 rounded-md bg-electric px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-canvas">
            Starter
          </span>
        )}
      </div>
      <div>
        <p className="w-[110px] truncate text-xs font-medium leading-tight text-white">
          {player.playerName.split(" ").slice(-1)[0]}
        </p>
        {isDnp && (
          <p className="text-[9px] uppercase tracking-wider text-muted">DNP</p>
        )}
      </div>
    </button>
  );
}

function PlayerRoster({
  teamName,
  teamId,
  players,
  onOpenPlayer,
}: {
  teamName: string;
  teamId: string;
  players: PlayerProjection[];
  onOpenPlayer: (id: string) => void;
}) {
  const sorted = [...players].sort((a, b) => {
    if (a.availabilityStatus === "dnp" && b.availabilityStatus !== "dnp") return 1;
    if (a.availabilityStatus !== "dnp" && b.availabilityStatus === "dnp") return -1;
    if (a.rotationRole === "starter" && b.rotationRole !== "starter") return -1;
    if (a.rotationRole !== "starter" && b.rotationRole === "starter") return 1;
    return 0;
  });

  return (
    <div className="panel p-5">
      <div className="mb-4 flex items-center gap-3">
        <TeamLogo teamId={teamId} teamName={teamName} size={32} />
        <div>
          <h3 className="font-display text-lg text-white">{teamName}</h3>
          <p className="text-xs text-muted">Tap a player to see stats &amp; predictions</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-3">
        {sorted.map((player) => (
          <PlayerFace
            key={player.playerId}
            player={player}
            onClick={() => {
              if (player.availabilityStatus !== "dnp") onOpenPlayer(player.playerId);
            }}
          />
        ))}
      </div>
    </div>
  );
}

function NBAScoreboard({
  quarter,
  clock,
  status,
  homeTeam,
  awayTeam,
  homePredicted,
  awayPredicted,
  tipoff,
  arena,
  broadcast,
}: {
  quarter: number;
  clock: string;
  status: string;
  homeTeam: Snapshot["homeTeam"] & { teamName: string; teamId: string };
  awayTeam: Snapshot["awayTeam"] & { teamName: string; teamId: string };
  homePredicted: number;
  awayPredicted: number;
  tipoff: string;
  arena: string;
  broadcast: string;
}) {
  const isFinal = status === "final";
  const isLive = status === "live";
  const isScheduled = !isFinal && !isLive;

  const phaseLabel = isFinal
    ? "FINAL"
    : isLive
      ? `Q${quarter} ${clock}`
      : `Tipoff ${tipoff}`;

  function TeamBlock({ team, predicted, actualScore }: { team: typeof homeTeam; predicted: number; actualScore: number }) {
    return (
      <div className="flex flex-1 flex-col items-center gap-2 text-center">
        <TeamLogo teamId={team.teamId} teamName={team.teamName} size={80} />
        <div>
          <p className="font-display text-xl text-white">{team.teamName.split(" ").slice(-1)[0]}</p>
          <p className="text-xs uppercase tracking-wider text-muted">{team.teamId.toUpperCase()}</p>
        </div>
        <div className="flex flex-col items-center gap-0.5">
          <span className="font-display text-3xl tabular-nums leading-none text-electric">
            {predicted}
          </span>
          <span className="text-[9px] uppercase tracking-widest text-muted">
            {isFinal ? "AI Predicted" : isLive ? "Proj. Final" : "Predicted"}
          </span>
          {isFinal && (
            <span className="mt-1 text-[9px] uppercase tracking-widest text-muted/60">
              Actual: {actualScore}
            </span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="panel overflow-hidden">
      {/* Status bar */}
      <div className={`px-6 py-2 text-center text-xs font-semibold uppercase tracking-widest
        ${isFinal ? "bg-white/8 text-muted" : isLive ? "bg-electric/20 text-electric" : "bg-accent/20 text-accent"}`}>
        {phaseLabel}
      </div>

      {/* Main scoreboard */}
      <div className="flex items-center justify-between gap-4 px-6 py-8 md:px-12">
        <TeamBlock team={awayTeam} predicted={awayPredicted} actualScore={awayTeam.score} />

        {/* Live / final score — shows actual game score only when game is in progress or final */}
        <div className="flex items-center gap-4 md:gap-8">
          {isScheduled ? (
            <span className="font-display text-sm uppercase tracking-widest text-muted">Not Started</span>
          ) : (
            <>
              <span className="font-display text-6xl tabular-nums leading-none text-white md:text-7xl">
                {awayTeam.score}
              </span>
              <span className="text-2xl text-white/20">–</span>
              <span className="font-display text-6xl tabular-nums leading-none text-white md:text-7xl">
                {homeTeam.score}
              </span>
            </>
          )}
        </div>

        <TeamBlock team={homeTeam} predicted={homePredicted} actualScore={homeTeam.score} />
      </div>

      {/* Game info footer */}
      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 border-t border-white/6 px-6 py-3 text-xs text-muted">
        {broadcast && broadcast !== "NBA TV" && <span>{broadcast}</span>}
        {broadcast && <span>·</span>}
        <span>{arena}</span>
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
  const [preview, setPreview] = useState<GamePreview | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadGame() {
      setLoading(true);
      setError(null);
      try {
        const [previewData, snapshotData] = await Promise.all([
          fetchGamePreview(gameId),
          fetchSnapshot(gameId),
        ]);
        if (!cancelled) {
          setPreview(previewData);
          setSnapshot(snapshotData);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load game");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadGame();
    return () => { cancelled = true; };
  }, [gameId]);

  if (loading) {
    return (
      <main className="min-h-screen bg-grid bg-[size:22px_22px] px-4 py-6 md:px-8">
        <div className="mx-auto max-w-4xl">
          <div className="panel p-8 text-center">
            <p className="text-sm text-muted">Loading game...</p>
          </div>
        </div>
      </main>
    );
  }

  if (error || !preview || !snapshot) {
    return (
      <main className="min-h-screen bg-grid bg-[size:22px_22px] px-4 py-6 md:px-8">
        <div className="mx-auto max-w-4xl flex flex-col gap-5">
          <button
            type="button"
            onClick={onBack}
            className="self-start rounded-full border border-white/10 px-4 py-2 text-sm text-ink transition hover:border-white/20 hover:bg-white/5"
          >
            ← Back to games
          </button>
          <div className="panel p-8">
            <p className="text-sm font-semibold text-red-400">Error loading game</p>
            <p className="mt-2 text-sm text-muted">{error ?? "No data returned from API"}</p>
          </div>
        </div>
      </main>
    );
  }

  const homePlayers = snapshot.playerProjections.filter((p) => p.teamId === snapshot.homeTeam.teamId);
  const awayPlayers = snapshot.playerProjections.filter((p) => p.teamId === snapshot.awayTeam.teamId);

  const homePredictedScore = snapshot.homeTeam.finalScoreMean;
  const awayPredictedScore = snapshot.awayTeam.finalScoreMean;

  return (
    <main className="min-h-screen bg-grid bg-[size:22px_22px] px-4 py-6 md:px-8">
      <div className="mx-auto flex max-w-4xl flex-col gap-5">
        <button
          type="button"
          onClick={onBack}
          className="self-start rounded-full border border-white/10 px-4 py-2 text-sm text-ink transition hover:border-white/20 hover:bg-white/5"
        >
          ← Back to games
        </button>

        <NBAScoreboard
          quarter={snapshot.quarter}
          clock={snapshot.clock}
          status={preview.status}
          homeTeam={{ ...snapshot.homeTeam, teamName: preview.homeTeam.teamName, teamId: snapshot.homeTeam.teamId }}
          awayTeam={{ ...snapshot.awayTeam, teamName: preview.awayTeam.teamName, teamId: snapshot.awayTeam.teamId }}
          homePredicted={homePredictedScore}
          awayPredicted={awayPredictedScore}
          tipoff={preview.tipoff}
          arena={preview.arena}
          broadcast={preview.broadcast}
        />

        <PlayerRoster
          teamName={preview.awayTeam.teamName}
          teamId={snapshot.awayTeam.teamId}
          players={awayPlayers}
          onOpenPlayer={onOpenPlayer}
        />

        <PlayerRoster
          teamName={preview.homeTeam.teamName}
          teamId={snapshot.homeTeam.teamId}
          players={homePlayers}
          onOpenPlayer={onOpenPlayer}
        />
      </div>
    </main>
  );
}
