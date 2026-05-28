import { useState, useRef } from "react";
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
    return <span className="font-mono text-base font-bold text-white">{abbr}</span>;
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

function SlateCard({ game, onOpen }: { game: SlateGame; onOpen: (gameId: string) => void }) {
  const isUpcoming = (game.daysUntil ?? 0) > 0 || game.status === "upcoming";

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => !isUpcoming && onOpen(game.gameId)}
        disabled={isUpcoming}
        className={[
          "w-full border p-5 text-left transition",
          isUpcoming
            ? "border-white/5 bg-black/60 cursor-not-allowed opacity-60"
            : "border-white/10 bg-black hover:border-white/25 hover:bg-neutral-950",
        ].join(" ")}
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
          <div className="flex flex-col items-end gap-1">
            <span className="border border-white/20 px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-[0.4em] text-white">
              {isUpcoming ? (game.gameDate ?? "upcoming") : game.status}
            </span>
            {isUpcoming && (
              <span className="font-mono text-[9px] uppercase tracking-[0.3em] text-white/40">
                {game.tipoff}
              </span>
            )}
          </div>
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
            <p className="mt-1 font-mono font-bold text-white">{game.broadcast || "—"}</p>
          </div>
        </div>

        {/* Records */}
        <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
          <div>
            <p className="font-mono text-[9px] uppercase tracking-[0.4em] text-white">{game.awayAbbreviation} Record</p>
            <p className="mt-1 font-mono font-bold text-white">{game.awayRecord || "—"}</p>
          </div>
          <div>
            <p className="font-mono text-[9px] uppercase tracking-[0.4em] text-white">{game.homeAbbreviation} Record</p>
            <p className="mt-1 font-mono font-bold text-white">{game.homeRecord || "—"}</p>
          </div>
        </div>

        <p className="mt-4 text-xs text-white/60">{game.predictionHook}</p>

        {/* CTA */}
        <div className="mt-5 border-t border-white/20 pt-4">
          {isUpcoming ? (
            <p className="font-mono text-[10px] font-bold uppercase tracking-[0.5em] text-white/30">
              🔒 Prediction Unlocks Game Day
            </p>
          ) : (
            <p className="font-mono text-[10px] font-bold uppercase tracking-[0.5em] text-white">
              Open Analysis →
            </p>
          )}
        </div>
      </button>
    </div>
  );
}

// ── Date tab helpers ────────────────────────────────────────────────────────

function todayLabel(): string {
  return new Date().toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

type DateBucket = {
  daysUntil: number;
  label: string;      // e.g. "Wed May 28"
  sublabel: string;   // "Today" | "Tomorrow" | ""
  games: SlateGame[];
  locked: boolean;
};

function buildBuckets(games: SlateGame[]): DateBucket[] {
  // Group by daysUntil (0, 1, 2 …)
  const map = new Map<number, SlateGame[]>();
  for (const g of games) {
    const d = g.daysUntil ?? 0;
    if (!map.has(d)) map.set(d, []);
    map.get(d)!.push(g);
  }

  // Sort keys ascending
  const sorted = [...map.keys()].sort((a, b) => a - b);

  return sorted.map((d) => {
    const dayGames = map.get(d)!;
    // For the label use gameDate from any upcoming game, or build from today
    let label = "";
    if (d === 0) {
      label = todayLabel();
    } else {
      // Try to get it from the first game's gameDate
      const gd = dayGames[0]?.gameDate;
      label = gd ?? `+${d}d`;
    }
    return {
      daysUntil: d,
      label,
      sublabel: d === 0 ? "Today" : d === 1 ? "Tomorrow" : "",
      games: dayGames,
      locked: d > 0,
    };
  });
}

// ── Date Slider ─────────────────────────────────────────────────────────────

function DateSlider({
  buckets,
  selected,
  onSelect,
}: {
  buckets: DateBucket[];
  selected: number;
  onSelect: (daysUntil: number) => void;
}) {
  const stripRef = useRef<HTMLDivElement>(null);

  // Touch/mouse swipe state
  const dragStart = useRef<number | null>(null);

  const handlePointerDown = (e: React.PointerEvent) => {
    dragStart.current = e.clientX;
  };

  const handlePointerUp = (e: React.PointerEvent) => {
    if (dragStart.current === null) return;
    const diff = e.clientX - dragStart.current;
    dragStart.current = null;

    if (Math.abs(diff) < 30) return; // treat as click, not swipe

    const currentIdx = buckets.findIndex((b) => b.daysUntil === selected);
    if (diff < 0 && currentIdx < buckets.length - 1) {
      onSelect(buckets[currentIdx + 1].daysUntil);
    } else if (diff > 0 && currentIdx > 0) {
      onSelect(buckets[currentIdx - 1].daysUntil);
    }
  };

  if (buckets.length <= 1) return null;

  return (
    <div
      ref={stripRef}
      className="flex items-stretch gap-0 overflow-x-auto border border-white/10 select-none"
      style={{ scrollbarWidth: "none" }}
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerUp}
    >
      {buckets.map((bucket, i) => {
        const isActive = bucket.daysUntil === selected;
        return (
          <button
            key={bucket.daysUntil}
            type="button"
            onClick={() => onSelect(bucket.daysUntil)}
            className={[
              "relative flex flex-col items-center justify-center px-8 py-4 transition-all flex-1 min-w-[120px]",
              isActive
                ? "bg-white text-black"
                : bucket.locked
                ? "bg-black text-white/40 hover:text-white/60"
                : "bg-black text-white hover:bg-white/5",
              i < buckets.length - 1 ? "border-r border-white/10" : "",
            ].join(" ")}
          >
            {/* Lock icon for future dates */}
            {bucket.locked && (
              <span className={["font-mono text-[8px] mb-1", isActive ? "text-black/50" : "text-white/30"].join(" ")}>
                🔒
              </span>
            )}

            {/* Day label */}
            <span className={["font-mono text-[10px] font-bold uppercase tracking-[0.35em]", isActive ? "text-black" : ""].join(" ")}>
              {bucket.label}
            </span>

            {/* Sub-label: Today / Tomorrow */}
            {bucket.sublabel ? (
              <span className={["mt-0.5 font-mono text-[8px] uppercase tracking-[0.5em]", isActive ? "text-black/60" : "text-white/40"].join(" ")}>
                {bucket.sublabel}
              </span>
            ) : null}

            {/* Game count pip */}
            <span className={[
              "mt-2 font-mono text-xs font-bold",
              isActive ? "text-black" : bucket.locked ? "text-white/30" : "text-white/70",
            ].join(" ")}>
              {bucket.games.length} {bucket.games.length === 1 ? "game" : "games"}
            </span>

            {/* Active underline */}
            {isActive && (
              <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-black" />
            )}
          </button>
        );
      })}
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────────────

export function SlatePage({
  games,
  slateError,
  onOpenGame,
}: {
  games: SlateGame[];
  slateError?: string | null;
  onOpenGame: (gameId: string) => void;
}) {
  const buckets = buildBuckets(games);
  const [selectedDay, setSelectedDay] = useState<number>(0);

  const activeBucket = buckets.find((b) => b.daysUntil === selectedDay) ?? buckets[0];
  const visibleGames = activeBucket?.games ?? [];
  const isLockedDay = (selectedDay) > 0;

  return (
    <main className="min-h-screen bg-black px-4 py-6 md:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">

        {/* ── Header ──────────────────────────────────────────────────── */}
        <section className="border border-white/10 bg-black p-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <div className="flex items-center gap-4 mb-3">
                <img src="/logo.png" alt="BallTalk" className="h-20 w-20 object-contain" />
                <h1 className="font-mono text-5xl font-bold italic text-white md:text-6xl tracking-tighter">
                  BALLTALK<span className="text-white">.</span>
                </h1>
              </div>
              <p className="font-mono text-[10px] uppercase tracking-[0.6em] text-white mb-1">
                AI Prediction Model · NBA Slate
              </p>
              <div className="h-px w-32 bg-white/30 mb-4" />
              <p className="max-w-2xl text-xs leading-6 text-white">
                Click any matchup for AI-projected scores, player stat predictions, series momentum analysis, and coaching adjustments.
              </p>
            </div>

            {/* Stats block — updates with selected day */}
            <div className={["border px-6 py-5 transition-all", isLockedDay ? "border-white/5 opacity-50" : "border-white/10"].join(" ")}>
              <p className="font-mono text-[9px] uppercase tracking-[0.5em] text-white">
                {isLockedDay ? (activeBucket?.label ?? "Upcoming") : "Today"}
              </p>
              <p className="mt-2 font-mono text-4xl font-bold text-white">{visibleGames.length}</p>
              <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.4em] text-white">
                {isLockedDay ? "Scheduled" : "Games"}
              </p>
            </div>
          </div>
        </section>

        {slateError && (
          <section className="border border-red-900/40 bg-black px-5 py-4 font-mono text-sm text-red-400">
            Failed to load games: {slateError}
          </section>
        )}

        {/* ── Date Slider ─────────────────────────────────────────────── */}
        <DateSlider buckets={buckets} selected={selectedDay} onSelect={setSelectedDay} />

        {/* ── Locked day notice ─────────────────────────────────────── */}
        {isLockedDay && (
          <div className="border border-white/5 bg-white/[0.02] px-5 py-3 font-mono text-[10px] uppercase tracking-[0.4em] text-white/40 text-center">
            🔒 Predictions for {activeBucket?.label} unlock on game day
          </div>
        )}

        {/* ── Game Cards ──────────────────────────────────────────────── */}
        <section className="grid gap-4 xl:grid-cols-3">
          {visibleGames.map((game) => (
            <SlateCard key={game.gameId} game={game} onOpen={onOpenGame} />
          ))}
          {!slateError && visibleGames.length === 0 && (
            <p className="col-span-3 py-12 text-center font-mono text-xs uppercase tracking-[0.4em] text-white/40">
              No games scheduled.
            </p>
          )}
        </section>
      </div>
    </main>
  );
}
