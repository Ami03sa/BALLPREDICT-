import { mockPlayerDetail, mockPreview, mockSlate, mockSnapshot } from "./mockData";
import type { GamePreview, PlayerDetail, SlateGame, Snapshot } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

function buildFallbackPlayerDetail(gameId: string, playerId: string): PlayerDetail {
  const player = mockSnapshot.playerProjections.find((entry) => entry.playerId === playerId) ?? mockPlayerDetail.projection;
  const teamName = player.teamId === "gsw" ? "Golden State Warriors" : "Dallas Mavericks";
  const opponentTeamName = player.teamId === "gsw" ? "Dallas Mavericks" : "Golden State Warriors";

  return {
    gameId,
    playerId: player.playerId,
    playerName: player.playerName,
    teamId: player.teamId,
    teamName,
    opponentTeamName,
    coachCounterSummary: `${opponentTeamName} is expected to reshape coverages around ${player.playerName}'s usage and shot diet.`,
    projection: player,
    quarterBreakdown: [
      {
        quarter: "Q1",
        points: Number((player.projectedStats.mean.points * 0.27).toFixed(1)),
        assists: Number((player.projectedStats.mean.assists * 0.24).toFixed(1)),
        rebounds: Number((player.projectedStats.mean.rebounds * 0.24).toFixed(1)),
        threesMade: Number((player.projectedStats.mean.threesMade * 0.28).toFixed(1)),
      },
      {
        quarter: "Q2",
        points: Number((player.projectedStats.mean.points * 0.23).toFixed(1)),
        assists: Number((player.projectedStats.mean.assists * 0.22).toFixed(1)),
        rebounds: Number((player.projectedStats.mean.rebounds * 0.22).toFixed(1)),
        threesMade: Number((player.projectedStats.mean.threesMade * 0.22).toFixed(1)),
      },
      {
        quarter: "Q3",
        points: Number((player.projectedStats.mean.points * 0.24).toFixed(1)),
        assists: Number((player.projectedStats.mean.assists * 0.25).toFixed(1)),
        rebounds: Number((player.projectedStats.mean.rebounds * 0.25).toFixed(1)),
        threesMade: Number((player.projectedStats.mean.threesMade * 0.24).toFixed(1)),
      },
      {
        quarter: "Q4",
        points: Number((player.projectedStats.mean.points * 0.26).toFixed(1)),
        assists: Number((player.projectedStats.mean.assists * 0.29).toFixed(1)),
        rebounds: Number((player.projectedStats.mean.rebounds * 0.29).toFixed(1)),
        threesMade: Number((player.projectedStats.mean.threesMade * 0.26).toFixed(1)),
      },
    ],
    statProfile: [
      { label: "Points", live: player.liveStats.points, projected: player.projectedStats.mean.points },
      { label: "Assists", live: player.liveStats.assists, projected: player.projectedStats.mean.assists },
      { label: "Rebounds", live: player.liveStats.rebounds, projected: player.projectedStats.mean.rebounds },
      { label: "3PM", live: player.liveStats.threesMade, projected: player.projectedStats.mean.threesMade },
      { label: "Turnovers", live: player.liveStats.turnovers, projected: player.projectedStats.mean.turnovers },
    ],
    matchupFactors: [
      `Usage load at ${(player.projectedStats.mean.usageRate * 100).toFixed(0)}%`,
      `${opponentTeamName} defensive attention`,
      "half-court shot quality",
      "help-side timing",
      "late-game creation burden",
    ],
    confidence: {
      floorPoints: Number((player.projectedStats.mean.points * 0.84).toFixed(1)),
      medianPoints: player.projectedStats.mean.points,
      ceilingPoints: Number((player.projectedStats.mean.points * 1.18).toFixed(1)),
      pressure: player.defensivePressure,
    },
    playerInsights: [
      {
        title: "Scoring Shape",
        body: `${player.playerName}'s projection is leaning on usage concentration and half-court shot creation rather than pure transition volume.`,
        severity: "advantage",
      },
      {
        title: "Defensive Response",
        body: `${opponentTeamName} is projected to change shell positioning and coverage pressure as ${player.playerName}'s efficiency climbs.`,
        severity: "warning",
      },
      {
        title: "Playmaking Spillover",
        body: "Extra defensive attention can move some output from raw scoring into assists and secondary creation.",
        severity: "info",
      },
    ],
  };
}

export async function fetchSlate(): Promise<SlateGame[]> {
  try {
    const response = await fetch(`${API_BASE}/games/slate`);
    if (!response.ok) {
      throw new Error("API unavailable");
    }
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
  } catch {
    return mockSlate;
  }
}

export async function fetchGamePreview(gameId: string): Promise<GamePreview> {
  try {
    const response = await fetch(`${API_BASE}/games/${gameId}/preview`);
    if (!response.ok) {
      throw new Error("API unavailable");
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
  } catch {
    return mockPreview;
  }
}

export async function fetchSnapshot(gameId: string): Promise<Snapshot> {
  try {
    const response = await fetch(`${API_BASE}/games/${gameId}`);
    if (!response.ok) {
      throw new Error("API unavailable");
    }
    const data = await response.json();
    return {
      gameId: data.game_id,
      quarter: data.quarter,
      clock: data.clock,
      homeTeam: {
        teamId: data.home_team.team_id,
        teamName: data.home_team.team_name,
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
  } catch {
    return mockSnapshot;
  }
}

export async function fetchPlayerDetail(gameId: string, playerId: string): Promise<PlayerDetail> {
  try {
    const response = await fetch(`${API_BASE}/games/${gameId}/players/${playerId}`);
    if (!response.ok) {
      throw new Error("API unavailable");
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
  } catch {
    return buildFallbackPlayerDetail(gameId, playerId);
  }
}
