import type { SlateGame } from "../types";

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

function TeamLogoImg({ teamId, abbr, size = 48 }: { teamId: string; abbr: string; size?: number }) {
  const path = teamLogoPath(teamId);
  if (!path) {
    return (
      <span className="font-mono text-base font-bold text-white">{abbr}</span>
    );
  }
  return (
    <img
      src={path}
      alt={abbr}
      width={size}
      height={size}
      className="object-contain"
      onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
    />
  );
}

function SlateCard({
  game,
  onOpen,
}: {
  game: SlateGame;
  onOpen: (gameId: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(game.gameId)}
      className="border border-white/10 bg-black p-5 text-left transition hover:border-white/25 hover:bg-neutral-950"
    >
      {/* Team logos row */}
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-4">
          <div className="flex flex-col items-center gap-1">
            <TeamLogoImg teamId={game.awayAbbreviation} abbr={game.awayAbbreviation} size={48} />
            <span className="font-mono text-[10px] font-bold uppercase tracking-[0.3em] text-white">
              {game.awayAbbreviation}
            </span>
          </div>
          <span className="font-mono text-xs text-white">@</span>
          <div className="flex flex-col items-center gap-1">
            <TeamLogoImg teamId={game.homeAbbreviation} abbr={game.homeAbbreviation} size={48} />
            <span className="font-mono text-[10px] font-bold uppercase tracking-[0.3em] text-white">
              {game.homeAbbreviation}
            </span>
          </div>
        </div>
        <span className="border border-white/20 px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-[0.4em] text-white">
          {game.status}
        </span>
      </div>

      {/* Matchup heading */}
      <h2 className="font-mono text-xl font-bold italic text-white leading-tight">
        {game.awayTeam} <span className="text-white">at</span> {game.homeTeam}
      </h2>
      <p className="mt-2 text-xs leading-5 text-white">{game.headline}</p>

      {/* Tipoff / Broadcast */}
      <div className="mt-4 grid grid-cols-2 gap-3 text-xs border-t border-white/20 pt-4">
        <div>
          <p className="font-mono text-[9px] uppercase tracking-[0.4em] text-white">Tipoff</p>
          <p className="mt-1 font-mono font-bold text-white">{game.tipoff}</p>
        </div>
        <div>
          <p className="font-mono text-[9px] uppercase tracking-[0.4em] text-white">Broadcast</p>
          <p className="mt-1 font-mono font-bold text-white">{game.broadcast}</p>
        </div>
      </div>

      {/* Records */}
      <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
        <div>
          <p className="font-mono text-[9px] uppercase tracking-[0.4em] text-white">{game.awayAbbreviation} Record</p>
          <p className="mt-1 font-mono font-bold text-white">{game.awayRecord}</p>
        </div>
        <div>
          <p className="font-mono text-[9px] uppercase tracking-[0.4em] text-white">{game.homeAbbreviation} Record</p>
          <p className="mt-1 font-mono font-bold text-white">{game.homeRecord}</p>
        </div>
      </div>

      <p className="mt-4 text-xs text-white">{game.predictionHook}</p>

      {/* CTA */}
      <div className="mt-5 border-t border-white/20 pt-4">
        <p className="font-mono text-[10px] font-bold uppercase tracking-[0.5em] text-white">
          Open Analysis →
        </p>
      </div>
    </button>
  );
}

export function SlatePage({
  games,
  slateError,
  onOpenGame,
}: {
  games: SlateGame[];
  slateError?: string | null;
  onOpenGame: (gameId: string) => void;
}) {
  return (
    <main className="min-h-screen bg-black px-4 py-6 md:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        {/* Header */}
        <section className="border border-white/10 bg-black p-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              {/* Logo + name row */}
              <div className="flex items-center gap-4 mb-3">
                <img
                  src="/logo.png"
                  alt="BallTalk"
                  className="h-20 w-20 object-contain"
                />
                <h1 className="font-mono text-5xl font-bold italic text-white md:text-6xl tracking-tighter">
                  BALLTALK<span className="text-white">.</span>
                </h1>
              </div>
              <p className="font-mono text-[10px] uppercase tracking-[0.6em] text-white mb-1">
                AI Prediction Model · Today&apos;s NBA Slate
              </p>
              <div className="h-px w-32 bg-white/30 mb-4" />
              <p className="max-w-2xl text-xs leading-6 text-white">
                Click any matchup for AI-projected scores, player stat predictions, series momentum analysis, and coaching adjustments.
              </p>
            </div>
            <div className="border border-white/10 px-6 py-5">
              <p className="font-mono text-[9px] uppercase tracking-[0.5em] text-white">Scheduled Today</p>
              <p className="mt-2 font-mono text-4xl font-bold text-white">{games.length}</p>
              <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.4em] text-white">Games Ready</p>
            </div>
          </div>
        </section>

        {slateError && (
          <section className="border border-warning/30 bg-black px-5 py-4 font-mono text-sm text-warning">
            Failed to load games: {slateError}
          </section>
        )}

        <section className="grid gap-4 xl:grid-cols-3">
          {games.map((game) => (
            <SlateCard key={game.gameId} game={game} onOpen={onOpenGame} />
          ))}
          {!slateError && games.length === 0 && (
            <p className="col-span-3 py-12 text-center font-mono text-xs uppercase tracking-[0.4em] text-white">
              No games scheduled today.
            </p>
          )}
        </section>
      </div>
    </main>
  );
}
