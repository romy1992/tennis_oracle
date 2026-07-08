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

export type PickStatus = "pending" | "won" | "lost";
export type SlipStatus = "pending" | "won" | "lost";

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
  confidence: number | null;
  pick_score: number | null;
  pick_status: PickStatus;
  actual_winner_label: string | null;
  is_correct: boolean | null;
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
  picks_total: number;
  resolved_combined_odds: number | null;
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
