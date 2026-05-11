import { useEffect, useState } from "react";
import { fetchSlate } from "./lib/api";
import { mockSlate } from "./lib/mockData";
import { GameDetailPage } from "./pages/GameDetailPage";
import { PlayerDetailPage } from "./pages/PlayerDetailPage";
import { SlatePage } from "./pages/SlatePage";
import type { SlateGame } from "./types";

type Route =
  | { name: "home" }
  | { name: "game"; gameId: string }
  | { name: "player"; gameId: string; playerId: string };

function getRouteFromLocation(pathname: string): Route {
  const parts = pathname.split("/").filter(Boolean);
  if (parts[0] === "game" && parts[1] && parts[2] === "player" && parts[3]) {
    return { name: "player", gameId: parts[1], playerId: parts[3] };
  }
  if (parts[0] === "game" && parts[1]) {
    return { name: "game", gameId: parts[1] };
  }
  return { name: "home" };
}

function App() {
  const [route, setRoute] = useState<Route>(() => getRouteFromLocation(window.location.pathname));
  const [games, setGames] = useState<SlateGame[]>(mockSlate);

  useEffect(() => {
    fetchSlate().then(setGames).catch(() => setGames(mockSlate));
  }, []);

  useEffect(() => {
    const onPopState = () => setRoute(getRouteFromLocation(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  function openGame(gameId: string) {
    window.history.pushState({}, "", `/game/${gameId}`);
    setRoute({ name: "game", gameId });
  }

  function goHome() {
    window.history.pushState({}, "", "/");
    setRoute({ name: "home" });
  }

  function openPlayer(gameId: string, playerId: string) {
    window.history.pushState({}, "", `/game/${gameId}/player/${playerId}`);
    setRoute({ name: "player", gameId, playerId });
  }

  if (route.name === "game") {
    return <GameDetailPage gameId={route.gameId} onBack={goHome} onOpenPlayer={(playerId) => openPlayer(route.gameId, playerId)} />;
  }

  if (route.name === "player") {
    return (
      <PlayerDetailPage
        gameId={route.gameId}
        playerId={route.playerId}
        onBackToGame={() => {
          window.history.pushState({}, "", `/game/${route.gameId}`);
          setRoute({ name: "game", gameId: route.gameId });
        }}
      />
    );
  }

  return <SlatePage games={games} onOpenGame={openGame} />;
}

export default App;
