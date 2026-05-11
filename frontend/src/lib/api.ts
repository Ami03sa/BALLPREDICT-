import { mockPreview, mockSlate, mockSnapshot } from "./mockData";
import type { GamePreview, SlateGame, Snapshot } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

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
