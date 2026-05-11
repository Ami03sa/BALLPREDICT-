export type TeamProjection = {
  teamId: string;
  teamName: string;
  finalScoreMean: number;
  finalScoreCI: [number, number];
  pace: number;
  offensiveRating: number;
  defensiveRating: number;
  winProbability: number;
  projectedScore: [number, number, number, number];
};

export type Adjustment = {
  title: string;
  trigger: string;
  explanation: string;
  counters: string[];
  impact: Record<string, number>;
  side: "offense" | "defense" | "rotation" | "pace";
};

export type PlayerProjection = {
  playerId: string;
  playerName: string;
  teamId: string;
  momentumScore: number;
  fatigueIndex: number;
  defensivePressure: number;
  liveStats: {
    points: number;
    assists: number;
    rebounds: number;
    threesMade: number;
    turnovers: number;
  };
  projectedStats: {
    mean: {
      points: number;
      assists: number;
      rebounds: number;
      threesMade: number;
      turnovers: number;
      usageRate: number;
      fieldGoalPct: number;
    };
  };
  adjustments: Adjustment[];
};

export type Snapshot = {
  gameId: string;
  quarter: number;
  clock: string;
  homeTeam: TeamProjection;
  awayTeam: TeamProjection;
  playerProjections: PlayerProjection[];
  insights: {
    title: string;
    body: string;
    severity: "info" | "warning" | "advantage";
  }[];
  possessionFeed: {
    quarter: number;
    clock: string;
    summary: string;
    leverage: "low" | "medium" | "high";
  }[];
  winProbabilitySeries: {
    minute: number;
    home: number;
    away: number;
  }[];
};

export type SlateGame = {
  gameId: string;
  status: string;
  tipoff: string;
  broadcast: string;
  arena: string;
  headline: string;
  homeTeam: string;
  awayTeam: string;
  homeAbbreviation: string;
  awayAbbreviation: string;
  homeRecord: string;
  awayRecord: string;
  predictionHook: string;
};

export type GamePreview = {
  gameId: string;
  status: string;
  tipoff: string;
  broadcast: string;
  arena: string;
  headline: string;
  homeTeam: {
    teamId: string;
    teamName: string;
    coachName: string;
    offensiveRating: number;
    defensiveRating: number;
    pace: number;
    threePointRate: number;
    benchDepth: number;
  };
  awayTeam: {
    teamId: string;
    teamName: string;
    coachName: string;
    offensiveRating: number;
    defensiveRating: number;
    pace: number;
    threePointRate: number;
    benchDepth: number;
  };
  playersToWatch: {
    playerId: string;
    playerName: string;
    teamId: string;
    usageRate: number;
    momentumScore: number;
    fatigueIndex: number;
    matchupDifficulty: number;
  }[];
  gameFactors: string[];
  predictionSummary: string;
};

export type PlayerDetail = {
  gameId: string;
  playerId: string;
  playerName: string;
  teamId: string;
  teamName: string;
  opponentTeamName: string;
  coachCounterSummary: string;
  projection: PlayerProjection;
  quarterBreakdown: {
    quarter: string;
    points: number;
    assists: number;
    rebounds: number;
    threesMade: number;
  }[];
  statProfile: {
    label: string;
    live: number;
    projected: number;
  }[];
  matchupFactors: string[];
  confidence: {
    floorPoints: number;
    medianPoints: number;
    ceilingPoints: number;
    pressure: number;
  };
  playerInsights: {
    title: string;
    body: string;
    severity: "info" | "warning" | "advantage";
  }[];
};
