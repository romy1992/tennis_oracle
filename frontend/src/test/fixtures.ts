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
  TelegramBotStatsResponse,
  TelegramFeedbackListResponse,
  TelegramUserListResponse,
  PublishedPredictionListResponse,
  PublishedLiveStatsSummary,
  LiveBetaDashboardResponse,
  PublishedSettledTip,
  WeeklyBetaReport,
  SubscriptionDashboardSummaryResponse,
  SubscriptionDashboardUserListResponse,
  SubscriptionDashboardEventListResponse
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

export const telegramUsers: TelegramUserListResponse = {
  total: 1,
  limit: 50,
  offset: 0,
  items: [
    {
      id: 1,
      telegram_user_id: 42,
      chat_id: 42,
      username: "tester",
      first_name: "Test",
      last_name: "User",
      status: "invited",
      invite_origin: "beta_wave1",
      first_access_at: `${TODAY}T10:00:00Z`,
      last_access_at: `${TODAY}T11:00:00Z`,
      terms_accepted: false,
      terms_accepted_at: null,
      terms_version: null,
      notifications_enabled: true,
      notify_predictions: true,
      notify_results: true,
      notify_empty_day: false,
      created_at: `${TODAY}T10:00:00Z`,
      updated_at: `${TODAY}T11:00:00Z`
    }
  ]
};

export const telegramFeedback: TelegramFeedbackListResponse = {
  total: 1,
  limit: 50,
  offset: 0,
  items: [
    {
      id: 7,
      telegram_user_id: 42,
      username: "tester",
      first_name: "Test",
      last_name: "User",
      category: "bug",
      rating: 4,
      message: "La schedina di oggi non si apre.",
      status: "new",
      created_at: `${TODAY}T12:00:00Z`,
      updated_at: `${TODAY}T12:00:00Z`
    }
  ]
};

export const publishedPredictions: PublishedPredictionListResponse = {
  total: 1,
  limit: 50,
  offset: 0,
  items: [
    {
      id: 1,
      publication_id: "pub-1111-2222-3333",
      content_version: 1,
      previous_version_id: null,
      event_key: 9001,
      selection: "Player A",
      model_version: "v3",
      model_name: "logistic_regression",
      probability: 0.62,
      odds: 1.85,
      void_odds: 1.6129,
      edge: 14.7,
      publication_odds: 1.85,
      publication_bookmaker: "book_a",
      closing_odds: 1.72,
      closing_bookmaker: "book_a",
      no_vig_publication_prob: 0.54,
      no_vig_closing_prob: 0.57,
      clv_pct: 7.5581,
      clv_prob_delta_pct: 3,
      clv_available: true,
      unit_stake: 1,
      published_at: `${TODAY}T10:30:00Z`,
      publication_source: "admin_api",
      initial_status: "published",
      content_hash: "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
      player_1_name: "Player A",
      player_2_name: "Player B",
      tournament_name: "Test Open",
      event_date: TODAY,
      event_time: "15:00:00",
      match_prediction_id: null,
      betting_slip_pick_id: null,
      is_latest: true,
      match_started: false
    }
  ]
};

export const publishedLiveStats: PublishedLiveStatsSummary = {
  source: "published_prediction",
  latest_only: true,
  from_date: null,
  to_date: null,
  event_date_from: null,
  event_date_to: null,
  model_version: null,
  model_name: null,
  publication_source: null,
  tournament_name: null,
  surface: null,
  odds_band: null,
  predictions_total: 4,
  closed: 2,
  open: 1,
  void: 1,
  won: 1,
  lost: 1,
  hit_rate_pct: 50,
  stake_total: 5,
  stake_settled: 3,
  profit: -1,
  roi_pct: -33.3333,
  yield_pct: -33.3333,
  avg_odds: 2.125,
  max_drawdown: 2,
  max_winning_streak: 1,
  max_losing_streak: 1,
  clv_count: 3,
  clv_missing: 1,
  clv_coverage_pct: 75,
  clv_avg_pct: 2.4,
  clv_median_pct: 1.8,
  clv_positive_pct: 66.6667,
  clv_avg_prob_delta_pct: 1.2,
  by_model: [
    {
      key: "v3|logistic_regression",
      label: "v3 / logistic_regression",
      predictions_total: 3,
      closed: 2,
      open: 0,
      void: 1,
      won: 1,
      lost: 1,
      hit_rate_pct: 50,
      stake_total: 4,
      stake_settled: 3,
      profit: -1,
      roi_pct: -33.3333,
      yield_pct: -33.3333,
      avg_odds: 2.1667,
      clv_count: 2,
      clv_missing: 1,
      clv_coverage_pct: 66.6667,
      clv_avg_pct: 1.7,
      clv_median_pct: 1.7,
      clv_positive_pct: 50,
      clv_avg_prob_delta_pct: 0.9
    }
  ],
  by_odds: [],
  by_edge: [],
  by_surface: [
    {
      key: "Clay",
      label: "Clay",
      predictions_total: 3,
      closed: 2,
      open: 0,
      void: 1,
      won: 1,
      lost: 1,
      hit_rate_pct: 50,
      stake_total: 4,
      stake_settled: 3,
      profit: -1,
      roi_pct: -33.3333,
      yield_pct: -33.3333,
      avg_odds: 2.1667,
      clv_count: 2,
      clv_missing: 1,
      clv_coverage_pct: 66.6667,
      clv_avg_pct: 1.7,
      clv_median_pct: 1.7,
      clv_positive_pct: 50,
      clv_avg_prob_delta_pct: 0.9
    }
  ],
  by_period: [
    {
      key: "2026-06",
      label: "2026-06",
      predictions_total: 3,
      closed: 2,
      open: 0,
      void: 1,
      won: 1,
      lost: 1,
      hit_rate_pct: 50,
      stake_total: 4,
      stake_settled: 3,
      profit: -1,
      roi_pct: -33.3333,
      yield_pct: -33.3333,
      avg_odds: 2.1667,
      clv_count: 2,
      clv_missing: 1,
      clv_coverage_pct: 66.6667,
      clv_avg_pct: 1.7,
      clv_median_pct: 1.7,
      clv_positive_pct: 50,
      clv_avg_prob_delta_pct: 0.9
    }
  ]
};

const settledTipBase = publishedPredictions.items[0];

export const liveBetaSettledTip: PublishedSettledTip = {
  ...settledTipBase,
  outcome: "pending",
  profit: 0,
  stake_settled: 0,
  surface: "Hard"
};

export const liveBetaDashboard: LiveBetaDashboardResponse = {
  mode: "live",
  generated_at: `${TODAY}T12:00:00`,
  from_date: "2026-04-22",
  to_date: TODAY,
  model_version: null,
  model_name: null,
  tournament_name: null,
  surface: null,
  odds_band: null,
  latest_only: true,
  pipeline: {
    mode: "live",
    active_run: null,
    latest_run: idleGlobalUpdate,
    last_updated_at: idleGlobalUpdate.finished_at,
    import_status: importStatus
  },
  live_stats: publishedLiveStats,
  published_today: [liveBetaSettledTip],
  open_predictions: [liveBetaSettledTip],
  closed_predictions: [
    {
      ...settledTipBase,
      id: settledTipBase.id + 1,
      outcome: "won",
      profit: 1,
      stake_settled: 1,
      surface: "Clay",
      match_started: true
    }
  ],
  bot_usage: telegramStats,
  data_completeness: {
    tips_total: 4,
    tips_with_odds: 4,
    tips_with_odds_pct: 100,
    tips_with_event_date: 4,
    tips_with_event_date_pct: 100,
    tips_with_match_context: 4,
    tips_with_match_context_pct: 100,
    distinct_event_keys: 4,
    event_keys_with_odds_snapshot: 2,
    odds_snapshot_coverage_pct: 50,
    snapshots_opening: 2,
    snapshots_observed: 1,
    snapshots_publication: 1,
    snapshots_closing: 0,
    tips_with_closing_snapshot: 0,
    tips_with_closing_snapshot_pct: 0,
    closing_odds_status: "missing",
    closing_odds_note:
      "Closing odds: senza un job dedicato di cattura pre-kickoff frequente, il closing è best-effort."
  },
  publication_health: {
    empty_reason: "ok",
    message: "Registro live operativo.",
    live_publication_enabled: true,
    public_model_version: "v3",
    public_model_name: "logistic_regression",
    validation_started_at: `${TODAY}T08:00:00`,
    last_run_publications_created: 2,
    last_run_duplicates_skipped: 0,
    last_run_excluded: 1,
    last_run_candidates: 5,
    last_run_publication_errors: []
  },
  recent_errors: [
    {
      source: "global_update",
      created_at: `${TODAY}T09:00:00`,
      message: "pipeline boom",
      detail: "run_id=7 status=completed_with_errors"
    }
  ],
  backtest: {
    mode: "backtest",
    included_in_live_kpis: false,
    message:
      "I KPI LIVE della beta usano solo il registro immutabile delle pubblicazioni. Metriche di training/backtest e previsioni operative restano sulle pagine dedicate.",
    related_paths: ["/prediction-stats", "/betting-slip-model-stats", "/published-live-stats"]
  }
};

function makePeriod(weekStart: string, weekEnd: string, weekLabel: string) {
  return {
    week_start: weekStart,
    week_end: weekEnd,
    week_label: weekLabel,
    users: {
      total_users: 12,
      active_users: 8,
      new_users: 3,
      by_status: { active: 9, invited: 2, suspended: 1 },
      retention_cohort: 4,
      retention_retained: 2,
      retention_pct: 50
    },
    command_usage: {
      total_events: 40,
      unique_users: 7,
      by_action: [
        { action: "/start", count: 10 },
        { action: "/oggi", count: 15 }
      ]
    },
    live_tips: {
      predictions_published: 6,
      closed: 4,
      open: 2,
      won: 2,
      lost: 2,
      void: 0,
      hit_rate_pct: 50,
      stake_settled: 4,
      profit: 0.5,
      roi_pct: 12.5,
      yield_pct: 12.5,
      max_drawdown: 1.2
    },
    pipeline: {
      runs_total: 7,
      runs_failed: 0,
      runs_completed_with_errors: 1,
      runs_interrupted: 0,
      combinations_failed: 1,
      error_messages: ["run#7: combo failed"]
    },
    notifications: {
      total: 20,
      sent: 18,
      failed: 2,
      skipped: 0,
      pending: 0,
      by_kind_failed: { predictions: 2 }
    },
    feedback: {
      total: 3,
      avg_rating: 4.0,
      by_status: { new: 2, resolved: 1 },
      by_category: { bug: 1, ux: 2 }
    }
  };
}

export const weeklyBetaReport: WeeklyBetaReport = {
  id: 1,
  week_start: "2026-07-13",
  week_end: "2026-07-19",
  week_label: "2026-W29",
  payload: {
    current: makePeriod("2026-07-13", "2026-07-19", "2026-W29"),
    previous: {
      ...makePeriod("2026-07-06", "2026-07-12", "2026-W28"),
      users: {
        ...makePeriod("2026-07-06", "2026-07-12", "2026-W28").users,
        total_users: 10,
        active_users: 6,
        new_users: 2,
        retention_pct: 40
      },
      live_tips: {
        ...makePeriod("2026-07-06", "2026-07-12", "2026-W28").live_tips,
        predictions_published: 4,
        roi_pct: 5
      }
    },
    wow: {
      total_users: { current: 12, previous: 10, delta: 2, delta_pct: 20 },
      active_users: { current: 8, previous: 6, delta: 2, delta_pct: 33.3333 },
      new_users: { current: 3, previous: 2, delta: 1, delta_pct: 50 },
      retention_pct: { current: 50, previous: 40, delta: 10, delta_pct: 25 },
      total_events: { current: 40, previous: 30, delta: 10, delta_pct: 33.3333 },
      predictions_published: { current: 6, previous: 4, delta: 2, delta_pct: 50 },
      roi_pct: { current: 12.5, previous: 5, delta: 7.5, delta_pct: 150 },
      yield_pct: { current: 12.5, previous: 5, delta: 7.5, delta_pct: 150 },
      max_drawdown: { current: 1.2, previous: 1.2, delta: 0, delta_pct: 0 },
      pipeline_errors: { current: 1, previous: 0, delta: 1, delta_pct: null },
      notifications_failed: { current: 2, previous: 1, delta: 1, delta_pct: 100 },
      feedback_total: { current: 3, previous: 1, delta: 2, delta_pct: 200 }
    },
    notes: ["Settimana ISO (lunedì–domenica) in calendario Europe/Rome."]
  },
  telegram_status: "sent",
  telegram_error: null,
  telegram_sent_at: `${TODAY}T10:00:00`,
  generated_at: `${TODAY}T09:30:00`,
  generated_by: "job"
};

export const weeklyBetaReports = {
  total: 1,
  limit: 20,
  offset: 0,
  items: [
    {
      id: weeklyBetaReport.id,
      week_start: weeklyBetaReport.week_start,
      week_end: weeklyBetaReport.week_end,
      week_label: weeklyBetaReport.week_label,
      telegram_status: weeklyBetaReport.telegram_status,
      telegram_sent_at: weeklyBetaReport.telegram_sent_at,
      generated_at: weeklyBetaReport.generated_at,
      generated_by: weeklyBetaReport.generated_by,
      total_users: 12,
      active_users: 8,
      new_users: 3,
      retention_pct: 50,
      predictions_published: 6,
      roi_pct: 12.5,
      notifications_failed: 2,
      feedback_total: 3
    }
  ]
};

export const futureExpiresAt = () => new Date(Date.now() + 60 * 60 * 1000).toISOString();

export const walkForwardRun = {
  id: 11,
  status: "completed",
  mode: "expanding",
  initial_train_days: 365,
  test_days: 90,
  step_days: 90,
  min_train_rows: 200,
  min_test_rows: 50,
  embargo_days: 0,
  edge_threshold: 0.03,
  random_state: 42,
  versions_requested: "v2,v3",
  origin: "manual",
  started_at: `${TODAY}T08:00:00`,
  finished_at: `${TODAY}T08:20:00`,
  duration_seconds: 1200,
  report_path: "backend/data/reports/walk_forward/walk_forward_latest.json",
  summary: {
    folds_completed: 3,
    folds_skipped: 1,
    folds_errors: 0,
    leakage_flags_total: 0,
    official_metrics_shuffled: false,
    public_model_unchanged: true,
    holdout_metrics_unchanged: true,
    official_contenders: [
      "market_favorite",
      "market_no_vig",
      "atp_ranking",
      "elo",
      "logistic_regression",
      "random_forest"
    ],
    official_sample_mismatch_folds: 1,
    versions_detail: [
      {
        model_version: "v2",
        aggregate_metrics: {
          logistic_regression: {
            folds_completed: 1,
            accuracy: { mean: 0.61, std: 0, n: 1 }
          },
          official_benchmarks: {
            logistic_regression: {
              accuracy: { mean: 0.61, std: 0, n: 1 },
              log_loss: { mean: 0.66, std: 0, n: 1 },
              brier_score: { mean: 0.22, std: 0, n: 1 },
              roi: { mean: 0.05, std: 0, n: 1 },
              yield: { mean: 0.05, std: 0, n: 1 },
              max_drawdown: { mean: 1.2, std: 0, n: 1 },
              clv_pct: { mean: null, std: null, n: 0 }
            },
            market_no_vig: {
              accuracy: { mean: 0.58, std: 0, n: 1 },
              log_loss: { mean: 0.68, std: 0, n: 1 },
              brier_score: { mean: 0.24, std: 0, n: 1 },
              roi: { mean: 0.01, std: 0, n: 1 },
              yield: { mean: 0.01, std: 0, n: 1 },
              max_drawdown: { mean: 1.8, std: 0, n: 1 },
              clv_pct: { mean: null, std: null, n: 0 }
            }
          }
        },
        holdout_comparison: {
          source: "holdout_baseline",
          models: { logistic_regression: { accuracy: 0.63, roc_auc: 0.66 } }
        },
        leakage_flags: []
      }
    ]
  },
  error_message: null,
  created_at: `${TODAY}T07:55:00`,
  created_by: "admin_api",
  folds: [
    {
      id: 101,
      run_id: 11,
      fold_index: 0,
      model_version: "v2",
      model_name: "logistic_regression",
      dataset_path: "backend/data/processed/tennis_winner_dataset_v2.csv",
      status: "completed",
      train_start: "2024-01-01",
      train_end: "2024-12-31",
      test_start: "2025-01-01",
      test_end: "2025-03-31",
      train_rows: 1200,
      test_rows: 300,
      feature_set: ["surface", "rank_diff", "elo_diff"],
      metrics: {
        accuracy: 0.61,
        roc_auc: 0.64,
        log_loss: 0.66,
        f1: 0.6,
        official_benchmark: {
          accuracy: 0.61,
          log_loss: 0.66,
          brier_score: 0.22,
          roi: 0.05,
          yield: 0.05,
          max_drawdown: 1.2,
          clv_pct: null
        }
      },
      market_benchmark: { market_accuracy: 0.58 },
      coverage: {
        train_rows: 1200,
        test_rows: 300,
        official_benchmark_sample: {
          rows_total_test: 300,
          rows_common_official: 300,
          rows_excluded_for_common_sample: 0,
          sample_mismatch_detected: false,
          missing_rows_by_contender: {}
        }
      },
      leakage_flags: [],
      skip_reason: null
    },
    {
      id: 103,
      run_id: 11,
      fold_index: 0,
      model_version: "v2",
      model_name: "market_no_vig",
      dataset_path: "backend/data/processed/tennis_winner_dataset_v2.csv",
      status: "completed",
      train_start: "2024-01-01",
      train_end: "2024-12-31",
      test_start: "2025-01-01",
      test_end: "2025-03-31",
      train_rows: 1200,
      test_rows: 300,
      feature_set: [],
      metrics: {
        official_benchmark: {
          accuracy: 0.58,
          log_loss: 0.68,
          brier_score: 0.24,
          roi: 0.01,
          yield: 0.01,
          max_drawdown: 1.8,
          clv_pct: null
        }
      },
      market_benchmark: { market_accuracy: 0.58 },
      coverage: {
        train_rows: 1200,
        test_rows: 300,
        official_benchmark_sample: {
          rows_total_test: 300,
          rows_common_official: 300,
          rows_excluded_for_common_sample: 0,
          sample_mismatch_detected: false,
          missing_rows_by_contender: {}
        }
      },
      leakage_flags: [],
      skip_reason: null
    },
    {
      id: 104,
      run_id: 11,
      fold_index: 1,
      model_version: "v3",
      model_name: "elo",
      dataset_path: "backend/data/processed/tennis_winner_dataset_v3.csv",
      status: "completed",
      train_start: "2024-01-01",
      train_end: "2025-03-31",
      test_start: "2025-04-01",
      test_end: "2025-06-30",
      train_rows: 1500,
      test_rows: 320,
      feature_set: [],
      metrics: {
        official_benchmark: {
          accuracy: 0.55,
          log_loss: 0.7,
          brier_score: 0.26,
          roi: -0.02,
          yield: -0.02,
          max_drawdown: 2.3,
          clv_pct: null
        }
      },
      market_benchmark: null,
      coverage: {
        train_rows: 1500,
        test_rows: 320,
        official_benchmark_sample: {
          rows_total_test: 320,
          rows_common_official: 290,
          rows_excluded_for_common_sample: 30,
          sample_mismatch_detected: true,
          missing_rows_by_contender: { atp_ranking: 30 }
        }
      },
      leakage_flags: [],
      skip_reason: null
    },
    {
      id: 102,
      run_id: 11,
      fold_index: 1,
      model_version: "v2",
      model_name: "random_forest",
      dataset_path: "backend/data/processed/tennis_winner_dataset_v2.csv",
      status: "skipped_insufficient_data",
      train_start: "2024-01-01",
      train_end: "2025-03-31",
      test_start: "2025-04-01",
      test_end: "2025-06-30",
      train_rows: 40,
      test_rows: 10,
      feature_set: ["surface", "rank_diff"],
      metrics: null,
      market_benchmark: null,
      coverage: {
        train_rows: 40,
        test_rows: 10,
        official_benchmark_sample: {
          rows_total_test: 10,
          rows_common_official: 0,
          rows_excluded_for_common_sample: 10,
          sample_mismatch_detected: true,
          missing_rows_by_contender: { market_no_vig: 10 }
        }
      },
      leakage_flags: [],
      skip_reason: "Dati insufficienti: train=40 (min 200), test=10 (min 50)."
    }
  ]
};

export const walkForwardRuns = {
  total: 1,
  limit: 20,
  offset: 0,
  items: [
    {
      id: walkForwardRun.id,
      status: walkForwardRun.status,
      mode: walkForwardRun.mode,
      initial_train_days: walkForwardRun.initial_train_days,
      test_days: walkForwardRun.test_days,
      step_days: walkForwardRun.step_days,
      versions_requested: walkForwardRun.versions_requested,
      origin: walkForwardRun.origin,
      started_at: walkForwardRun.started_at,
      finished_at: walkForwardRun.finished_at,
      duration_seconds: walkForwardRun.duration_seconds,
      created_at: walkForwardRun.created_at,
      created_by: walkForwardRun.created_by,
      folds_completed: 3,
      folds_skipped: 1,
      folds_errors: 0,
      leakage_flags_total: 0
    }
  ]
};

const calibrationReliabilityBins = [
  {
    bin_index: 0,
    bin_start: 0,
    bin_end: 0.1,
    count: 12,
    mean_predicted: 0.06,
    mean_actual: 0.08,
    calibration_gap: 0.02,
    insufficient_sample: true
  },
  {
    bin_index: 4,
    bin_start: 0.4,
    bin_end: 0.5,
    count: 45,
    mean_predicted: 0.47,
    mean_actual: 0.49,
    calibration_gap: 0.02,
    insufficient_sample: false
  },
  {
    bin_index: 8,
    bin_start: 0.8,
    bin_end: 0.9,
    count: 38,
    mean_predicted: 0.84,
    mean_actual: 0.78,
    calibration_gap: 0.06,
    insufficient_sample: false
  }
];

const calibrationMethodMetrics = {
  brier_score: 0.21,
  log_loss: 0.62,
  ece: 0.045,
  mce: 0.09,
  n_samples: 320,
  reliability_bins: calibrationReliabilityBins
};

export const calibrationRun = {
  id: 3,
  status: "completed",
  walk_forward_run_id: 11,
  n_bins: 10,
  min_bin_samples: 30,
  min_calibrator_train_samples: 100,
  wf_mode: "expanding",
  wf_initial_train_days: 365,
  wf_test_days: 90,
  wf_step_days: 90,
  wf_min_train_rows: 200,
  wf_min_test_rows: 50,
  wf_embargo_days: 0,
  wf_edge_threshold: 0.03,
  wf_random_state: 42,
  methods_requested: "raw,platt,isotonic",
  versions_requested: "v2",
  origin: "manual",
  started_at: `${TODAY}T09:00:00`,
  finished_at: `${TODAY}T09:15:00`,
  duration_seconds: 900,
  report_path: "backend/data/reports/calibration/calibration_latest.json",
  summary: {
    models_total: 1,
    models_with_oos: 1,
    oos_samples_total: 320,
    leakage_flags_total: 0,
    note: "Calibrazione su OOS walk-forward."
  },
  error_message: null,
  created_at: `${TODAY}T08:55:00`,
  created_by: "admin_api",
  results: [
    {
      id: 31,
      run_id: 3,
      model_version: "v2",
      model_name: "logistic_regression",
      dataset_path: "backend/data/processed/tennis_winner_dataset_v2.csv",
      date_min: "2025-01-01",
      date_max: "2025-06-30",
      oos_samples_total: 320,
      aggregate: {
        raw: calibrationMethodMetrics,
        platt: { ...calibrationMethodMetrics, ece: 0.032, brier_score: 0.205 },
        isotonic: { ...calibrationMethodMetrics, ece: 0.028, brier_score: 0.201 }
      },
      comparison: {
        raw: calibrationMethodMetrics,
        platt: { ...calibrationMethodMetrics, ece: 0.032 },
        isotonic: { ...calibrationMethodMetrics, ece: 0.028 },
        deltas: {
          platt: { brier_score: -0.005, log_loss: -0.01, ece: -0.013, mce: -0.02 },
          isotonic: { brier_score: -0.009, log_loss: -0.015, ece: -0.017, mce: -0.03 }
        },
        note: "Delta negativo indica miglioramento."
      },
      fold_outcomes: [],
      artifacts: {},
      leakage_flags: [],
      skip_reason: null
    }
  ]
};

export const calibrationRuns = {
  total: 1,
  limit: 20,
  offset: 0,
  items: [
    {
      id: calibrationRun.id,
      status: calibrationRun.status,
      wf_mode: calibrationRun.wf_mode,
      wf_initial_train_days: calibrationRun.wf_initial_train_days,
      wf_test_days: calibrationRun.wf_test_days,
      wf_step_days: calibrationRun.wf_step_days,
      methods_requested: calibrationRun.methods_requested,
      versions_requested: calibrationRun.versions_requested,
      walk_forward_run_id: calibrationRun.walk_forward_run_id,
      origin: calibrationRun.origin,
      started_at: calibrationRun.started_at,
      finished_at: calibrationRun.finished_at,
      duration_seconds: calibrationRun.duration_seconds,
      created_at: calibrationRun.created_at,
      created_by: calibrationRun.created_by,
      models_with_oos: 1,
      oos_samples_total: 320,
      leakage_flags_total: 0
    }
  ]
};

const probabilityBandBucket = {
  key: "p_05_0.50_0.60",
  label: "50% – 60%",
  bin_start: 0.5,
  bin_end: 0.6,
  predictions_total: 42,
  closed: 42,
  void: 0,
  open: 0,
  won: 24,
  lost: 18,
  hit_rate_pct: 57.14,
  mean_predicted_pct: 55.2,
  mean_observed_pct: 57.14,
  calibration_gap_pct: 1.94,
  avg_odds: 1.92,
  avg_edge_pct: 4.5,
  stake_total: 42,
  stake_settled: 42,
  profit: 3.6,
  roi_pct: 8.57,
  yield_pct: 8.57,
  hit_rate_ci_lower_pct: 42.1,
  hit_rate_ci_upper_pct: 70.2,
  insufficient_sample: false
};

export const probabilityBandAnalysis = {
  source: "live" as const,
  band_dimension: "probability" as const,
  probability_kind: "raw" as const,
  n_bins: 10,
  min_bin_samples: 30,
  model_version: null,
  model_name: null,
  from_date: "2026-01-01",
  to_date: "2026-07-28",
  event_date_from: null,
  event_date_to: null,
  predictions_total: 42,
  closed: 42,
  void: 0,
  open: 0,
  won: 24,
  lost: 18,
  bands: [probabilityBandBucket],
  comparison: {},
  by_fold: [],
  by_period: [],
  notes: ["Live: ledger PublishedPrediction con settlement a lettura (non backtest ML)."]
};

export const segmentRoiBucket = {
  key: "Hard",
  label: "Hard",
  predictions_total: 42,
  closed: 42,
  void: 0,
  open: 0,
  won: 24,
  lost: 18,
  hit_rate_pct: 57.14,
  avg_odds: 1.95,
  avg_edge_pct: 6.2,
  stake_total: 42,
  stake_settled: 42,
  profit: 3.5,
  roi_pct: 8.33,
  yield_pct: 8.33,
  max_drawdown: 2.0,
  hit_rate_ci_lower_pct: 42.1,
  hit_rate_ci_upper_pct: 70.2,
  roi_ci_lower_pct: -2.5,
  roi_ci_upper_pct: 18.5,
  insufficient_sample: false
};

export const segmentRoiAnalysis = {
  source: "live" as const,
  segment_dimension: "surface" as const,
  min_segment_samples: 30,
  model_version: null,
  model_name: null,
  from_date: "2026-01-01",
  to_date: "2026-07-28",
  event_date_from: null,
  event_date_to: null,
  predictions_total: 42,
  closed: 42,
  void: 0,
  open: 0,
  won: 24,
  lost: 18,
  segments: [segmentRoiBucket],
  by_fold: [],
  by_period: [],
  notes: ["Live: ledger PublishedPrediction con settlement a lettura (non backtest ML)."]
};

export const subscriptionDashboardSummary: SubscriptionDashboardSummaryResponse = {
  generated_at: `${TODAY}T12:00:00Z`,
  overview: {
    users_free: 12,
    users_pro: 7,
    users_founder: 2,
    active_subscriptions: 16,
    trialing_subscriptions: 3,
    expiring_within_7_days: 2,
    expiring_within_30_days: 4,
    canceled_subscriptions: 5,
    canceled_last_30_days: 2,
    payment_failed_last_30_days: 1,
    monthly_revenue_cents: 15400,
    free_to_pro_users: 4,
    free_user_base: 12,
    free_to_pro_conversion_pct: 33.33,
    churned_last_30_days: 2,
    active_base_last_30_days: 14,
    churn_pct_last_30_days: 14.29
  },
  monthly_revenue: [
    { month: "2026-03", revenue_cents: 7600 },
    { month: "2026-04", revenue_cents: 9200 },
    { month: "2026-05", revenue_cents: 8800 },
    { month: "2026-06", revenue_cents: 10300 },
    { month: "2026-07", revenue_cents: 12100 },
    { month: "2026-08", revenue_cents: 15400 }
  ]
};

export const subscriptionDashboardUsers: SubscriptionDashboardUserListResponse = {
  total: 2,
  limit: 50,
  offset: 0,
  items: [
    {
      user_id: 101,
      telegram_user_id: 900101,
      external_ref: null,
      username: "pro_user",
      plan_code: "pro",
      plan_name: "Pro",
      subscription_id: 501,
      subscription_status: "active",
      started_at: `${TODAY}T08:00:00Z`,
      trial_ends_at: null,
      expires_at: `${TODAY}T23:59:00Z`,
      cancel_at_period_end: false,
      canceled_at: null,
      auto_renew: true,
      payment_failed: true,
      last_payment_status: "failed",
      last_payment_event_at: `${TODAY}T11:00:00Z`
    },
    {
      user_id: 102,
      telegram_user_id: 900102,
      external_ref: null,
      username: "founder_user",
      plan_code: "founder",
      plan_name: "Founder",
      subscription_id: 502,
      subscription_status: "active",
      started_at: `${TODAY}T07:00:00Z`,
      trial_ends_at: null,
      expires_at: null,
      cancel_at_period_end: false,
      canceled_at: null,
      auto_renew: false,
      payment_failed: false,
      last_payment_status: "succeeded",
      last_payment_event_at: `${TODAY}T10:30:00Z`
    }
  ]
};

export const subscriptionDashboardEvents: SubscriptionDashboardEventListResponse = {
  total: 2,
  limit: 50,
  offset: 0,
  items: [
    {
      source: "payment",
      event_id: "payment:1001",
      occurred_at: `${TODAY}T11:00:00Z`,
      event_type: "invoice_payment_failed",
      status: "failed",
      user_id: 101,
      subscription_id: 501,
      plan_code: "pro",
      amount_cents: 1900,
      currency: "EUR",
      admin_username: null,
      description: "provider=stripe event=evt_test_failed",
      context_json: "{}"
    },
    {
      source: "admin_action",
      event_id: "admin:1002",
      occurred_at: `${TODAY}T10:00:00Z`,
      event_type: "subscription_suspend",
      status: "suspended",
      user_id: 101,
      subscription_id: 501,
      plan_code: "pro",
      amount_cents: null,
      currency: null,
      admin_username: "admin",
      description: "Manual suspension from admin dashboard",
      context_json: '{"reason":"manual_review"}'
    }
  ]
};

