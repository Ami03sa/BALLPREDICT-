/**
 * Fallback data used only when the backend is unreachable.
 * All projected stats are 0 — projections are computed server-side.
 * Rosters reflect the 2024-25 NBA season (Luka Doncic traded to LAL Feb 2025).
 */
import type { GamePreview, PlayerDetail, SlateGame, Snapshot } from "../types";

export const mockSlate: SlateGame[] = [
  {
    gameId: "lal-gsw-demo",
    status: "scheduled",
    tipoff: "7:30 PM ET",
    broadcast: "ESPN",
    arena: "Crypto.com Arena",
    headline: "Lakers vs Warriors — connect to the server for live data.",
    homeTeam: "Los Angeles Lakers",
    awayTeam: "Golden State Warriors",
    homeAbbreviation: "LAL",
    awayAbbreviation: "GSW",
    homeRecord: "--",
    awayRecord: "--",
    predictionHook: "Live game data unavailable. Start the backend server to load today's NBA slate.",
  },
];

export const mockPreview: GamePreview = {
  gameId: "lal-gsw-demo",
  status: "scheduled",
  tipoff: "7:30 PM ET",
  broadcast: "ESPN",
  arena: "Crypto.com Arena",
  headline: "Lakers vs Warriors — connect to the server for live data.",
  homeTeam: {
    teamId: "lal",
    teamName: "Los Angeles Lakers",
    coachName: "JJ Redick",
    offensiveRating: 114.0,
    defensiveRating: 114.0,
    pace: 98.0,
    threePointRate: 0.39,
    benchDepth: 0.50,
  },
  awayTeam: {
    teamId: "gsw",
    teamName: "Golden State Warriors",
    coachName: "Steve Kerr",
    offensiveRating: 114.0,
    defensiveRating: 114.0,
    pace: 98.0,
    threePointRate: 0.42,
    benchDepth: 0.50,
  },
  playersToWatch: [
    {
      playerId: "luka",
      playerName: "Luka Doncic",
      teamId: "lal",
      usageRate: 0.35,
      momentumScore: 0.65,
      fatigueIndex: 0.15,
      matchupDifficulty: 0.50,
    },
    {
      playerId: "ad",
      playerName: "Anthony Davis",
      teamId: "lal",
      usageRate: 0.28,
      momentumScore: 0.60,
      fatigueIndex: 0.18,
      matchupDifficulty: 0.55,
    },
    {
      playerId: "steph",
      playerName: "Stephen Curry",
      teamId: "gsw",
      usageRate: 0.31,
      momentumScore: 0.62,
      fatigueIndex: 0.12,
      matchupDifficulty: 0.55,
    },
  ],
  gameFactors: ["pace pressure", "lineup staggering", "half-court shot creation", "weak-side help timing", "rest advantage"],
  predictionSummary: "Backend server is offline. Start the server to load live NBA data and projections.",
};

const _zeroStats = {
  points: 0,
  assists: 0,
  rebounds: 0,
  threesMade: 0,
  turnovers: 0,
  usageRate: 0,
  fieldGoalPct: 0,
};

export const mockSnapshot: Snapshot = {
  gameId: "lal-gsw-demo",
  quarter: 0,
  clock: "12:00",
  homeTeam: {
    teamId: "lal",
    teamName: "Los Angeles Lakers",
    finalScoreMean: 0,
    finalScoreCI: [0, 0],
    pace: 98.0,
    offensiveRating: 114.0,
    defensiveRating: 114.0,
    winProbability: 0.5,
    projectedScore: [0, 0, 0, 0],
  },
  awayTeam: {
    teamId: "gsw",
    teamName: "Golden State Warriors",
    finalScoreMean: 0,
    finalScoreCI: [0, 0],
    pace: 98.0,
    offensiveRating: 114.0,
    defensiveRating: 114.0,
    winProbability: 0.5,
    projectedScore: [0, 0, 0, 0],
  },
  playerProjections: [
    {
      playerId: "luka",
      playerName: "Luka Doncic",
      teamId: "lal",
      momentumScore: 0.65,
      fatigueIndex: 0.15,
      defensivePressure: 0.55,
      liveStats: { points: 0, assists: 0, rebounds: 0, threesMade: 0, turnovers: 0 },
      projectedStats: { mean: _zeroStats },
      adjustments: [],
    },
    {
      playerId: "ad",
      playerName: "Anthony Davis",
      teamId: "lal",
      momentumScore: 0.60,
      fatigueIndex: 0.18,
      defensivePressure: 0.50,
      liveStats: { points: 0, assists: 0, rebounds: 0, threesMade: 0, turnovers: 0 },
      projectedStats: { mean: _zeroStats },
      adjustments: [],
    },
    {
      playerId: "steph",
      playerName: "Stephen Curry",
      teamId: "gsw",
      momentumScore: 0.62,
      fatigueIndex: 0.12,
      defensivePressure: 0.52,
      liveStats: { points: 0, assists: 0, rebounds: 0, threesMade: 0, turnovers: 0 },
      projectedStats: { mean: _zeroStats },
      adjustments: [],
    },
  ],
  insights: [
    {
      title: "Backend Offline",
      body: "Start the backend server to load today's real NBA games, live scores, and player stats.",
      severity: "warning",
    },
  ],
  possessionFeed: [],
  winProbabilitySeries: [{ minute: 0, home: 0.5, away: 0.5 }],
};

export const mockPlayerDetail: PlayerDetail = {
  gameId: "lal-gsw-demo",
  playerId: "luka",
  playerName: "Luka Doncic",
  teamId: "lal",
  teamName: "Los Angeles Lakers",
  opponentTeamName: "Golden State Warriors",
  coachCounterSummary: "Live data unavailable — start the backend server to load projections.",
  projection: mockSnapshot.playerProjections[0],
  quarterBreakdown: [
    { quarter: "Q1", points: 0, assists: 0, rebounds: 0, threesMade: 0 },
    { quarter: "Q2", points: 0, assists: 0, rebounds: 0, threesMade: 0 },
    { quarter: "Q3", points: 0, assists: 0, rebounds: 0, threesMade: 0 },
    { quarter: "Q4", points: 0, assists: 0, rebounds: 0, threesMade: 0 },
  ],
  statProfile: [
    { label: "Points", live: 0, projected: 0 },
    { label: "Assists", live: 0, projected: 0 },
    { label: "Rebounds", live: 0, projected: 0 },
    { label: "3PM", live: 0, projected: 0 },
    { label: "Turnovers", live: 0, projected: 0 },
  ],
  matchupFactors: ["Live data unavailable"],
  confidence: { floorPoints: 0, medianPoints: 0, ceilingPoints: 0, pressure: 0.5 },
  playerInsights: [
    {
      title: "Backend Offline",
      body: "Start the backend server to load today's real NBA games, rosters, and live scores.",
      severity: "warning",
    },
  ],
};
