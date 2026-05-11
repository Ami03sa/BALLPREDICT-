import type { SlateGame } from "../types";

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
      className="rounded-[28px] border border-white/8 bg-panelAlt/70 p-5 text-left transition hover:border-white/20 hover:bg-panelAlt"
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="rounded-2xl bg-white/5 px-3 py-2 font-display text-lg text-white">
            {game.awayAbbreviation}
          </span>
          <span className="text-muted">@</span>
          <span className="rounded-2xl bg-white/5 px-3 py-2 font-display text-lg text-white">
            {game.homeAbbreviation}
          </span>
        </div>
        <span className="rounded-full border border-success/20 bg-success/10 px-3 py-1 text-xs uppercase tracking-[0.2em] text-success">
          {game.status}
        </span>
      </div>

      <h2 className="font-display text-2xl text-white">
        {game.awayTeam} at {game.homeTeam}
      </h2>
      <p className="mt-2 text-sm leading-6 text-muted">{game.headline}</p>

      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div className="rounded-2xl bg-black/20 p-3">
          <p className="text-muted">Tipoff</p>
          <p className="mt-1 font-semibold text-ink">{game.tipoff}</p>
        </div>
        <div className="rounded-2xl bg-black/20 p-3">
          <p className="text-muted">Broadcast</p>
          <p className="mt-1 font-semibold text-ink">{game.broadcast}</p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div className="rounded-2xl bg-black/20 p-3">
          <p className="text-muted">{game.awayAbbreviation} Record</p>
          <p className="mt-1 font-semibold text-white">{game.awayRecord}</p>
        </div>
        <div className="rounded-2xl bg-black/20 p-3">
          <p className="text-muted">{game.homeAbbreviation} Record</p>
          <p className="mt-1 font-semibold text-white">{game.homeRecord}</p>
        </div>
      </div>

      <p className="mt-4 text-sm text-electric">{game.predictionHook}</p>
      <p className="mt-5 font-semibold text-white">Open matchup analysis</p>
    </button>
  );
}

export function SlatePage({
  games,
  onOpenGame,
}: {
  games: SlateGame[];
  onOpenGame: (gameId: string) => void;
}) {
  return (
    <main className="min-h-screen bg-grid bg-[size:22px_22px] px-4 py-6 md:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <section className="panel overflow-hidden p-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="metric-chip mb-3">Basketball intelligence engine</p>
              <h1 className="font-display text-4xl text-white md:text-5xl">Today&apos;s NBA slate</h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-muted">
                Start with the games. Click any matchup to open its own page with projected score, player stat predictions, coaching adjustments, and tactical reasoning.
              </p>
            </div>
            <div className="rounded-3xl border border-white/10 bg-white/5 px-5 py-4">
              <p className="text-xs uppercase tracking-[0.3em] text-muted">Scheduled today</p>
              <p className="mt-1 font-display text-3xl text-white">{games.length}</p>
              <p className="text-sm text-electric">games ready</p>
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-3">
          {games.map((game) => (
            <SlateCard key={game.gameId} game={game} onOpen={onOpenGame} />
          ))}
        </section>
      </div>
    </main>
  );
}

