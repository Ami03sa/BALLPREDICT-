import { useEffect, useRef, useState } from "react";
import { fetchSlate } from "./lib/api";
import { GameDetailPage } from "./pages/GameDetailPage";
import { PlayerDetailPage } from "./pages/PlayerDetailPage";
import { InsightPanel } from "./components/InsightPanel";
import type { SlateGame, Snapshot } from "./types/index";

type PlayerRoute = { gameId: string; playerId: string } | null;

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

function GameTabLogo({ teamId, abbr }: { teamId: string; abbr: string }) {
  const path = teamLogoPath(teamId);
  if (!path) return <span className="font-mono text-[10px] font-bold text-white">{abbr}</span>;
  return (
    <img
      src={path}
      alt={abbr}
      width={22}
      height={22}
      className="object-contain shrink-0"
      onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
    />
  );
}

function GameTabs({
  games,
  selectedId,
  onSelect,
}: {
  games: SlateGame[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const tabsRef = useRef<HTMLDivElement>(null);

  // Scroll active tab into view
  useEffect(() => {
    if (!tabsRef.current || !selectedId) return;
    const active = tabsRef.current.querySelector<HTMLButtonElement>("[data-active='true']");
    active?.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
  }, [selectedId]);

  if (games.length === 0) {
    return (
      <div className="border-b border-white/10 px-4 py-3">
        <p className="font-mono text-[10px] uppercase tracking-[0.4em] text-white/30">No games today</p>
      </div>
    );
  }

  return (
    <div
      ref={tabsRef}
      className="flex overflow-x-auto border-b border-white/10 bg-black shrink-0"
      style={{ scrollbarWidth: "none" }}
    >
      <style>{`div::-webkit-scrollbar { display: none; }`}</style>
      {games.map((game) => {
        const isActive = game.gameId === selectedId;
        return (
          <button
            key={game.gameId}
            type="button"
            data-active={isActive}
            onClick={() => onSelect(game.gameId)}
            className={`flex shrink-0 items-center gap-2 border-r border-white/10 px-4 py-3 transition
              ${isActive
                ? "border-b-2 border-b-white bg-white/5"
                : "border-b-2 border-b-transparent hover:bg-white/5"
              }`}
          >
            <GameTabLogo teamId={game.awayAbbreviation} abbr={game.awayAbbreviation} />
            <span className="font-mono text-[9px] font-bold text-white/40">@</span>
            <GameTabLogo teamId={game.homeAbbreviation} abbr={game.homeAbbreviation} />
            <div className="ml-1 flex flex-col items-start gap-0.5">
              <span className="font-mono text-[10px] font-bold uppercase tracking-[0.1em] text-white whitespace-nowrap">
                {game.awayAbbreviation} @ {game.homeAbbreviation}
              </span>
              <span className="font-mono text-[9px] uppercase tracking-[0.15em] text-white/40 whitespace-nowrap">
                {game.status === "scheduled" ? game.tipoff : game.status}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function EmptyCenter() {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="text-center">
        <img src="/logo.png" alt="BALLTALK" className="mx-auto mb-6 h-16 w-16 object-contain opacity-20" />
        <p className="font-mono text-[10px] uppercase tracking-[0.5em] text-white/25">
          Select a game above
        </p>
      </div>
    </div>
  );
}

function ChatOverlay({
  insights,
  onClose,
}: {
  insights: Snapshot["insights"] | null;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-end">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />
      {/* Panel slides up from bottom-right */}
      <div
        className="relative mb-24 mr-6 w-full max-w-sm max-h-[70vh] overflow-y-auto border border-white/20 bg-black shadow-2xl"
        style={{ animation: "slideUp 0.2s ease-out" }}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-white/10 bg-black px-4 py-3">
          <div className="flex items-center gap-2">
            <img src="/logo.png" alt="BallTalk" className="h-5 w-5 object-contain" />
            <span className="font-mono text-xs font-bold uppercase tracking-[0.3em] text-white">BallTalk AI</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="font-mono text-xs text-white/30 transition hover:text-white"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        {insights && insights.length > 0 ? (
          <div className="p-4">
            <InsightPanel
              insights={insights}
              title="AI Insights"
              subtitle="Game analysis"
            />
          </div>
        ) : (
          <div className="flex items-center justify-center p-10">
            <p className="font-mono text-[10px] uppercase tracking-[0.4em] text-white/25 text-center">
              Select a game to<br />see AI insights
            </p>
          </div>
        )}
      </div>

      <style>{`
        @keyframes slideUp {
          from { opacity: 0; transform: translateY(16px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}

function App() {
  const [games, setGames] = useState<SlateGame[]>([]);
  const [slateError, setSlateError] = useState<string | null>(null);
  const [selectedGameId, setSelectedGameId] = useState<string | null>(null);
  const [playerRoute, setPlayerRoute] = useState<PlayerRoute>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [gameInsights, setGameInsights] = useState<Snapshot["insights"] | null>(null);

  const loadSlate = () => {
    fetchSlate()
      .then((data) => { setGames(data); setSlateError(null); })
      .catch((err: Error) => setSlateError(err.message));
  };

  useEffect(() => { loadSlate(); }, []);

  // Refresh at midnight
  useEffect(() => {
    const now = new Date();
    const midnight = new Date(now);
    midnight.setHours(24, 0, 10, 0);
    const t = setTimeout(loadSlate, midnight.getTime() - now.getTime());
    return () => clearTimeout(t);
  }, []);

  const todayGames = games.filter((g) => (g.daysUntil ?? 0) === 0);

  // Auto-select first game once slate loads
  useEffect(() => {
    if (todayGames.length > 0 && !selectedGameId) {
      setSelectedGameId(todayGames[0].gameId);
    }
  }, [todayGames.length, selectedGameId]);

  // Clear insights when game changes
  useEffect(() => {
    setGameInsights(null);
  }, [selectedGameId]);

  function selectGame(id: string) {
    setSelectedGameId(id);
    setPlayerRoute(null);
  }

  // Player detail is full-screen overlay
  if (playerRoute) {
    return (
      <PlayerDetailPage
        gameId={playerRoute.gameId}
        playerId={playerRoute.playerId}
        onBackToGame={() => setPlayerRoute(null)}
      />
    );
  }

  return (
    <div className="flex flex-col bg-black" style={{ height: "100dvh" }}>

      {/* Top header */}
      <header className="flex shrink-0 items-center justify-between border-b border-white/10 bg-black px-4 py-2">
        <div className="flex items-center gap-3">
          <img src="/logo.png" alt="BALLTALK" className="h-7 w-7 object-contain" />
          <span className="font-mono text-base font-bold italic tracking-tighter text-white">
            BALLTALK<span className="text-white">.</span>
          </span>
        </div>
        <span className="font-mono text-[9px] uppercase tracking-[0.4em] text-white/30 hidden sm:block">
          AI Prediction Model · NBA
        </span>
      </header>

      {/* Scrollable game tabs */}
      {slateError ? (
        <div className="shrink-0 border-b border-white/10 px-4 py-2 font-mono text-xs text-red-400">
          {slateError}
        </div>
      ) : (
        <GameTabs games={todayGames} selectedId={selectedGameId} onSelect={selectGame} />
      )}

      {/* Main content: center column + right insights column */}
      <div className="flex min-h-0 flex-1">

        {/* Center column — game content */}
        <div className="min-w-0 flex-1 overflow-y-auto">
          {selectedGameId ? (
            <GameDetailPage
              key={selectedGameId}
              gameId={selectedGameId}
              onBack={() => setSelectedGameId(null)}
              onOpenPlayer={(playerId) => setPlayerRoute({ gameId: selectedGameId, playerId })}
              onSnapshotLoaded={(snap) => setGameInsights(snap.insights)}
              hideBackButton
            />
          ) : (
            <EmptyCenter />
          )}
        </div>

        {/* Right column — insights (hidden on small screens) */}
        <div className="hidden w-72 shrink-0 overflow-y-auto border-l border-white/10 xl:block">
          {gameInsights && gameInsights.length > 0 ? (
            <div className="p-4">
              <InsightPanel
                insights={gameInsights}
                title="AI Insights"
                subtitle="Game analysis"
              />
            </div>
          ) : (
            <div className="flex h-full items-center justify-center p-4">
              <p className="text-center font-mono text-[9px] uppercase tracking-[0.4em] text-white/20">
                Insights load<br />with game
              </p>
            </div>
          )}
        </div>
      </div>

      {/* BallTalk floating button */}
      <button
        type="button"
        onClick={() => setChatOpen((o) => !o)}
        className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-white shadow-xl transition hover:scale-105 active:scale-95"
        aria-label="BallTalk AI insights"
      >
        <img src="/logo.png" alt="BallTalk" className="h-9 w-9 object-contain" />
      </button>

      {/* Chat overlay */}
      {chatOpen && (
        <ChatOverlay
          insights={gameInsights}
          onClose={() => setChatOpen(false)}
        />
      )}
    </div>
  );
}

export default App;
