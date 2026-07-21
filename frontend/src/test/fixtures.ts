import type {
  BettingSlip,
  BettingSlipCalendarResponse,
  BettingSlipStatsResponse,
  BettingSlipsDailyResponse,
  FixturesWithPredictionsPage,
  GlobalUpdateRunRead,
  ImportStatusResponse,
  ModelsVersionsResultsResponse,
  NextFixtureWithPrediction,
  SingleMatchValueResponse,
  TelegramBotEventsResponse,
  TelegramBotStatsResponse
} from "../types/api";

export const TODAY = "2026-07-21";

export const modelsCatalog: ModelsVersionsResultsResponse = {
  date: TODAY,
  last_updated_at: `${TODAY}T10:00:00Z`,
  last_run_id: 1,
  last_run_origin: "manual",
  versions: [
    {
      version: "v3",
      models: [
        {
          model: "logistic_regression",
          status: "ok",
          predictions_count: 10,
          slips_count: 9,
          data: {}
        },
        {
          model: "random_forest",
          status: "ok",
          predictions_count: 10,
          slips_count: 9,
          data: {}
        }
      ]
    },
    {
      version: "v2",
      models: [
        {
          model: "logistic_regression",
          status: "ok",
          predictions_count: 5,
          slips_count: 3,
          data: {}
        }
      ]
    }
  ]
};

export const importStatus: ImportStatusResponse = {
  next_fixtures_last_imported_at: `${TODAY}T08:00:00Z`,
  next_fixtures_imported_today: true,
  next_fixtures_max_date: "2026-07-28",
  next_fixtures_window_days: 7,
  next_fixtures_window_until: "2026-07-28",
  fixtures_last_match_date: "2026-07-20",
  fixtures_last_imported_at: `${TODAY}T08:00:00Z`
};

export const emptyValueAnalysis: SingleMatchValueResponse = {
  model_version: "v3",
  model_name: "logistic_regression",
  min_edge_percent: 0,
  items: [],
  total: 0,
  offset: 0,
  limit: 200,
  summary: {
    total: 0,
    play_count: 0,
    no_bet_count: 0,
    borderline_count: 0,
    avg_market_odds: null,
    avg_void_odds: null,
    avg_expected_roi: null
  },
  simulation: {
    stake: 1,
    play_bets: {
      bets_count: 0,
      resolved_count: 0,
      profit_loss_units: 0,
      roi_pct: null,
      hit_rate_pct: null,
      avg_market_odds: null,
      avg_void_odds: null
    },
    above_void: {
      bets_count: 0,
      resolved_count: 0,
      profit_loss_units: 0,
      roi_pct: null,
      hit_rate_pct: null,
      avg_market_odds: null,
      avg_void_odds: null
    },
    below_void: {
      bets_count: 0,
      resolved_count: 0,
      profit_loss_units: 0,
      roi_pct: null,
      hit_rate_pct: null,
      avg_market_odds: null,
      avg_void_odds: null
    },
    borderline_count: 0
  },
  warnings: []
};

export function makeFixture(
  overrides: Partial<NextFixtureWithPrediction> = {}
): NextFixtureWithPrediction {
  return {
    id: 1,
    event_key: 1001,
    event_date: TODAY,
    event_time: "15:30:00",
    event_first_player: "Player A",
    first_player_key: 11,
    event_second_player: "Player B",
    second_player_key: 22,
    tournament_name: "Test Open",
    tournament_key: 99,
    tournament_round: "R32",
    surface: "Hard",
    event_status: "Not Started",
    event_type_type: "Atp Singles",
    odds: null,
    imported_at: `${TODAY}T08:00:00Z`,
    week_start: TODAY,
    week_end: TODAY,
    source: "test",
    is_completed: false,
    moved_to_fixture_at: null,
    prediction: {
      event_key: 1001,
      model_version: "v3",
      model_name: "logistic_regression",
      predicted_at: `${TODAY}T09:00:00Z`,
      prob_player_1_win: 0.62,
      predicted_winner: "First Player",
      actual_winner: null,
      is_correct: null,
      predicted_winner_odds: 1.75,
      odds_bookmaker_count: 3,
      confidence: 0.62,
      features_available: true,
      warnings: []
    },
    prediction_warning: null,
    ...overrides
  };
}

export function makeFixturesPage(
  items: NextFixtureWithPrediction[] = [makeFixture()],
  total = items.length
): FixturesWithPredictionsPage {
  return { items, total, offset: 0, limit: 50 };
}

export const idleGlobalUpdate: GlobalUpdateRunRead = {
  id: 7,
  run_date: TODAY,
  origin: "manual",
  status: "completed",
  current_phase: null,
  progress_pct: 100,
  started_at: `${TODAY}T07:00:00Z`,
  finished_at: `${TODAY}T07:10:00Z`,
  duration_seconds: 600,
  force: true,
  versions_processed: 2,
  models_processed: 3,
  combinations_completed: 3,
  combinations_failed: 0,
  combinations_skipped: 0,
  fixtures_processed: 40,
  slips_generated: 27,
  errors: [],
  warnings: [],
  items: []
};

export const runningGlobalUpdate: GlobalUpdateRunRead = {
  ...idleGlobalUpdate,
  status: "running",
  current_phase: "predictions",
  progress_pct: 42,
  finished_at: null,
  duration_seconds: null
};

export function makeCalendar(date = TODAY): BettingSlipCalendarResponse {
  return {
    today: date,
    window_from: date,
    window_to: date,
    history_from: null,
    model_version: "v3",
    model_name: "logistic_regression",
    days: [
      {
        date,
        is_today: true,
        is_past: false,
        is_upcoming: false,
        has_slips: true,
        slip_count: 1,
        fixture_count: 4,
        candidate_pool_size: 4
      }
    ]
  };
}

export function makeSlip(overrides: Partial<BettingSlip> = {}): BettingSlip {
  return {
    id: "slip-1",
    slip_key: "play_easy",
    label: "Play facile",
    description: "3 picks PLAY",
    picks: [
      {
        event_key: 1001,
        event_date: TODAY,
        event_time: "15:30:00",
        tournament_name: "Test Open",
        surface: "Hard",
        player_1: "Player A",
        player_2: "Player B",
        predicted_winner: "First Player",
        predicted_winner_label: "Player A",
        model_prob: 0.62,
        market_prob: 0.55,
        edge: 0.07,
        odds: 1.9,
        void_odds: 1.61,
        edge_absolute: 0.29,
        edge_percent: 18,
        expected_roi: 0.18,
        suggested_min_edge_percent: 2,
        min_edge_percent: 2,
        value_decision: "PLAY",
        value_label: "PLAY",
        confidence: 0.62,
        pick_score: 1,
        pick_status: "pending",
        actual_winner_label: null,
        is_correct: null
      }
    ],
    pick_count: 1,
    combined_odds: 1.9,
    combined_probability_estimate: 0.62,
    potential_return: 19,
    potential_profit: 9,
    slip_status: "pending",
    picks_won: 0,
    picks_lost: 0,
    picks_pending: 1,
    picks_total: 1,
    resolved_combined_odds: null,
    theoretical_profit_if_won: 9,
    generated_at: `${TODAY}T09:00:00Z`,
    ...overrides
  };
}

export function makeDailySlips(date = TODAY): BettingSlipsDailyResponse {
  return {
    date,
    model_version: "v3",
    model_name: "logistic_regression",
    stake: 10,
    candidate_pool_size: 4,
    slips: [makeSlip()],
    warnings: []
  };
}

export function makeSlipStats(date = TODAY): BettingSlipStatsResponse {
  return {
    model_version: "v3",
    from_date: date,
    to_date: date,
    days: [],
    summary: {
      slips_total: 1,
      slips_won: 0,
      slips_lost: 0,
      slips_pending: 1,
      picks_total: 1,
      picks_won: 0,
      picks_lost: 0,
      picks_pending: 1,
      slip_win_rate_pct: null,
      pick_hit_rate_pct: null,
      theoretical_profit_units: 0,
      theoretical_roi_pct: null,
      by_profile: []
    }
  };
}

export const telegramStats: TelegramBotStatsResponse = {
  total_events: 12,
  unique_users: 4,
  events_today: 2,
  top_action: "/schedine",
  by_action: [{ action: "/schedine", count: 8 }],
  by_day: [{ day: TODAY, count: 2 }]
};

export const telegramEvents: TelegramBotEventsResponse = {
  total: 1,
  limit: 50,
  offset: 0,
  items: [
    {
      id: 1,
      created_at: `${TODAY}T11:00:00Z`,
      telegram_user_id: 42,
      chat_id: 42,
      username: "tester",
      first_name: "Test",
      last_name: "User",
      event_type: "command",
      action: "/schedine",
      raw_text: "/schedine",
      success: true,
      error_message: null
    }
  ]
};

export const futureExpiresAt = () => new Date(Date.now() + 60 * 60 * 1000).toISOString();
