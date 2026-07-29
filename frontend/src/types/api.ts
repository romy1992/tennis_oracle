export type TennisMatch = {
  id_fixture: number;
  event_key: number;
  event_date: string | null;
  event_time: string | null;
  event_first_player: string | null;
  first_player_key: number | null;
  event_second_player: string | null;
  second_player_key: number | null;
  event_final_result: string | null;
  event_game_result: string | null;
  event_serve: string | null;
  event_winner: string | null;
  event_status: string | null;
  event_type_type: string | null;
  tournament_name: string | null;
  tournament_key: number | null;
  tournament_round: string | null;
  tournament_season: string | null;
  event_live: string | null;
  event_first_player_logo: string | null;
  event_second_player_logo: string | null;
  event_qualification: string | null;
  pointbypoint: unknown | null;
  scores: unknown | null;
  statistics: unknown | null;
  odds: unknown | null;
};

export type Player = {
  id_player: number;
  player_key: number;
  player_name: string | null;
  player_full_name: string | null;
  player_country: string | null;
  player_bday: string | null;
  player_logo: string | null;
  stats: unknown | null;
  tournaments: unknown | null;
};

export type Tournament = {
  id_tournament: number;
  tournament_key: number | null;
  tournament_name: string | null;
  event_type_key: number | null;
  event_type_type: string | null;
  tournament_sourface: string | null;
};

export type ListParams = {
  limit?: number;
  offset?: number;
};

export type MLModelVersion = "v1" | "v2" | "v3";
export type MLModelName = "logistic_regression" | "random_forest";

export type NextFixture = {
  id: number;
  event_key: number;
  event_date: string | null;
  event_time: string | null;
  event_first_player: string | null;
  first_player_key: number | null;
  event_second_player: string | null;
  second_player_key: number | null;
  tournament_name: string | null;
  tournament_key: number | null;
  tournament_round: string | null;
  surface: string | null;
  event_status: string | null;
  event_type_type: string | null;
  odds: unknown | null;
  imported_at: string | null;
  week_start: string | null;
  week_end: string | null;
  source: string | null;
  is_completed: boolean | null;
  moved_to_fixture_at: string | null;
  match_lifecycle_status?: string | null;
  match_lifecycle_label?: string | null;
};

export type MatchPrediction = {
  event_key: number;
  model_version: string;
  model_name: string | null;
  predicted_at: string | null;
  prob_player_1_win: number | null;
  predicted_winner: string | null;
  actual_winner: string | null;
  is_correct: boolean | null;
  predicted_winner_odds: number | null;
  odds_bookmaker_count: number | null;
  confidence: number | null;
  features_available: boolean;
  warnings: string[];
};

export type NextFixtureWithPrediction = NextFixture & {
  prediction: MatchPrediction | null;
  prediction_warning: string | null;
};

export type FixturesWithPredictionsPage = {
  items: NextFixtureWithPrediction[];
  total: number;
  offset: number;
  limit: number;
};

export type DailyPredictionStatsDay = {
  day_offset: number;
  date: string;
  predictions_total: number;
  predictions_resolved: number;
  predictions_correct: number;
  predictions_lost: number;
  accuracy_pct: number | null;
  pending: number;
  predictions_with_odds: number;
  avg_predicted_winner_odds: number | null;
  avg_winning_odds: number | null;
  theoretical_profit_units: number;
  theoretical_roi_pct: number | null;
};

export type DailyPredictionStatsResponse = {
  model_version: MLModelVersion;
  days: DailyPredictionStatsDay[];
};

export type PredictionSummaryResponse = {
  model_version: MLModelVersion;
  predictions_total: number;
  predictions_resolved: number;
  predictions_correct: number;
  predictions_lost: number;
  accuracy_pct: number | null;
  pending: number;
  predictions_with_odds: number;
  avg_predicted_winner_odds: number | null;
  avg_winning_odds: number | null;
  theoretical_profit_units: number;
  theoretical_roi_pct: number | null;
  breakdown: PredictionModelBreakdown[];
};

export type PredictionModelBreakdown = {
  model_version: string;
  model_name: string | null;
  predictions_total: number;
  predictions_resolved: number;
  predictions_correct: number;
  predictions_lost: number;
  accuracy_pct: number | null;
  pending: number;
  predictions_with_odds: number;
  avg_predicted_winner_odds: number | null;
  avg_winning_odds: number | null;
  theoretical_profit_units: number;
  theoretical_roi_pct: number | null;
};

export type PredictionQueryParams = {
  model_version?: MLModelVersion;
  model_name?: string;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
  status?: "upcoming" | "played" | "all";
  outcome?: "all" | "won" | "lost";
  player?: string;
};

export type SingleMatchValueDecision = "PLAY" | "NO BET" | "BORDERLINE";

export type SingleMatchValueItem = {
  match_id: number;
  event_date: string | null;
  event_time: string | null;
  tournament_name: string | null;
  competition: string | null;
  player_a: string | null;
  player_b: string | null;
  market: string;
  selection: string;
  selection_code: string;
  model_probability: number;
  market_odds: number;
  void_odds: number;
  edge_absolute: number;
  edge_percent: number;
  expected_roi: number;
  suggested_min_edge_percent: number;
  min_edge_percent: number;
  stake: number;
  decision: SingleMatchValueDecision;
  value_label: string;
  edge_label: string;
  explanation: string;
  bookmaker_count: number | null;
  actual_winner: string | null;
  is_correct: boolean | null;
  profit_loss: number | null;
};

export type SingleMatchValueSimulationBucket = {
  bets_count: number;
  resolved_count: number;
  profit_loss_units: number;
  roi_pct: number | null;
  hit_rate_pct: number | null;
  avg_market_odds: number | null;
  avg_void_odds: number | null;
};

export type SingleMatchValueSimulation = {
  stake: number;
  play_bets: SingleMatchValueSimulationBucket;
  above_void: SingleMatchValueSimulationBucket;
  below_void: SingleMatchValueSimulationBucket;
  borderline_count: number;
};

export type SingleMatchValueSummary = {
  total: number;
  play_count: number;
  no_bet_count: number;
  borderline_count: number;
  avg_market_odds: number | null;
  avg_void_odds: number | null;
  avg_expected_roi: number | null;
};

export type SingleMatchValueResponse = {
  model_version: MLModelVersion;
  model_name: string | null;
  min_edge_percent: number | null;
  items: SingleMatchValueItem[];
  total: number;
  offset: number;
  limit: number;
  summary: SingleMatchValueSummary;
  simulation: SingleMatchValueSimulation;
  warnings: string[];
};

export type SingleMatchValueQueryParams = PredictionQueryParams & {
  min_edge_percent?: number;
};

export type DailyStatsParams = {
  model_version?: MLModelVersion;
  model_name?: string;
  from_day?: number;
  to_day?: number;
};

export type ImportStatusResponse = {
  next_fixtures_last_imported_at: string | null;
  next_fixtures_imported_today: boolean;
  next_fixtures_max_date: string | null;
  next_fixtures_window_days: number;
  next_fixtures_window_until: string | null;
  fixtures_last_match_date: string | null;
  fixtures_last_imported_at: string | null;
};

export type RefreshMatchesResponse = {
  next_fixtures_imported: boolean;
  next_fixtures_summary: Record<string, number> | null;
  predictions_summary: Record<string, unknown>;
  import_status: ImportStatusResponse;
};

export type ImportFixturesResponse = {
  days_back: number;
  import_status: ImportStatusResponse;
};

export type MLDatasetType =
  | "base"
  | "atp_enriched"
  | "v2"
  | "v2_atp_enriched"
  | "v3"
  | "v3_atp_enriched"
  | "v3_with_odds";

export type MLPipelineSummary = {
  fixture_total: number | null;
  fixture_completed_singles: number | null;
  dataset_base_exists: boolean;
  dataset_base_path: string;
  dataset_base_rows: number | null;
  dataset_atp_exists: boolean;
  dataset_atp_path: string;
  dataset_atp_rows: number | null;
  dataset_latest_match_date: string | null;
  atp_matched_rows: number | null;
  atp_coverage_pct: number | null;
  atp_singles_matches_exists: boolean;
  atp_singles_matches_path: string;
  atp_singles_matches_rows: number | null;
  atp_match_mapping_exists: boolean;
  atp_match_mapping_path: string;
  atp_match_mapping_rows: number | null;
  atp_player_mapping_exists: boolean;
  atp_player_mapping_path: string;
  atp_player_mapping_rows: number | null;
  warnings: string[];
};

export type MLDatasetSummary = {
  dataset_type: MLDatasetType;
  path: string;
  exists: boolean;
  rows: number;
  columns: number;
  date_min: string | null;
  date_max: string | null;
  target_distribution: Record<string, number>;
  null_counts: Record<string, number>;
  available_columns: string[];
  warnings: string[];
};

export type MLDatasetPreview = {
  dataset_type: MLDatasetType;
  rows: number;
  columns: string[];
  data: Array<Record<string, string | number | boolean | null>>;
  warnings: string[];
};

export type MLOddsSummary = {
  odds_csv_exists: boolean;
  odds_csv_path: string;
  odds_rows: number | null;
  unique_matches: number | null;
  unique_bookmakers: number | null;
  top_bookmakers: Record<string, number>;
  date_min: string | null;
  date_max: string | null;
  with_odds_dataset_exists: boolean;
  with_odds_dataset_path: string;
  with_odds_dataset_rows: number | null;
  odds_coverage_pct: number | null;
  warnings: string[];
};

export type MLModelInfo = {
  name: string;
  available: boolean;
  path: string;
  last_modified: string | null;
};

export type MLModelVersionSummary = {
  version: MLModelVersion;
  models: MLModelInfo[];
  metrics_path: string;
  metrics_exists: boolean;
};

export type MLModelsSummary = {
  versions: MLModelVersionSummary[];
  models: MLModelInfo[];
  baseline_metrics_path: string;
  baseline_metrics_exists: boolean;
  baseline_v2_metrics_path: string;
  baseline_v2_metrics_exists: boolean;
  baseline_v3_metrics_path?: string;
  baseline_v3_metrics_exists?: boolean;
  model_registry_path: string;
  model_registry_exists: boolean;
  model_comparison_path: string;
  model_comparison_exists: boolean;
};

export type MLValueBetMetrics = {
  edge_threshold: number;
  bets_count: number;
  hit_rate: number;
  total_profit: number;
  roi: number;
  yield: number;
  odds_coverage_rows: number;
  odds_coverage_pct: number;
};

export type MLModelMetrics = {
  accuracy: number | null;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  roc_auc: number | null;
  log_loss: number | null;
  confusion_matrix?: number[][];
  class_distribution_train?: Record<string, number>;
  class_distribution_test?: Record<string, number>;
  value_bet_overall?: MLValueBetMetrics;
  value_bet_with_odds?: MLValueBetMetrics;
};

export type MLMarketBenchmark = {
  market_accuracy: number | null;
  market_log_loss: number | null;
  market_roc_auc: number | null;
  market_profit_if_bet_player_1_all: number;
  market_roi_if_bet_player_1_all: number;
  odds_coverage_rows: number;
  odds_coverage_pct: number;
};

export type MLBaselineMetrics = {
  exists: boolean;
  version?: MLModelVersion;
  metrics_path: string;
  last_modified?: string | null;
  model_version?: string | null;
  dataset_used: string | null;
  rows_total?: number;
  columns_total?: number;
  date_min?: string | null;
  date_max?: string | null;
  split: {
    strategy: string;
    test_size: number;
    train_rows: number;
    test_rows: number;
    train_date_min: string | null;
    train_date_max: string | null;
    test_date_min: string | null;
    test_date_max: string | null;
  } | null;
  features_used?: string[];
  features_excluded?: string[];
  rank_features_note?: string | null;
  logistic_regression: MLModelMetrics | null;
  random_forest: MLModelMetrics | null;
  market_benchmark: MLMarketBenchmark | null;
  comparison: Array<MLModelMetrics & { model: string }>;
  warnings: string[];
};

export type MLModelRegistryEntry = {
  id: MLModelVersion | string;
  label: string;
  description: string;
  dataset: string;
  features_summary: string;
  models_path: string;
  metrics_path: string;
  created_at: string;
  updated_at?: string;
};

export type MLModelRegistry = {
  exists: boolean;
  versions: MLModelRegistryEntry[];
  planned_versions: Array<{ id: string; label: string; status: string; note?: string }>;
  warnings: string[];
};

export type MLModelComparison = {
  exists: boolean;
  generated_at?: string | null;
  versions: Record<
    string,
    {
      metrics_path: string;
      dataset_used?: string;
      features_used?: string[];
      rank_features_note?: string;
      models?: Record<string, MLModelMetrics>;
      market_benchmark?: MLMarketBenchmark | null;
    }
  >;
  warnings: string[];
};

export type PickStatus = "pending" | "won" | "lost" | "void";
export type SlipStatus = "pending" | "won" | "lost" | "void";

export type BettingSlipPick = {
  event_key: number;
  event_date: string | null;
  event_time: string | null;
  tournament_name: string | null;
  surface: string | null;
  player_1: string | null;
  player_2: string | null;
  predicted_winner: string;
  predicted_winner_label: string | null;
  model_prob: number | null;
  market_prob: number | null;
  edge: number | null;
  odds: number | null;
  void_odds: number | null;
  edge_absolute: number | null;
  edge_percent: number | null;
  expected_roi: number | null;
  suggested_min_edge_percent: number | null;
  min_edge_percent: number | null;
  value_decision: string | null;
  value_label: string | null;
  confidence: number | null;
  pick_score: number | null;
  pick_status: PickStatus;
  actual_winner_label: string | null;
  is_correct: boolean | null;
  match_lifecycle_status?: string | null;
  match_lifecycle_label?: string | null;
  event_status?: string | null;
  void_reason?: string | null;
};

export type BettingSlip = {
  id: string;
  slip_key: string;
  label: string;
  description: string | null;
  picks: BettingSlipPick[];
  pick_count: number;
  combined_odds: number;
  combined_probability_estimate: number | null;
  potential_return: number;
  potential_profit: number;
  slip_status: SlipStatus;
  picks_won: number;
  picks_lost: number;
  picks_pending: number;
  picks_void?: number;
  picks_total: number;
  resolved_combined_odds: number | null;
  effective_combined_odds?: number | null;
  theoretical_profit_if_won: number | null;
  generated_at: string | null;
};

export type BettingSlipsDailyResponse = {
  date: string;
  model_version: MLModelVersion;
  model_name: string;
  stake: number;
  candidate_pool_size: number;
  slips: BettingSlip[];
  warnings: string[];
};

export type BettingSlipRefreshSummary = {
  fixtures_imported: boolean;
  predictions_resolved: number;
  slips_updated: number;
  next_fixtures_imported: boolean;
  import_status?: ImportStatusResponse | null;
};

export type BettingSlipsRefreshResponse = BettingSlipsDailyResponse & {
  refresh_summary: BettingSlipRefreshSummary;
};

export type BettingSlipStatsDay = {
  date: string;
  slips_total: number;
  slips_won: number;
  slips_lost: number;
  slips_pending: number;
  picks_total: number;
  picks_won: number;
  picks_lost: number;
  picks_pending: number;
  slip_win_rate_pct: number | null;
  pick_hit_rate_pct: number | null;
  theoretical_profit_units: number;
  theoretical_roi_pct: number | null;
};

export type BettingSlipStatsProfile = {
  slip_key: string;
  label: string;
  slips_won: number;
  slips_lost: number;
  slips_pending: number;
  slips_total: number;
  slip_win_rate_pct: number | null;
};

export type BettingSlipStatsSummary = {
  slips_total: number;
  slips_won: number;
  slips_lost: number;
  slips_pending: number;
  picks_total: number;
  picks_won: number;
  picks_lost: number;
  picks_pending: number;
  slip_win_rate_pct: number | null;
  pick_hit_rate_pct: number | null;
  theoretical_profit_units: number;
  theoretical_roi_pct: number | null;
  by_profile: BettingSlipStatsProfile[];
};

export type BettingSlipStatsResponse = {
  model_version: MLModelVersion;
  from_date: string;
  to_date: string;
  days: BettingSlipStatsDay[];
  summary: BettingSlipStatsSummary;
};

export type BettingSlipModelStatsRow = {
  model_version: string;
  model_name: string;
  slips_total: number;
  slips_won: number;
  slips_lost: number;
  slips_pending: number;
  slip_win_rate_pct: number | null;
  picks_total: number;
  picks_won: number;
  picks_lost: number;
  picks_pending: number;
  pick_hit_rate_pct: number | null;
  theoretical_profit_units: number;
  theoretical_roi_pct: number | null;
  first_date: string;
  last_date: string;
};

export type BettingSlipModelStatsResponse = {
  from_date: string;
  to_date: string;
  stake: number;
  rows: BettingSlipModelStatsRow[];
};

export type BettingSlipsQueryParams = {
  date?: string;
  model_version?: MLModelVersion;
  model_name?: string;
  stake?: number;
  min_edge_percent?: number;
  regenerate?: boolean;
};

export type BettingSlipStatsParams = {
  from?: string;
  to?: string;
  model_version?: MLModelVersion;
  model_name?: string;
  stake?: number;
  all_time?: boolean;
};

export type BettingSlipModelStatsParams = {
  from?: string;
  to?: string;
  stake?: number;
  all_time?: boolean;
};

export type BettingSlipCalendarDay = {
  date: string;
  is_today: boolean;
  is_past: boolean;
  is_upcoming: boolean;
  has_slips: boolean;
  slip_count: number;
  fixture_count: number;
  candidate_pool_size: number | null;
};

export type BettingSlipCalendarResponse = {
  today: string;
  window_from: string;
  window_to: string;
  history_from: string | null;
  model_version: MLModelVersion;
  model_name: string;
  days: BettingSlipCalendarDay[];
};

export type GlobalUpdateStatus =
  | "pending"
  | "running"
  | "completed"
  | "completed_with_errors"
  | "failed"
  | "cancelled"
  | "interrupted";

export type GlobalUpdateRunItemRead = {
  model_version: string;
  model_name: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  predictions_generated: number;
  slips_generated: number;
  error_message: string | null;
  warnings: string[];
};

export type GlobalUpdateRunRead = {
  id: number;
  run_date: string;
  origin: "manual" | "cron" | "job";
  status: GlobalUpdateStatus;
  current_phase: string | null;
  progress_pct: number | null;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  force: boolean;
  versions_processed: number;
  models_processed: number;
  combinations_completed: number;
  combinations_failed: number;
  combinations_skipped: number;
  fixtures_processed: number;
  slips_generated: number;
  errors: string[];
  warnings: string[];
  items: GlobalUpdateRunItemRead[];
};

export type GlobalUpdateStartResponse = {
  run_id: number;
  status: GlobalUpdateStatus;
  message: string;
};

export type GlobalUpdateReportPhase = {
  phase?: string;
  status?: string;
  duration_seconds?: number;
  error?: string;
  [key: string]: unknown;
};

export type GlobalUpdateReportRead = {
  run_id: number;
  run_date: string;
  origin: "manual" | "cron" | "job";
  status: GlobalUpdateStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  summary: Record<string, unknown>;
  phases: GlobalUpdateReportPhase[];
  items: GlobalUpdateRunItemRead[];
  errors: string[];
  warnings: string[];
};

export type ModelsVersionsResultsResponse = {
  date: string;
  last_updated_at: string | null;
  last_run_id: number | null;
  last_run_origin: "manual" | "cron" | "job" | null;
  versions: Array<{
    version: string;
    models: Array<{
      model: string;
      status: string;
      predictions_count: number;
      slips_count: number;
      data: Record<string, unknown>;
    }>;
  }>;
};

export type TelegramBotEventType = "command" | "message" | "callback";

export type TelegramBotEvent = {
  id: number;
  created_at: string;
  telegram_user_id: number | null;
  chat_id: number | null;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  event_type: TelegramBotEventType | string;
  action: string;
  raw_text: string | null;
  success: boolean | null;
  error_message: string | null;
};

export type TelegramBotEventsResponse = {
  total: number;
  limit: number;
  offset: number;
  items: TelegramBotEvent[];
};

export type TelegramBotActionCount = {
  action: string;
  count: number;
};

export type TelegramBotDayCount = {
  day: string;
  count: number;
};

export type TelegramBotStatsResponse = {
  total_events: number;
  unique_users: number;
  events_today: number;
  top_action: string | null;
  by_action: TelegramBotActionCount[];
  by_day: TelegramBotDayCount[];
};

export type TelegramBotEventsParams = {
  from?: string;
  to?: string;
  action?: string;
  user_id?: number;
  username?: string;
  event_type?: string;
  limit?: number;
  offset?: number;
};

export type TelegramBotStatsParams = {
  from?: string;
  to?: string;
  days?: number;
};

export type TelegramUserStatus = "invited" | "active" | "suspended" | "blocked";

export type TelegramUser = {
  id: number;
  telegram_user_id: number;
  chat_id?: number | null;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  status: TelegramUserStatus | string;
  invite_origin: string | null;
  first_access_at: string;
  last_access_at: string;
  terms_accepted: boolean;
  terms_accepted_at: string | null;
  terms_version: string | null;
  notifications_enabled?: boolean;
  notify_predictions?: boolean;
  notify_results?: boolean;
  notify_empty_day?: boolean;
  created_at: string;
  updated_at: string;
};

export type TelegramUserListResponse = {
  total: number;
  limit: number;
  offset: number;
  items: TelegramUser[];
};

export type TelegramUsersParams = {
  q?: string;
  status?: TelegramUserStatus | string;
  telegram_user_id?: number;
  username?: string;
  limit?: number;
  offset?: number;
};

export type TelegramUserInviteCreate = {
  telegram_user_id: number;
  username?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  invite_origin?: string | null;
  status?: TelegramUserStatus;
};

export type TelegramFeedbackCategory =
  | "bug"
  | "content"
  | "ux"
  | "feature"
  | "access"
  | "other";

export type TelegramFeedbackStatus = "new" | "reviewing" | "resolved" | "rejected";

export type TelegramFeedback = {
  id: number;
  telegram_user_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  category: TelegramFeedbackCategory | string;
  rating: number;
  message: string;
  status: TelegramFeedbackStatus | string;
  created_at: string;
  updated_at: string;
};

export type TelegramFeedbackListResponse = {
  total: number;
  limit: number;
  offset: number;
  items: TelegramFeedback[];
};

export type TelegramFeedbackParams = {
  q?: string;
  status?: TelegramFeedbackStatus | string;
  category?: TelegramFeedbackCategory | string;
  telegram_user_id?: number;
  limit?: number;
  offset?: number;
};

export type TelegramFeedbackStatusUpdate = {
  status: TelegramFeedbackStatus;
};

export type PublicationSource =
  | "admin_api"
  | "telegram"
  | "global_update"
  | "system"
  | "manual";

export type PublishedPrediction = {
  id: number;
  publication_id: string;
  content_version: number;
  previous_version_id: number | null;
  event_key: number;
  selection: string;
  model_version: string;
  model_name: string;
  probability: number;
  odds: number | null;
  void_odds: number | null;
  edge: number | null;
  publication_odds: number | null;
  publication_bookmaker: string | null;
  closing_odds: number | null;
  closing_bookmaker: string | null;
  no_vig_publication_prob: number | null;
  no_vig_closing_prob: number | null;
  clv_pct: number | null;
  clv_prob_delta_pct: number | null;
  clv_available: boolean;
  unit_stake: number;
  published_at: string;
  publication_source: PublicationSource | string;
  initial_status: string;
  content_hash: string;
  player_1_name: string | null;
  player_2_name: string | null;
  tournament_name: string | null;
  event_date: string | null;
  event_time: string | null;
  match_prediction_id: number | null;
  betting_slip_pick_id: number | null;
  is_latest: boolean;
  match_started: boolean;
};

export type PublishedPredictionListResponse = {
  total: number;
  limit: number;
  offset: number;
  items: PublishedPrediction[];
};

export type PublishedPredictionVersionChainResponse = {
  publication_id: string;
  items: PublishedPrediction[];
};

export type PublishedPredictionsParams = {
  from?: string;
  to?: string;
  event_key?: number;
  model_version?: MLModelVersion | string;
  model_name?: string;
  publication_source?: string;
  latest_only?: boolean;
  limit?: number;
  offset?: number;
};

export type PublishedLiveStatsBucket = {
  key: string;
  label: string;
  predictions_total: number;
  closed: number;
  open: number;
  void: number;
  won: number;
  lost: number;
  hit_rate_pct: number | null;
  stake_total: number;
  stake_settled: number;
  profit: number;
  roi_pct: number | null;
  yield_pct: number | null;
  avg_odds: number | null;
  clv_count: number;
  clv_missing: number;
  clv_coverage_pct: number | null;
  clv_avg_pct: number | null;
  clv_median_pct: number | null;
  clv_positive_pct: number | null;
  clv_avg_prob_delta_pct: number | null;
};

export type PublishedLiveStatsSummary = {
  source: "published_prediction";
  latest_only: boolean;
  from_date: string | null;
  to_date: string | null;
  event_date_from: string | null;
  event_date_to: string | null;
  model_version: string | null;
  model_name: string | null;
  publication_source: string | null;
  tournament_name: string | null;
  surface: string | null;
  odds_band: OddsBand | null;
  predictions_total: number;
  closed: number;
  open: number;
  void: number;
  won: number;
  lost: number;
  hit_rate_pct: number | null;
  stake_total: number;
  stake_settled: number;
  profit: number;
  roi_pct: number | null;
  yield_pct: number | null;
  avg_odds: number | null;
  max_drawdown: number;
  max_winning_streak: number;
  max_losing_streak: number;
  clv_count: number;
  clv_missing: number;
  clv_coverage_pct: number | null;
  clv_avg_pct: number | null;
  clv_median_pct: number | null;
  clv_positive_pct: number | null;
  clv_avg_prob_delta_pct: number | null;
  by_model: PublishedLiveStatsBucket[];
  by_odds: PublishedLiveStatsBucket[];
  by_edge: PublishedLiveStatsBucket[];
  by_surface: PublishedLiveStatsBucket[];
  by_period: PublishedLiveStatsBucket[];
};

export type OddsBand = "lt_1_50" | "1_50_2_00" | "2_00_3_00" | "gte_3_00" | "missing";

export type PublishedSettledTip = PublishedPrediction & {
  outcome: "pending" | "won" | "lost" | "void";
  profit: number;
  stake_settled: number;
  surface: string | null;
};

export type PublishedLiveStatsParams = {
  from?: string;
  to?: string;
  event_date_from?: string;
  event_date_to?: string;
  model_version?: MLModelVersion | string;
  model_name?: string;
  publication_source?: string;
  tournament_name?: string;
  surface?: string;
  odds_band?: OddsBand | string;
  latest_only?: boolean;
};

export type LiveBetaPipelineStatus = {
  mode: "live";
  active_run: GlobalUpdateRunRead | null;
  latest_run: GlobalUpdateRunRead | null;
  last_updated_at: string | null;
  import_status: ImportStatusResponse;
};

export type LivePublicationEmptyReason =
  | "ok"
  | "table_unavailable"
  | "publication_disabled"
  | "public_model_unconfigured"
  | "public_model_invalid"
  | "pipeline_never_run"
  | "pipeline_run_no_qualified_plays"
  | "publication_errors";

export type LiveBetaDataCompleteness = {
  tips_total: number;
  tips_with_odds: number;
  tips_with_odds_pct: number | null;
  tips_with_event_date: number;
  tips_with_event_date_pct: number | null;
  tips_with_match_context: number;
  tips_with_match_context_pct: number | null;
  distinct_event_keys: number;
  event_keys_with_odds_snapshot: number;
  odds_snapshot_coverage_pct: number | null;
  snapshots_opening: number;
  snapshots_observed: number;
  snapshots_publication: number;
  snapshots_closing: number;
  tips_with_closing_snapshot: number;
  tips_with_closing_snapshot_pct: number | null;
  closing_odds_status: "available" | "partial" | "missing" | "unknown";
  closing_odds_note: string | null;
};

export type LiveBetaPublicationHealth = {
  empty_reason: LivePublicationEmptyReason;
  message: string;
  live_publication_enabled: boolean;
  public_model_version: string | null;
  public_model_name: string | null;
  validation_started_at: string | null;
  last_run_publications_created: number | null;
  last_run_duplicates_skipped: number | null;
  last_run_excluded: number | null;
  last_run_candidates: number | null;
  last_run_publication_errors: string[];
};

export type LiveBetaRecentError = {
  source: "global_update" | "telegram";
  created_at: string | null;
  message: string;
  detail: string | null;
};

export type LiveBetaBacktestNote = {
  mode: "backtest";
  included_in_live_kpis: boolean;
  message: string;
  related_paths: string[];
};

export type LiveBetaDashboardResponse = {
  mode: "live";
  generated_at: string;
  from_date: string | null;
  to_date: string | null;
  model_version: string | null;
  model_name: string | null;
  tournament_name: string | null;
  surface: string | null;
  odds_band: OddsBand | null;
  latest_only: boolean;
  pipeline: LiveBetaPipelineStatus;
  publication_health: LiveBetaPublicationHealth;
  live_stats: PublishedLiveStatsSummary;
  published_today: PublishedSettledTip[];
  open_predictions: PublishedSettledTip[];
  closed_predictions: PublishedSettledTip[];
  bot_usage: TelegramBotStatsResponse;
  data_completeness: LiveBetaDataCompleteness;
  recent_errors: LiveBetaRecentError[];
  backtest: LiveBetaBacktestNote;
};

export type LiveBetaDashboardParams = {
  from?: string;
  to?: string;
  model_version?: MLModelVersion | string;
  model_name?: string;
  tournament_name?: string;
  surface?: string;
  odds_band?: OddsBand | string;
  latest_only?: boolean;
  tip_limit?: number;
};

export type WeeklyBetaTelegramStatus = "pending" | "sent" | "skipped" | "failed";

export type WeeklyBetaMetricDelta = {
  current: number | null;
  previous: number | null;
  delta: number | null;
  delta_pct: number | null;
};

export type WeeklyBetaUsersMetrics = {
  total_users: number;
  active_users: number;
  new_users: number;
  by_status: Record<string, number>;
  retention_cohort: number;
  retention_retained: number;
  retention_pct: number | null;
};

export type WeeklyBetaCommandUsage = {
  total_events: number;
  unique_users: number;
  by_action: Array<{ action: string; count: number }>;
};

export type WeeklyBetaLiveTipsMetrics = {
  predictions_published: number;
  closed: number;
  open: number;
  won: number;
  lost: number;
  void: number;
  hit_rate_pct: number | null;
  stake_settled: number;
  profit: number;
  roi_pct: number | null;
  yield_pct: number | null;
  max_drawdown: number;
};

export type WeeklyBetaPipelineMetrics = {
  runs_total: number;
  runs_failed: number;
  runs_completed_with_errors: number;
  runs_interrupted: number;
  combinations_failed: number;
  error_messages: string[];
};

export type WeeklyBetaNotificationsMetrics = {
  total: number;
  sent: number;
  failed: number;
  skipped: number;
  pending: number;
  by_kind_failed: Record<string, number>;
};

export type WeeklyBetaFeedbackMetrics = {
  total: number;
  avg_rating: number | null;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
};

export type WeeklyBetaPeriodMetrics = {
  week_start: string;
  week_end: string;
  week_label: string;
  users: WeeklyBetaUsersMetrics;
  command_usage: WeeklyBetaCommandUsage;
  live_tips: WeeklyBetaLiveTipsMetrics;
  pipeline: WeeklyBetaPipelineMetrics;
  notifications: WeeklyBetaNotificationsMetrics;
  feedback: WeeklyBetaFeedbackMetrics;
};

export type WeeklyBetaWowDeltas = {
  total_users: WeeklyBetaMetricDelta;
  active_users: WeeklyBetaMetricDelta;
  new_users: WeeklyBetaMetricDelta;
  retention_pct: WeeklyBetaMetricDelta;
  total_events: WeeklyBetaMetricDelta;
  predictions_published: WeeklyBetaMetricDelta;
  roi_pct: WeeklyBetaMetricDelta;
  yield_pct: WeeklyBetaMetricDelta;
  max_drawdown: WeeklyBetaMetricDelta;
  pipeline_errors: WeeklyBetaMetricDelta;
  notifications_failed: WeeklyBetaMetricDelta;
  feedback_total: WeeklyBetaMetricDelta;
};

export type WeeklyBetaReportPayload = {
  current: WeeklyBetaPeriodMetrics;
  previous: WeeklyBetaPeriodMetrics;
  wow: WeeklyBetaWowDeltas;
  notes: string[];
};

export type WeeklyBetaReport = {
  id: number;
  week_start: string;
  week_end: string;
  week_label: string;
  payload: WeeklyBetaReportPayload;
  telegram_status: WeeklyBetaTelegramStatus | string;
  telegram_error: string | null;
  telegram_sent_at: string | null;
  generated_at: string;
  generated_by: string;
};

export type WeeklyBetaReportListItem = {
  id: number;
  week_start: string;
  week_end: string;
  week_label: string;
  telegram_status: WeeklyBetaTelegramStatus | string;
  telegram_sent_at: string | null;
  generated_at: string;
  generated_by: string;
  total_users: number;
  active_users: number;
  new_users: number;
  retention_pct: number | null;
  predictions_published: number;
  roi_pct: number | null;
  notifications_failed: number;
  feedback_total: number;
};

export type WeeklyBetaReportListResponse = {
  total: number;
  limit: number;
  offset: number;
  items: WeeklyBetaReportListItem[];
};

export type WeeklyBetaReportGenerateRequest = {
  week_start?: string | null;
  send_telegram?: boolean;
  force?: boolean;
};

export type WeeklyBetaReportGenerateResponse = {
  report: WeeklyBetaReport;
  created: boolean;
  telegram: Record<string, unknown>;
};

export type WalkForwardMode = "expanding" | "rolling";
export type WalkForwardRunStatus =
  | "pending"
  | "running"
  | "completed"
  | "completed_with_errors"
  | "failed"
  | "cancelled";
export type WalkForwardFoldStatus =
  | "completed"
  | "skipped_insufficient_data"
  | "skipped_single_class"
  | "error";

export type WalkForwardOfficialBenchmarkMetrics = {
  accuracy?: number | null;
  log_loss?: number | null;
  brier_score?: number | null;
  roi?: number | null;
  yield?: number | null;
  max_drawdown?: number | null;
  clv_pct?: number | null;
  official_common_sample_rows?: number | null;
  official_sample_mismatch_detected?: boolean;
  [key: string]: unknown;
};

export type WalkForwardFold = {
  id: number;
  run_id: number;
  fold_index: number;
  model_version: string;
  model_name: string;
  dataset_path: string;
  status: WalkForwardFoldStatus | string;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  train_rows: number;
  test_rows: number;
  feature_set: string[];
  metrics:
    | (Record<string, unknown> & {
        official_benchmark?: WalkForwardOfficialBenchmarkMetrics;
      })
    | null;
  market_benchmark: Record<string, unknown> | null;
  coverage: Record<string, unknown> | null;
  leakage_flags: string[];
  skip_reason: string | null;
};

export type WalkForwardRun = {
  id: number;
  status: WalkForwardRunStatus | string;
  mode: WalkForwardMode | string;
  initial_train_days: number;
  test_days: number;
  step_days: number;
  min_train_rows: number;
  min_test_rows: number;
  embargo_days: number;
  edge_threshold: number;
  random_state: number;
  versions_requested: string;
  origin: string;
  current_phase?: string | null;
  progress_pct?: number | null;
  progress_current?: number | null;
  progress_total?: number | null;
  cancel_requested?: boolean;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  report_path: string | null;
  summary:
    | (Record<string, unknown> & {
        official_contenders?: string[];
        official_sample_mismatch_folds?: number;
        versions_detail?: Array<Record<string, unknown>>;
      })
    | null;
  error_message: string | null;
  created_at: string;
  created_by: string;
  folds: WalkForwardFold[];
};

export type WalkForwardRunListItem = {
  id: number;
  status: WalkForwardRunStatus | string;
  mode: WalkForwardMode | string;
  initial_train_days: number;
  test_days: number;
  step_days: number;
  versions_requested: string;
  origin: string;
  current_phase?: string | null;
  progress_pct?: number | null;
  progress_current?: number | null;
  progress_total?: number | null;
  cancel_requested?: boolean;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  created_at: string;
  created_by: string;
  folds_completed: number;
  folds_skipped: number;
  folds_errors: number;
  leakage_flags_total: number;
};

export type WalkForwardRunListResponse = {
  total: number;
  limit: number;
  offset: number;
  items: WalkForwardRunListItem[];
};

export type WalkForwardTriggerRequest = {
  mode?: WalkForwardMode;
  initial_train_days?: number;
  test_days?: number;
  step_days?: number;
  min_train_rows?: number;
  min_test_rows?: number;
  embargo_days?: number;
  edge_threshold?: number;
  random_state?: number;
  versions?: MLModelVersion[] | null;
  blocking?: boolean;
};

export type WalkForwardTriggerResponse = {
  run: WalkForwardRun;
  started: boolean;
  message: string;
};

export type WalkForwardCancelResponse = {
  run_id: number;
  status: WalkForwardRunStatus | string;
  message: string;
};

export type CalibrationMethod = "raw" | "platt" | "isotonic";
export type CalibrationRunStatus =
  | "pending"
  | "running"
  | "completed"
  | "completed_with_errors"
  | "failed"
  | "cancelled";

export type CalibrationResult = {
  id: number;
  run_id: number;
  model_version: string;
  model_name: string;
  dataset_path: string;
  date_min: string | null;
  date_max: string | null;
  oos_samples_total: number;
  aggregate: Record<string, unknown> | null;
  comparison: Record<string, unknown> | null;
  fold_outcomes: Record<string, unknown>[];
  artifacts: Record<string, string>;
  leakage_flags: string[];
  skip_reason: string | null;
};

export type CalibrationRun = {
  id: number;
  status: CalibrationRunStatus | string;
  walk_forward_run_id: number | null;
  n_bins: number;
  min_bin_samples: number;
  min_calibrator_train_samples: number;
  wf_mode: string;
  wf_initial_train_days: number;
  wf_test_days: number;
  wf_step_days: number;
  wf_min_train_rows: number;
  wf_min_test_rows: number;
  wf_embargo_days: number;
  wf_edge_threshold: number;
  wf_random_state: number;
  methods_requested: string;
  versions_requested: string;
  origin: string;
  current_phase?: string | null;
  progress_pct?: number | null;
  progress_current?: number | null;
  progress_total?: number | null;
  cancel_requested?: boolean;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  report_path: string | null;
  summary: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  created_by: string;
  results: CalibrationResult[];
};

export type CalibrationRunListItem = {
  id: number;
  status: CalibrationRunStatus | string;
  wf_mode: string;
  wf_initial_train_days: number;
  wf_test_days: number;
  wf_step_days: number;
  methods_requested: string;
  versions_requested: string;
  walk_forward_run_id: number | null;
  origin: string;
  current_phase?: string | null;
  progress_pct?: number | null;
  progress_current?: number | null;
  progress_total?: number | null;
  cancel_requested?: boolean;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  created_at: string;
  created_by: string;
  models_with_oos: number;
  oos_samples_total: number;
  leakage_flags_total: number;
};

export type CalibrationRunListResponse = {
  total: number;
  limit: number;
  offset: number;
  items: CalibrationRunListItem[];
};

export type CalibrationTriggerRequest = {
  n_bins?: number;
  min_bin_samples?: number;
  min_calibrator_train_samples?: number;
  methods?: CalibrationMethod[];
  mode?: WalkForwardMode;
  initial_train_days?: number;
  test_days?: number;
  step_days?: number;
  min_train_rows?: number;
  min_test_rows?: number;
  embargo_days?: number;
  edge_threshold?: number;
  random_state?: number;
  versions?: MLModelVersion[] | null;
  walk_forward_run_id?: number | null;
  blocking?: boolean;
};

export type CalibrationTriggerResponse = {
  run: CalibrationRun;
  started: boolean;
  message: string;
};

export type CalibrationCancelResponse = {
  run_id: number;
  status: CalibrationRunStatus | string;
  message: string;
};

export type BandAnalysisSource = "live" | "walk_forward" | "backtest";
export type BandDimension = "probability" | "edge";

export type ProbabilityBandBucket = {
  key: string;
  label: string;
  bin_start: number | null;
  bin_end: number | null;
  predictions_total: number;
  closed: number;
  void: number;
  open: number;
  won: number;
  lost: number;
  hit_rate_pct: number | null;
  mean_predicted_pct: number | null;
  mean_observed_pct: number | null;
  calibration_gap_pct: number | null;
  avg_odds: number | null;
  avg_edge_pct: number | null;
  stake_total: number;
  stake_settled: number;
  profit: number;
  roi_pct: number | null;
  yield_pct: number | null;
  hit_rate_ci_lower_pct: number | null;
  hit_rate_ci_upper_pct: number | null;
  insufficient_sample: boolean;
};

export type ProbabilityBandGroup = {
  fold_index: number | null;
  period: string | null;
  predictions_total: number;
  closed: number;
  void: number;
  open: number;
  won: number;
  lost: number;
  bands: ProbabilityBandBucket[];
};

export type ProbabilityBandAnalysis = {
  source: BandAnalysisSource;
  band_dimension: BandDimension;
  probability_kind: CalibrationMethod;
  n_bins: number;
  min_bin_samples: number;
  model_version: string | null;
  model_name: string | null;
  from_date: string | null;
  to_date: string | null;
  event_date_from: string | null;
  event_date_to: string | null;
  predictions_total: number;
  closed: number;
  void: number;
  open: number;
  won: number;
  lost: number;
  bands: ProbabilityBandBucket[];
  comparison: Record<string, ProbabilityBandBucket[]>;
  by_fold: ProbabilityBandGroup[];
  by_period: ProbabilityBandGroup[];
  notes: string[];
};

export type ProbabilityBandAnalysisParams = {
  source: BandAnalysisSource;
  band_dimension?: BandDimension;
  probability_kind?: CalibrationMethod;
  model_version?: MLModelVersion;
  model_name?: string;
  from?: string;
  to?: string;
  event_date_from?: string;
  event_date_to?: string;
  publication_source?: string;
  tournament_name?: string;
  surface?: string;
  odds_band?: string;
  latest_only?: boolean;
  n_bins?: number;
  min_bin_samples?: number;
  include_comparison?: boolean;
  group_by_fold?: boolean;
  group_by_period?: boolean;
};

export type SegmentDimension =
  | "surface"
  | "tournament"
  | "circuit"
  | "level"
  | "round"
  | "favorite_role"
  | "odds_band"
  | "bookmaker"
  | "model"
  | "version"
  | "period";

export type SegmentRoiBucket = {
  key: string;
  label: string;
  predictions_total: number;
  closed: number;
  void: number;
  open: number;
  won: number;
  lost: number;
  hit_rate_pct: number | null;
  avg_odds: number | null;
  avg_edge_pct: number | null;
  stake_total: number;
  stake_settled: number;
  profit: number;
  roi_pct: number | null;
  yield_pct: number | null;
  max_drawdown: number;
  hit_rate_ci_lower_pct: number | null;
  hit_rate_ci_upper_pct: number | null;
  roi_ci_lower_pct: number | null;
  roi_ci_upper_pct: number | null;
  insufficient_sample: boolean;
};

export type SegmentRoiGroup = {
  fold_index: number | null;
  period: string | null;
  predictions_total: number;
  closed: number;
  void: number;
  open: number;
  won: number;
  lost: number;
  segments: SegmentRoiBucket[];
};

export type SegmentRoiAnalysis = {
  source: BandAnalysisSource;
  segment_dimension: SegmentDimension;
  min_segment_samples: number;
  model_version: string | null;
  model_name: string | null;
  from_date: string | null;
  to_date: string | null;
  event_date_from: string | null;
  event_date_to: string | null;
  predictions_total: number;
  closed: number;
  void: number;
  open: number;
  won: number;
  lost: number;
  segments: SegmentRoiBucket[];
  by_fold: SegmentRoiGroup[];
  by_period: SegmentRoiGroup[];
  notes: string[];
};

export type SegmentRoiAnalysisParams = {
  source: BandAnalysisSource;
  segment_dimension?: SegmentDimension;
  model_version?: MLModelVersion;
  model_name?: string;
  from?: string;
  to?: string;
  event_date_from?: string;
  event_date_to?: string;
  publication_source?: string;
  tournament_name?: string;
  surface?: string;
  odds_band?: string;
  latest_only?: boolean;
  min_segment_samples?: number;
  group_by_fold?: boolean;
  group_by_period?: boolean;
};

export type PublicModelRegistryStatus = "candidate" | "active" | "retired";

export type PublicModelRegistryArtifacts = {
  model_pkl: string | null;
  metrics_path: string | null;
  model_exists: boolean;
  metrics_exists: boolean;
  walk_forward_run_id: number | null;
  calibration_run_id: number | null;
  calibration_artifacts: Record<string, string>;
};

export type PublicModelRegistryEntry = {
  id: number;
  model_version: string;
  model_name: string;
  status: PublicModelRegistryStatus;
  activated_at: string | null;
  retired_at: string | null;
  approval_metrics: Record<string, unknown>;
  motivation: string | null;
  artifacts: PublicModelRegistryArtifacts;
  supersedes_entry_id: number | null;
  walk_forward_run_id: number | null;
  calibration_run_id: number | null;
  created_at: string;
  created_by: string;
  updated_at: string;
};

export type PublicModelRegistryListResponse = {
  total: number;
  limit: number;
  offset: number;
  items: PublicModelRegistryEntry[];
  active: PublicModelRegistryEntry | null;
};

export type PublicModelRegistryCandidateCreate = {
  model_version: MLModelVersion;
  model_name: string;
  motivation?: string | null;
  approval_metrics?: Record<string, unknown> | null;
  walk_forward_run_id?: number | null;
  calibration_run_id?: number | null;
};

export type PublicModelRegistryActionResponse = {
  entry: PublicModelRegistryEntry;
  previous_active: PublicModelRegistryEntry | null;
  message: string;
};
