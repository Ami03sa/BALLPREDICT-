import { useEffect, useState } from "react";
import { fetchSlate } from "./lib/api";
import { mockSlate } from "./lib/mockData";
import { GameDetailPage } from "./pages/GameDetailPage";
import { SlatePage } from "./pages/SlatePage";
import type { SlateGame } from "./types";

type Route =
  | { name: "home" }
  | { name: "game"; gameId: string };

function getRouteFromLocation(pathname: string): Route {
  const parts = pathname.split("/").filter(Boolean);
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

  if (route.name === "game") {
    return <GameDetailPage gameId={route.gameId} onBack={goHome} />;
  }

  return <SlatePage games={games} onOpenGame={openGame} />;
}

export default App;
