import { useEffect, useState } from "react";
import { fetchGamePreview, fetchSnapshot } from "../lib/api";
import type { GamePreview, PlayerProjection, Snapshot } from "../types";

// Local logo map
const TEAM_LOGO_MAP: Record<string, string> = {
  atl: "atlanta", bos: "celtics", bkn: "nets", cha: "hornets",
  chi: "bulls", cle: "cavs", dal: "mavs", den: "nuggets",
  det: "pistons", gsw: "warriors", hou: "rockets", ind: "pacers",
  lac: "clippers", lal: "lakers", mem: "grizzlies", mia: "heat",
  mil: "bucks", min: "wolves", nop: "pelicans", nyk: "knicks",
  okc: "okc", orl: "magic", phi: "76ers", phx: "suns",
  por: "portland", sac: "sac", sas: "spurs", tor: "raptors",
  uta: "jazz", was: "wizards",
};

function teamLogoPath(teamId: string): string {
  const name = TEAM_LOGO_MAP[teamId.toLowerCase()];
  return name ? `/logos/${name}.png` : "";
}

function playerHeadshotUrl(playerId: string): string {
  return `https://cdn.nba.com/headshots/nba/latest/1040x760/${playerId}.png`;
}

function TeamLogo({ teamId, teamName, size = 80 }: { teamId: string; teamName: string; size?: number }) {
  const [errored, setErrored] = useState(false);
  const path = teamLogoPath(teamId);
  const abbr = teamId.toUpperCase().slice(0, 3);

  if (!path || errored) {
    return (
      <div
        style={{ width: size, height: size }}
        className="flex items-center justify-center border border-white/10 bg-white/5 font-mono text-xl font-bold text-white"
      >
        {abbr}
      </div>
    );
  }

  return (
    <img
      src={path}
      alt={teamName}
      width={size}
      height={size}
      className="object-contain"
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
      <div className="relative overflow-hidden border border-white/10 bg-white/5 transition group-hover:border-white/30"
           style={{ width: 110, height: 120 }}>
        {!imgErrored ? (
          <img
            src={playerHeadshotUrl(player.playerId)}
            alt={player.playerName}
            className="h-full w-full object-cover object-top"
            onError={() => setImgErrored(true)}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center font-mono text-2xl font-bold text-white">
            {player.playerName.split(" ").map((n) => n[0]).join("").slice(0, 2)}
          </div>
        )}
        {player.rotationRole === "starter" && !isDnp && (
          <span className="absolute bottom-1.5 left-1.5 border border-white/30 bg-black px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider text-white">
            Starter
          </span>
        )}
      </div>
      <div>
        <p className="w-[110px] truncate font-mono text-xs font-medium leading-tight text-white">
          {player.playerName.split(" ").slice(-1)[0]}
        </p>
        {isDnp && (
          <p className="font-mono text-[9px] uppercase tracking-wider text-white">DNP</p>
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
    <div className="border border-white/10 bg-black p-5">
      <div className="mb-4 flex items-center gap-3">
        <TeamLogo teamId={teamId} teamName={teamName} size={32} />
        <div>
          <h3 className="font-mono text-base font-bold uppercase tracking-[0.3em] text-white">{teamName}</h3>
          <p className="font-mono text-[10px] uppercase tracking-[0.3em] text-white">Tap a player to see stats &amp; predictions</p>
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
  isCloseGame,
  predictedMargin,
  blowoutAlert,
  blowoutScore,
  blowoutSignals,
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
  isCloseGame?: boolean;
  predictedMargin?: number;
  blowoutAlert?: boolean;
  blowoutScore?: { home: number; away: number } | null;
  blowoutSignals?: string[];
}) {
  const isFinal = status === "final";
  const isLive = status === "live";
  const isScheduled = !isFinal && !isLive;
  const absMargin = Math.abs(predictedMargin ?? 0);

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
          <p className="font-mono text-base font-bold uppercase tracking-[0.3em] text-white">{team.teamName.split(" ").slice(-1)[0]}</p>
          <p className="font-mono text-[10px] uppercase tracking-[0.4em] text-white">{team.teamId.toUpperCase()}</p>
        </div>
        <div className="flex flex-col items-center gap-0.5">
          <span className="font-mono text-3xl font-bold tabular-nums leading-none text-white">
            {predicted}
          </span>
          <span className="font-mono text-[9px] uppercase tracking-widest text-white">
            {isFinal ? "AI Predicted" : isLive ? "Proj. Final" : "Predicted"}
          </span>
          {isFinal && (
            <span className="mt-1 font-mono text-[9px] uppercase tracking-widest text-white">
              Actual: {actualScore}
            </span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="border border-white/10 bg-black overflow-hidden">
      {/* Status bar */}
      <div className="border-b border-white/10 px-6 py-2 text-center font-mono text-xs font-bold uppercase tracking-[0.5em] text-white">
        {phaseLabel}
      </div>

      {/* Main scoreboard */}
      <div className="flex items-center justify-between gap-4 px-6 py-8 md:px-12">
        <TeamBlock team={awayTeam} predicted={awayPredicted} actualScore={awayTeam.score} />

        {/* Live / final score */}
        <div className="flex flex-col items-center gap-2">
          <div className="flex items-center gap-4 md:gap-8">
            {isScheduled ? (
              <span className="font-mono text-sm uppercase tracking-widest text-white">Not Started</span>
            ) : (
              <>
                <span className="font-mono text-6xl font-bold tabular-nums leading-none text-white md:text-7xl">
                  {awayTeam.score}
                </span>
                <span className="font-mono text-2xl text-white">–</span>
                <span className="font-mono text-6xl font-bold tabular-nums leading-none text-white md:text-7xl">
                  {homeTeam.score}
                </span>
              </>
            )}
          </div>
          {isCloseGame && (
            <div className="border border-white/20 px-3 py-1 text-center">
              <p className="font-mono text-[10px] font-bold uppercase tracking-widest text-white">
                Margin: {absMargin} pts — Too close to call
              </p>
            </div>
          )}
          {blowoutAlert && blowoutScore && (
            <div className="flex flex-col items-center gap-1.5">
              {/* Blowout badge */}
              <div className="flex items-center gap-1.5 border border-white/30 px-3 py-1">
                <p className="font-mono text-[10px] font-bold uppercase tracking-widest text-white">
                  ⚡ Blowout Alert
                </p>
              </div>
              {/* Blowout score */}
              <div className="border border-white/20 px-4 py-2 text-center">
                <p className="font-mono text-[9px] uppercase tracking-widest text-white mb-1">
                  If blowout conditions hold
                </p>
                <p className="font-mono text-base font-bold tabular-nums text-white">
                  {awayTeam.teamId.toUpperCase()} {blowoutScore.away} — {blowoutScore.home} {homeTeam.teamId.toUpperCase()}
                </p>
                {blowoutSignals && blowoutSignals.length > 0 && (
                  <div className="mt-2 flex flex-col gap-0.5">
                    {blowoutSignals.map((sig, i) => (
                      <p key={i} className="font-mono text-[9px] text-white">
                        · {sig}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <TeamBlock team={homeTeam} predicted={homePredicted} actualScore={homeTeam.score} />
      </div>

      {/* Game info footer */}
      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 border-t border-white/10 px-6 py-3 font-mono text-[10px] uppercase tracking-[0.3em] text-white">
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
      <main className="min-h-screen bg-black px-4 py-6 md:px-8">
        <div className="mx-auto max-w-4xl">
          <div className="border border-white/10 bg-black p-8 text-center">
            <p className="font-mono text-xs uppercase tracking-[0.4em] text-white">Loading game...</p>
          </div>
        </div>
      </main>
    );
  }

  if (error || !preview || !snapshot) {
    return (
      <main className="min-h-screen bg-black px-4 py-6 md:px-8">
        <div className="mx-auto max-w-4xl flex flex-col gap-5">
          <button
            type="button"
            onClick={onBack}
            className="self-start border border-white/10 px-4 py-2 font-mono text-xs uppercase tracking-[0.4em] text-white transition hover:border-white/25"
          >
            ← Back
          </button>
          <div className="border border-white/10 bg-black p-8">
            <p className="font-mono text-xs font-bold uppercase tracking-[0.4em] text-warning">Error loading game</p>
            <p className="mt-2 font-mono text-xs text-white">{error ?? "No data returned from API"}</p>
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
    <main className="min-h-screen bg-black px-4 py-6 md:px-8">
      <div className="mx-auto flex max-w-4xl flex-col gap-5">
        <button
          type="button"
          onClick={onBack}
          className="self-start border border-white/10 px-4 py-2 font-mono text-xs uppercase tracking-[0.4em] text-white transition hover:border-white/25"
        >
          ← Back
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
          isCloseGame={snapshot.isCloseGame}
          predictedMargin={snapshot.predictedMargin}
          blowoutAlert={snapshot.blowoutAlert}
          blowoutScore={snapshot.blowoutScore}
          blowoutSignals={snapshot.blowoutSignals}
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
