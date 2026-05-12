import type { GamePreview, PlayerDetail, SlateGame, Snapshot } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export async function fetchSlate(): Promise<SlateGame[]> {
  const response = await fetch(`${API_BASE}/games/slate`);
  if (!response.ok) throw new Error(`Slate fetch failed: ${response.status}`);
  const data = await response.json();
  return data.map((game: any) => ({
    gameId: game.game_id,
    status: game.status,
    tipoff: game.tipoff,
    broadcast: game.broadcast,
    arena: game.arena,
    headline: game.headline,
    homeTeam: game.home_team,
    awayTeam: game.away_team,
    homeAbbreviation: game.home_abbreviation,
    awayAbbreviation: game.away_abbreviation,
    homeRecord: game.home_record,
    awayRecord: game.away_record,
    predictionHook: game.prediction_hook,
  }));
}

export async function fetchGamePreview(gameId: string): Promise<GamePreview> {
  const response = await fetch(`${API_BASE}/games/${gameId}/preview`);
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail ?? `Preview fetch failed: ${response.status}`);
  }
  const data = await response.json();
  return {
    gameId: data.game_id,
    status: data.status,
    tipoff: data.tipoff,
    broadcast: data.broadcast,
    arena: data.arena,
    headline: data.headline,
    homeTeam: {
      teamId: data.home_team.team_id,
      teamName: data.home_team.team_name,
      coachName: data.home_team.coach_name,
      offensiveRating: data.home_team.offensive_rating,
      defensiveRating: data.home_team.defensive_rating,
      pace: data.home_team.pace,
      threePointRate: data.home_team.three_point_rate,
      benchDepth: data.home_team.bench_depth,
    },
    awayTeam: {
      teamId: data.away_team.team_id,
      teamName: data.away_team.team_name,
      coachName: data.away_team.coach_name,
      offensiveRating: data.away_team.offensive_rating,
      defensiveRating: data.away_team.defensive_rating,
      pace: data.away_team.pace,
      threePointRate: data.away_team.three_point_rate,
      benchDepth: data.away_team.bench_depth,
    },
    playersToWatch: data.players_to_watch.map((player: any) => ({
      playerId: player.player_id,
      playerName: player.player_name,
      teamId: player.team_id,
      usageRate: player.usage_rate,
      momentumScore: player.momentum_score,
      fatigueIndex: player.fatigue_index,
      matchupDifficulty: player.matchup_difficulty,
    })),
    gameFactors: data.game_factors,
    predictionSummary: data.prediction_summary,
  };
}

export async function fetchSnapshot(gameId: string): Promise<Snapshot> {
  const response = await fetch(`${API_BASE}/games/${gameId}`);
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail ?? `Snapshot fetch failed: ${response.status}`);
  }
  const data = await response.json();
  return {
    gameId: data.game_id,
    quarter: data.quarter,
    clock: data.clock,
    homeTeam: {
      teamId: data.home_team.team_id,
      teamName: data.home_team.team_name,
      score: data.home_team.score ?? 0,
      finalScoreMean: data.home_team.final_score_mean,
      finalScoreCI: data.home_team.final_score_ci,
      pace: data.home_team.pace,
      offensiveRating: data.home_team.offensive_rating,
      defensiveRating: data.home_team.defensive_rating,
      winProbability: data.home_team.win_probability,
      projectedScore: data.home_team.projected_score,
    },
    awayTeam: {
      teamId: data.away_team.team_id,
      teamName: data.away_team.team_name,
      score: data.away_team.score ?? 0,
      finalScoreMean: data.away_team.final_score_mean,
      finalScoreCI: data.away_team.final_score_ci,
      pace: data.away_team.pace,
      offensiveRating: data.away_team.offensive_rating,
      defensiveRating: data.away_team.defensive_rating,
      winProbability: data.away_team.win_probability,
      projectedScore: data.away_team.projected_score,
    },
    playerProjections: data.player_projections.map((player: any) => ({
      playerId: player.player_id,
      playerName: player.player_name,
      teamId: player.team_id,
      rotationRole: player.rotation_role ?? "rotation",
      availabilityStatus: player.availability_status ?? "available",
      dnpReason: player.dnp_reason ?? null,
      momentumScore: player.momentum_score,
      fatigueIndex: player.fatigue_index,
      defensivePressure: player.defensive_pressure,
      liveStats: {
        points: player.live_stats.points,
        assists: player.live_stats.assists,
        rebounds: player.live_stats.rebounds,
        threesMade: player.live_stats.threes_made ?? player.live_stats["3pm"] ?? 0,
        turnovers: player.live_stats.turnovers ?? 0,
      },
      projectedStats: {
        mean: {
          points: player.projected_stats.mean.points,
          assists: player.projected_stats.mean.assists,
          rebounds: player.projected_stats.mean.rebounds,
          threesMade: player.projected_stats.mean.threes_made ?? player.projected_stats.mean["3pm"] ?? 0,
          turnovers: player.projected_stats.mean.turnovers ?? 0,
          usageRate: player.projected_stats.mean.usage_rate,
          fieldGoalPct: player.projected_stats.mean.field_goal_pct ?? 0,
        },
      },
      adjustments: player.adjustments,
    })),
    insights: data.insights,
    possessionFeed: data.possession_feed,
    winProbabilitySeries: data.win_probability_series,
  };
}

export async function fetchPlayerDetail(gameId: string, playerId: string): Promise<PlayerDetail> {
  const response = await fetch(`${API_BASE}/games/${gameId}/players/${playerId}`);
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail ?? `Player fetch failed: ${response.status}`);
  }
  const data = await response.json();
  return {
    gameId: data.game_id,
    playerId: data.player_id,
    playerName: data.player_name,
    teamId: data.team_id,
    teamName: data.team_name,
    opponentTeamName: data.opponent_team_name,
    coachCounterSummary: data.coach_counter_summary,
    projection: {
      playerId: data.projection.player_id,
      playerName: data.projection.player_name,
      teamId: data.projection.team_id,
      rotationRole: data.projection.rotation_role ?? "rotation",
      availabilityStatus: data.projection.availability_status ?? "available",
      dnpReason: data.projection.dnp_reason ?? null,
      momentumScore: data.projection.momentum_score,
      fatigueIndex: data.projection.fatigue_index,
      defensivePressure: data.projection.defensive_pressure,
      liveStats: {
        points: data.projection.live_stats.points,
        assists: data.projection.live_stats.assists,
        rebounds: data.projection.live_stats.rebounds,
        threesMade: data.projection.live_stats.threes_made ?? data.projection.live_stats["3pm"] ?? 0,
        turnovers: data.projection.live_stats.turnovers ?? 0,
      },
      projectedStats: {
        mean: {
          points: data.projection.projected_stats.mean.points,
          assists: data.projection.projected_stats.mean.assists,
          rebounds: data.projection.projected_stats.mean.rebounds,
          threesMade: data.projection.projected_stats.mean.threes_made ?? data.projection.projected_stats.mean["3pm"] ?? 0,
          turnovers: data.projection.projected_stats.mean.turnovers ?? 0,
          usageRate: data.projection.projected_stats.mean.usage_rate,
          fieldGoalPct: data.projection.projected_stats.mean.field_goal_pct ?? 0,
        },
      },
      adjustments: data.projection.adjustments,
    },
    quarterBreakdown: data.quarter_breakdown.map((row: any) => ({
      quarter: row.quarter,
      points: row.points,
      assists: row.assists,
      rebounds: row.rebounds,
      threesMade: row.threes_made,
    })),
    statProfile: data.stat_profile.map((row: any) => ({
      label: row.label,
      live: row.live,
      projected: row.projected,
    })),
    matchupFactors: data.matchup_factors,
    confidence: {
      floorPoints: data.confidence.floor_points,
      medianPoints: data.confidence.median_points,
      ceilingPoints: data.confidence.ceiling_points,
      pressure: data.confidence.pressure,
    },
    playerInsights: data.player_insights,
  };
}
