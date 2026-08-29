import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { LiveMatchesPanel, MatchScoreSnapshot } from "../components/LiveMatchesPanel";
import { useGlobalUpdate } from "../hooks/useGlobalUpdate";
import { apiClient } from "../services/apiClient";
import type {
  BettingSlip,
  BettingSlipCalendarDay,
  BettingSlipCalendarResponse,
  BettingSlipPick,
  BettingSlipStatsResponse,
  BettingSlipsDailyResponse,
  MLModelVersion,
  ModelsVersionsResultsResponse,
  SlipKind,
  SlipStrategyFamily
} from "../types/api";
import { classifySingleBetValue } from "../utils/minEdge";
import {
  DEFAULT_MODEL_VERSION,
  modelVersionLabel,
  resolvePreferredModelVersion,
  writeStoredModelVersion
} from "../utils/modelVersion";
import { formatDate, todayLocalISODate } from "../utils/tennis";
import { formatLiveScore, isLiveMatch } from "../utils/liveScore";

const STAKE_PRESETS = [1, 5, 10, 25, 50];
const LIVE_UI_REFRESH_MS = 60_000;
const STRATEGY_TABS: Array<{
  key: SlipStrategyFamily;
  label: string;
  description: string;
}> = [
  {
    key: "generic",
    label: "Generiche",
    description: "Profili storici attuali, conservati senza modifiche."
  },
  {
    key: "play_only",
    label: "Solo PLAY",
    description: "Solo pick PLAY su eventi distinti e tutti i mercati."
  },
  {
    key: "strong_markets",
    label: "Mercati forti",
    description: "Strategia v1 concentrata sul vincitore del primo set."
  },
  {
    key: "selective",
    label: "Selettive",
    description: "Poche pick prudenti; puo anche non produrre alcun consiglio."
  }
];

function strategyFamilyOf(slip: BettingSlip): SlipStrategyFamily {
  return slip.strategy_family ?? "generic";
}

async function downloadBrowserFile(
  file: { blob: Blob; filename: string | null },
  fallbackName: string
) {
  if (typeof window.URL?.createObjectURL !== "function") {
    throw new Error("Download non supportato da questo browser.");
  }
  const url = window.URL.createObjectURL(file.blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = file.filename || fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

function marketLabel(market: string | null | undefined) {
  if (market === "over_under_games") return "Over/Under Games";
  if (market === "first_set_winner") return "Vincitore 1° set";
  return "Vincitore partita";
}

function formatProb(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${(value * 100).toLocaleString("it-IT", { maximumFractionDigits: 1 })}%`;
}

function formatTime(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(0, 5);
}

function formatOdds(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("it-IT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `${value.toLocaleString("it-IT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })} €`;
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 1 })}%`;
}

function formatSignedPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("it-IT", { maximumFractionDigits: 1 })}%`;
}

function formatSignedRoi(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toLocaleString("it-IT", { maximumFractionDigits: 1 })}%`;
}

function valueDecisionClass(decision: string | null | undefined) {
  if (decision === "PLAY") return "play";
  if (decision === "BORDERLINE") return "borderline";
  if (decision === "NO BET") return "no-bet";
  return "pending";
}

function pickDotClass(status: BettingSlipPick["pick_status"]) {
  if (status === "won") return "win";
  if (status === "lost") return "loss";
  if (status === "void") return "void";
  return "pending";
}

function slipStatusLabel(status: BettingSlip["slip_status"], historicalOutcomesMissing = false) {
  if (status === "won") return "Presa";
  if (status === "lost") return "Persa";
  if (status === "void") return "Annullata";
  if (historicalOutcomesMissing) return "Esito mancante";
  return "In corso";
}

function computeStakeValues(slip: BettingSlip, stake: number) {
  const oddsForPayout =
    slip.effective_combined_odds != null && slip.picks_void
      ? slip.effective_combined_odds
      : slip.effective_combined_odds != null && slip.slip_status === "won"
        ? slip.effective_combined_odds
        : slip.combined_odds;
  const displayOdds =
    slip.effective_combined_odds != null &&
    (slip.picks_void ?? 0) > 0
      ? slip.effective_combined_odds
      : slip.combined_odds;
  const potentialReturn = stake * displayOdds;
  const potentialProfit = potentialReturn - stake;
  let actualOutcome: number | null = null;
  if (slip.slip_status === "won") {
    actualOutcome = stake * (slip.effective_combined_odds ?? oddsForPayout);
  } else if (slip.slip_status === "lost") {
    actualOutcome = -stake;
  } else if (slip.slip_status === "void") {
    actualOutcome = 0;
  }
  return { potentialReturn, potentialProfit, actualOutcome, displayOdds };
}

function buildSlipClipboard(slip: BettingSlip, stake: number) {
  const lines = slip.picks.map((pick) => {
    const statusNote =
      pick.pick_status === "void"
        ? ` [ANNULLATA: ${pick.void_reason ?? pick.match_lifecycle_label ?? "void"}]`
        : pick.match_lifecycle_status &&
            pick.match_lifecycle_status !== "upcoming" &&
            pick.match_lifecycle_status !== "completed" &&
            pick.match_lifecycle_status !== "scheduled" &&
            pick.match_lifecycle_status !== "finished"
          ? ` [${pick.match_lifecycle_label}]`
          : "";
    return `${formatTime(pick.event_time)} ${pick.tournament_name ?? "-"} | ${pick.player_1 ?? "?"} vs ${pick.player_2 ?? "?"} -> ${pick.predicted_winner_label ?? "-"} @ ${formatOdds(pick.odds)} (void ${formatOdds(pick.void_odds)}, margine ${formatSignedPct(pick.edge_percent)})${statusNote}`;
  });
  const { potentialReturn, displayOdds } = computeStakeValues(slip, stake);
  const oddsLine =
    (slip.picks_void ?? 0) > 0 && slip.effective_combined_odds != null
      ? `Quota originale: ${formatOdds(slip.combined_odds)} | Quota effettiva: ${formatOdds(slip.effective_combined_odds)}`
      : `Quota combinata: ${formatOdds(displayOdds)}`;
  return [
    `${slip.label} (${slipStatusLabel(slip.slip_status)})`,
    ...lines,
    `${oddsLine} | Puntata: ${formatMoney(stake)} | Vincita potenziale: ${formatMoney(potentialReturn)}`
  ].join("\n");
}

function calendarDayLabel(day: BettingSlipCalendarDay) {
  if (day.is_today) return "Oggi";
  const parsed = new Date(`${day.date}T12:00:00`);
  return parsed.toLocaleDateString("it-IT", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit"
  });
}

function SlipStatsPanel({
  title,
  subtitle,
  stats,
  focusKind,
  focusStrategyFamily
}: {
  title: string;
  subtitle: string;
  stats: BettingSlipStatsResponse | null;
  focusKind?: "parlay" | "ladder";
  focusStrategyFamily?: SlipStrategyFamily;
}) {
  const daysWithSlips = [...(stats?.days ?? [])]
    .filter((day) => day.slips_total > 0)
    .sort((left, right) => right.date.localeCompare(left.date));

  const profiles = (stats?.summary.by_profile ?? []).filter((profile) => {
    const kindMatches = focusKind ? (profile.slip_kind ?? "parlay") === focusKind : true;
    const familyMatches = focusStrategyFamily
      ? (profile.strategy_family ?? "generic") === focusStrategyFamily
      : true;
    return kindMatches && familyMatches;
  });
  const strategies = (stats?.summary.by_strategy ?? []).filter((strategy) =>
    focusKind ? strategy.slip_kind === focusKind : true
  );
  const activeStrategy = focusStrategyFamily
    ? strategies.find((strategy) => strategy.strategy_family === focusStrategyFamily)
    : undefined;
  const scopedStats =
    activeStrategy ??
    (focusStrategyFamily === "generic" && strategies.length === 0 ? stats?.summary : undefined);

  if (!stats || !scopedStats || scopedStats.slips_total === 0) {
    return (
      <section className="panel slip-stats-panel">
        <header className="section-header">
          <div>
            <h3>{title}</h3>
            <p>{subtitle}</p>
          </div>
        </header>
        <EmptyState
          title="Nessun dato per questa strategia"
          message="Il sub-tab non ha ancora schedine o scalate salvate nel periodo selezionato."
        />
      </section>
    );
  }

  return (
    <section className="panel slip-stats-panel">
      <header className="section-header">
        <div>
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
      </header>
      <div className="metrics-grid">
        <div className="metric-card">
          <span>Schedine totali</span>
          <strong>{scopedStats.slips_total}</strong>
        </div>
        <div className="metric-card">
          <span>Win rate schedine</span>
          <strong>{formatPct(scopedStats.slip_win_rate_pct)}</strong>
        </div>
        <div className="metric-card">
          <span>Hit rate pick</span>
          <strong>{formatPct(scopedStats.pick_hit_rate_pct)}</strong>
        </div>
        <div className="metric-card">
          <span>Profitto teorico</span>
          <strong>{formatMoney(scopedStats.theoretical_profit_units)}</strong>
        </div>
        <div className="metric-card">
          <span>ROI per schedina</span>
          <strong>{formatPct(scopedStats.theoretical_roi_pct)}</strong>
        </div>
      </div>

      {strategies.length > 1 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Strategia</th>
                <th>Chiuse</th>
                <th>Prese</th>
                <th>Perse</th>
                <th>Win rate</th>
                <th>Profitto</th>
                <th>ROI</th>
                <th>ROI giornaliero</th>
                <th>Giorni</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((strategy) => (
                <tr
                  key={`${strategy.slip_kind}-${strategy.strategy_family}`}
                  className={strategy.strategy_family === focusStrategyFamily ? "active-row" : undefined}
                >
                  <td>{strategy.label}</td>
                  <td>{strategy.slips_won + strategy.slips_lost}</td>
                  <td>{strategy.slips_won}</td>
                  <td>{strategy.slips_lost}</td>
                  <td>{formatPct(strategy.slip_win_rate_pct)}</td>
                  <td>{formatMoney(strategy.theoretical_profit_units)}</td>
                  <td>{formatPct(strategy.theoretical_roi_pct)}</td>
                  <td>{formatPct(strategy.daily_portfolio_roi_pct)}</td>
                  <td>{strategy.comparable_days}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {!focusStrategyFamily && daysWithSlips.length > 1 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Data</th>
                <th>Schedine</th>
                <th>Prese</th>
                <th>Perse</th>
                <th>In corso</th>
                <th>Hit pick</th>
                <th>Win rate</th>
                <th>Profitto</th>
                <th>ROI</th>
              </tr>
            </thead>
            <tbody>
              {daysWithSlips.map((day) => (
                <tr key={day.date}>
                  <td>{formatDate(day.date)}</td>
                  <td>{day.slips_total}</td>
                  <td>{day.slips_won}</td>
                  <td>{day.slips_lost}</td>
                  <td>{day.slips_pending}</td>
                  <td>{formatPct(day.pick_hit_rate_pct)}</td>
                  <td>{formatPct(day.slip_win_rate_pct)}</td>
                  <td>{formatMoney(day.theoretical_profit_units)}</td>
                  <td>{formatPct(day.theoretical_roi_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {profiles.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Profilo</th>
                <th>Tipo</th>
                <th>Schedine</th>
                <th>Prese</th>
                <th>Perse</th>
                <th>Win rate</th>
                <th>Profitto</th>
                <th>ROI</th>
              </tr>
            </thead>
            <tbody>
              {profiles.map((profile) => (
                <tr key={profile.slip_key}>
                  <td>{profile.label}</td>
                  <td>{(profile.slip_kind ?? "parlay") === "ladder" ? "Scalata" : "Schedina"}</td>
                  <td>{profile.slips_total}</td>
                  <td>{profile.slips_won}</td>
                  <td>{profile.slips_lost}</td>
                  <td>{formatPct(profile.slip_win_rate_pct)}</td>
                  <td>{formatMoney(profile.theoretical_profit_units)}</td>
                  <td>{formatPct(profile.theoretical_roi_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function truncateText(value: string | null | undefined, maxLength = 28) {
  if (!value) return "-";
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1)}…`;
}

function pickOutcomeLabel(status: BettingSlipPick["pick_status"]) {
  if (status === "won") return "Pick vinta";
  if (status === "lost") return "Pick persa";
  if (status === "void") return "Pick annullata";
  return null;
}

function resolvePickDisplay(pick: BettingSlipPick, globalMinEdge: number) {
  let decision = pick.value_decision;
  if (pick.odds != null && pick.void_odds != null) {
    decision = classifySingleBetValue(pick.odds, pick.void_odds, globalMinEdge);
  }
  return { decision };
}

function SlipCard({
  slip,
  stake,
  historicalOutcomesMissing,
  globalMinEdge,
  downloadingImage = false,
  onDownloadImage
}: {
  slip: BettingSlip;
  stake: number;
  historicalOutcomesMissing: boolean;
  globalMinEdge: number;
  downloadingImage?: boolean;
  onDownloadImage?: () => void;
}) {
  const isLadder = (slip.slip_kind ?? "parlay") === "ladder";
  const { potentialReturn, potentialProfit, actualOutcome, displayOdds } = computeStakeValues(slip, stake);
  const hasRecalculatedOdds =
    (slip.picks_void ?? 0) > 0 &&
    slip.effective_combined_odds != null &&
    slip.effective_combined_odds !== slip.combined_odds;

  async function copySlip() {
    await navigator.clipboard.writeText(buildSlipClipboard(slip, stake));
  }

  return (
    <article className={`panel slip-card ${slip.slip_status}${isLadder ? " slip-card-ladder" : ""}`}>
      <header className="slip-card-header">
        <div className="slip-card-title">
          <span className="pill">{slip.label}</span>
          {isLadder ? <span className="pill">Scalata</span> : null}
          <p className="slip-description">{slip.description}</p>
        </div>
        <div className="slip-card-meta">
          <span className={`slip-status-badge ${slip.slip_status}`}>
            {slipStatusLabel(slip.slip_status, historicalOutcomesMissing)}
          </span>
          <span className="slip-pick-counter">
            {isLadder
              ? `${slip.picks_won}/${slip.picks_total - (slip.picks_void ?? 0)} step ok`
              : `${slip.picks_won}/${slip.picks_total - (slip.picks_void ?? 0)} pick corrette`}
            {(slip.picks_void ?? 0) > 0 ? ` · ${slip.picks_void} annullate` : ""}
          </span>
        </div>
      </header>

      <div className="table-wrap slip-table-wrap">
        <table className="slip-picks-table">
          <thead>
            <tr>
              <th className="slip-col-status">Esito</th>
              {isLadder ? <th>Step</th> : null}
              <th>Ora</th>
              <th>Torneo</th>
              <th>Match</th>
              <th>Mercato</th>
              <th>Pick</th>
              {isLadder ? <th className="slip-col-odds">Puntata step</th> : null}
              <th className="slip-col-odds">Media quote bookmakers</th>
              {isLadder ? <th className="slip-col-odds">Ritorno se presa</th> : null}
              {!isLadder ? <th>Void</th> : null}
              {!isLadder ? <th>Edge</th> : null}
              {!isLadder ? <th>ROI</th> : null}
              <th>Valore</th>
              <th>Conf.</th>
            </tr>
          </thead>
          <tbody>
            {slip.picks.map((pick) => {
              const display = resolvePickDisplay(pick, globalMinEdge);
              const live = isLiveMatch(pick);
              const completed =
                pick.pick_status === "won" ||
                pick.pick_status === "lost" ||
                pick.match_lifecycle_status === "completed";
              const pickTitle =
                pick.pick_status === "won"
                  ? "Presa"
                  : pick.pick_status === "lost"
                    ? "Persa"
                    : pick.pick_status === "void"
                      ? pick.void_reason ?? pick.match_lifecycle_label ?? "Annullata"
                      : pick.match_lifecycle_label && pick.match_lifecycle_status === "postponed"
                        ? pick.match_lifecycle_label
                        : historicalOutcomesMissing
                          ? "Esito non disponibile"
                          : live
                            ? "LIVE"
                            : ["upcoming", "scheduled"].includes(
                                  pick.match_lifecycle_status ?? "",
                                )
                              ? "Da giocare"
                              : "In corso";
              return (
              <tr
                key={`${pick.event_key}-${pick.market}`}
                className={pick.pick_status === "void" ? "pick-void" : undefined}
              >
                <td className="slip-col-status">
                  <span className="pick-outcome-state" title={pickTitle}>
                    <span className={`result-dot ${pickDotClass(pick.pick_status)}`} />
                    <span>{pickTitle}</span>
                  </span>
                </td>
                {isLadder ? (
                  <td className="slip-col-time">{pick.ladder_step_index ?? "—"}</td>
                ) : null}
                <td className="slip-col-time">{formatTime(pick.event_time)}</td>
                <td className="slip-col-tournament" title={pick.tournament_name ?? undefined}>
                  {truncateText(pick.tournament_name, 32)}
                </td>
                <td className="slip-col-match">
                  {pick.player_1 ?? "?"} vs {pick.player_2 ?? "?"}
                  <MatchScoreSnapshot
                    live={live}
                    completed={completed}
                    score={pick.live_score}
                    winnerLabel={
                      pick.actual_winner_label ? `Esito reale: ${pick.actual_winner_label}` : null
                    }
                    outcomeLabel={pickOutcomeLabel(pick.pick_status)}
                  />
                  {pick.match_lifecycle_label &&
                  pick.match_lifecycle_status &&
                  !live &&
                  !completed &&
                  !["upcoming", "completed", "scheduled", "finished"].includes(
                    pick.match_lifecycle_status,
                  ) ? (
                    <small className={`match-lifecycle-chip ${pick.match_lifecycle_status}`}>
                      {pick.match_lifecycle_label}
                    </small>
                  ) : null}
                </td>
                <td className="slip-col-market">
                  <span className={`market-badge market-${pick.market}`}>{marketLabel(pick.market)}</span>
                </td>
                <td className="slip-col-pick">
                  <strong>{pick.predicted_winner_label ?? "-"}</strong>
                </td>
                {isLadder ? (
                  <td className="slip-col-odds">{formatMoney(pick.ladder_step_stake)}</td>
                ) : null}
                <td className="slip-col-odds">{formatOdds(pick.odds)}</td>
                {isLadder ? (
                  <td className="slip-col-odds">{formatMoney(pick.ladder_step_return_if_won)}</td>
                ) : null}
                {!isLadder ? <td className="slip-col-value">{formatOdds(pick.void_odds)}</td> : null}
                {!isLadder ? (
                  <td className={`slip-col-value ${pick.edge_percent !== null && pick.edge_percent >= 0 ? "positive-value" : "negative-value"}`}>
                    {formatSignedPct(pick.edge_percent)}
                  </td>
                ) : null}
                {!isLadder ? (
                  <td className={`slip-col-value ${pick.expected_roi !== null && pick.expected_roi >= 0 ? "positive-value" : "negative-value"}`}>
                    {formatSignedRoi(pick.expected_roi)}
                  </td>
                ) : null}
                <td className="slip-col-value-state">
                  {display.decision ? (
                    <span className={`value-decision-badge ${valueDecisionClass(display.decision)}`}>
                      {display.decision}
                    </span>
                  ) : (
                    "—"
                  )}
                  {pick.value_label ? <small>{pick.value_label}</small> : null}
                </td>
                <td className="slip-col-confidence">{formatProb(pick.confidence)}</td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <footer className="slip-card-footer">
        <div className="slip-metrics-grid">
          <div>
            <span>{hasRecalculatedOdds ? "Quota effettiva" : isLadder ? "Moltiplicatore catena" : "Quota combinata"}</span>
            <strong>{formatOdds(displayOdds)}</strong>
            {hasRecalculatedOdds ? (
              <small className="slip-odds-note">Originale {formatOdds(slip.combined_odds)}</small>
            ) : null}
          </div>
          <div>
            <span>{isLadder ? "Puntata iniziale" : "Puntata"}</span>
            <strong>{formatMoney(stake)}</strong>
          </div>
          <div>
            <span>{isLadder ? "Ritorno se tutta presa" : "Vincita potenziale"}</span>
            <strong>{formatMoney(potentialReturn)}</strong>
          </div>
          <div>
            <span>Profitto</span>
            <strong>{formatMoney(potentialProfit)}</strong>
          </div>
          {actualOutcome !== null ? (
            <div>
              <span>Esito</span>
              <strong className={actualOutcome >= 0 ? "positive-value" : "negative-value"}>
                {formatMoney(actualOutcome)}
              </strong>
            </div>
          ) : null}
        </div>
        <div className="slip-card-actions">
          <button type="button" className="action-button" onClick={() => void copySlip()}>
            {isLadder ? "Copia scalata" : "Copia schedina"}
          </button>
          <button
            type="button"
            className="action-button secondary"
            onClick={() => onDownloadImage?.()}
            disabled={!onDownloadImage || downloadingImage}
          >
            {downloadingImage ? "Download..." : "Scarica immagine"}
          </button>
        </div>
      </footer>
    </article>
  );
}

export function BettingSlipsPage() {
  const { lastCompletedAt } = useGlobalUpdate();
  const [availableVersions, setAvailableVersions] = useState<ModelsVersionsResultsResponse["versions"]>([]);
  const [activeVersion, setActiveVersion] = useState<MLModelVersion>(DEFAULT_MODEL_VERSION);
  const [calendar, setCalendar] = useState<BettingSlipCalendarResponse | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>(() => todayLocalISODate());
  const [dailyByModel, setDailyByModel] = useState<Record<string, BettingSlipsDailyResponse>>({});
  const [dayStatsByModel, setDayStatsByModel] = useState<Record<string, BettingSlipStatsResponse>>({});
  const [overallStatsByModel, setOverallStatsByModel] = useState<Record<string, BettingSlipStatsResponse>>({});
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [stake, setStake] = useState(10);
  const [minEdgePercent, setMinEdgePercent] = useState(2);
  const [viewKind, setViewKind] = useState<SlipKind>("parlay");
  const [strategyFamily, setStrategyFamily] = useState<SlipStrategyFamily>("generic");
  const [loading, setLoading] = useState(true);
  const [loadingDay, setLoadingDay] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [downloadingZip, setDownloadingZip] = useState(false);
  const [downloadingSlipKey, setDownloadingSlipKey] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastReloadToken, setLastReloadToken] = useState<string | null>(null);

  const activeModels = useMemo(
    () =>
      availableVersions.find((entry) => entry.version === activeVersion)?.models.map((m) => m.model) ??
      [],
    [availableVersions, activeVersion]
  );

  useEffect(() => {
    if (!activeModels.length) return;
    if (!selectedModel || !activeModels.includes(selectedModel)) {
      setSelectedModel(activeModels[0]);
    }
  }, [activeModels, selectedModel]);

  useEffect(() => {
    async function loadCatalog() {
      try {
        const catalog = await apiClient.getModelsVersionsResults();
        setAvailableVersions(catalog.versions);
        if (catalog.versions.length === 0) {
          setError(
            "Nessun modello disponibile nel catalogo. Verifica il modello pubblico attivo."
          );
          setLoading(false);
          return;
        }
        setError(null);
        if (catalog.versions.length > 0) {
          setActiveVersion(resolvePreferredModelVersion(catalog.versions));
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Catalogo modelli non disponibile.");
        setLoading(false);
      }
    }
    void loadCatalog();
  }, [lastCompletedAt]);

  const selectedCalendarDay = useMemo(
    () => calendar?.days.find((day) => day.date === selectedDate) ?? null,
    [calendar, selectedDate]
  );

  const loadDayData = useCallback(async (
    date: string,
    options?: { regenerate?: boolean; minEdge?: number; dailyOnly?: boolean }
  ) => {
    const models = activeModels.length ? activeModels : ["logistic_regression"];
    // Do not put minEdgePercent in deps: margin changes reclassify client-side without refetch.
    // Regenerate/global-update callers pass minEdge explicitly.
    const edgeForRequest = options?.minEdge ?? 0;
    const dailyResponses = await Promise.all(
      models.map((modelName) =>
        options?.regenerate
          ? apiClient.regenerateDailyBettingSlips({
              model_version: activeVersion,
              model_name: modelName,
              stake,
              date,
              min_edge_percent: edgeForRequest
            })
          : apiClient.getDailyBettingSlips({
              model_version: activeVersion,
              model_name: modelName,
              stake,
              date,
              min_edge_percent: edgeForRequest
            })
      )
    );
    const dayStatsResponses = options?.dailyOnly
      ? []
      : await Promise.all(
          models.map((modelName) =>
            apiClient.getBettingSlipStats({
              model_version: activeVersion,
              model_name: modelName,
              from: date,
              to: date,
              stake
            })
          )
        );
    const overallStatsResponses = options?.dailyOnly
      ? []
      : await Promise.all(
          models.map((modelName) =>
            apiClient.getBettingSlipStats({
              model_version: activeVersion,
              model_name: modelName,
              all_time: true,
              stake
            })
          )
        );

    const dailyMap: Record<string, BettingSlipsDailyResponse> = {};
    const statsMap: Record<string, BettingSlipStatsResponse> = {};
    const overallMap: Record<string, BettingSlipStatsResponse> = {};
    models.forEach((modelName, index) => {
      dailyMap[modelName] = dailyResponses[index];
      statsMap[modelName] = dayStatsResponses[index];
      overallMap[modelName] = overallStatsResponses[index];
    });
    setDailyByModel(dailyMap);
    if (!options?.dailyOnly) {
      setDayStatsByModel(statsMap);
      setOverallStatsByModel(overallMap);
    }
  }, [stake, activeVersion, activeModels]);

  useEffect(() => {
    async function loadCalendar() {
      try {
        setLoading(true);
        const firstModel = activeModels[0] ?? "logistic_regression";
        const calendarData = await apiClient.getBettingSlipCalendar({
          model_version: activeVersion,
          model_name: firstModel
        });
        setCalendar(calendarData);
        const initialDate = calendarData.days.some((day) => day.is_today)
          ? calendarData.today
          : calendarData.days[0]?.date ?? calendarData.today;
        setSelectedDate(initialDate);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }
    if (activeModels.length) {
      void loadCalendar();
    }
  }, [activeVersion, activeModels]);

  useEffect(() => {
    if (!calendar) return;
    async function reloadSelectedDay() {
      try {
        setLoadingDay(true);
        await loadDayData(selectedDate);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoadingDay(false);
      }
    }
    void reloadSelectedDay();
  }, [calendar, selectedDate, loadDayData]);

  useEffect(() => {
    if (!selectedCalendarDay?.is_today) return;
    const timer = window.setInterval(() => {
      void loadDayData(selectedDate, { dailyOnly: true }).catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Aggiornamento live non riuscito.");
      });
    }, LIVE_UI_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [loadDayData, selectedCalendarDay?.is_today, selectedDate]);

  useEffect(() => {
    if (
      !activeModels.length ||
      !lastCompletedAt ||
      lastCompletedAt === lastReloadToken
    ) {
      return;
    }
    setLastReloadToken(lastCompletedAt);
    const shouldRegenerate = !selectedCalendarDay?.is_past;
    void loadDayData(selectedDate, {
      regenerate: shouldRegenerate,
      minEdge: minEdgePercent
    }).then(() => {
      setActionMessage(
        shouldRegenerate
          ? "Schedine aggiornate in modalità append-only dall'ultima run globale."
          : "Schedine aggiornate dall'ultima run globale."
      );
    });
  }, [
    activeModels.length,
    lastCompletedAt,
    lastReloadToken,
    loadDayData,
    selectedDate,
    selectedCalendarDay?.is_past
  ]);

  async function handleRegenerate() {
    if (selectedCalendarDay?.is_past) {
      setActionMessage("Le schedine storiche sono definitive: seleziona oggi o un giorno futuro.");
      return;
    }
    try {
      setRegenerating(true);
      setActionMessage(null);
      await loadDayData(selectedDate, { regenerate: true, minEdge: minEdgePercent });
      setActionMessage("Schedine e scalate arricchite con le nuove pick disponibili.");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore inatteso.");
    } finally {
      setRegenerating(false);
    }
  }

  async function handleDownloadAllImages() {
    const daily = selectedModel ? dailyByModel[selectedModel] : undefined;
    if (!selectedModel || !daily?.slips.length) {
      setActionMessage("Nessuna schedina da scaricare per la giocata selezionata.");
      return;
    }
    try {
      setDownloadingZip(true);
      setActionMessage(null);
      const file = await apiClient.downloadBettingSlipImagesZip({
        date: selectedDate,
        model_version: activeVersion,
        model_name: selectedModel,
        stake,
        min_edge_percent: minEdgePercent
      });
      await downloadBrowserFile(
        file,
        `schedine_${selectedDate}_${activeVersion}_${selectedModel}.zip`
      );
      setActionMessage("Immagini di tutte le schedine scaricate.");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download immagini non riuscito.");
    } finally {
      setDownloadingZip(false);
    }
  }

  async function handleDownloadSlipImage(slipKey: string) {
    if (!selectedModel) return;
    try {
      setDownloadingSlipKey(slipKey);
      setActionMessage(null);
      const file = await apiClient.downloadBettingSlipImage({
        date: selectedDate,
        model_version: activeVersion,
        model_name: selectedModel,
        stake,
        min_edge_percent: minEdgePercent,
        slip_key: slipKey
      });
      await downloadBrowserFile(file, `${slipKey}.png`);
      setActionMessage(`Immagine schedina ${slipKey} scaricata.`);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download immagine non riuscito.");
    } finally {
      setDownloadingSlipKey(null);
    }
  }

  if (loading) {
    return <LoadingState title="Caricamento schedine..." />;
  }

  if (error && Object.keys(dailyByModel).length === 0) {
    return <ErrorState title="Schedine non disponibili" message={error} />;
  }

  const pastDays = calendar?.days.filter((day) => day.is_past) ?? [];
  const upcomingDays = calendar?.days.filter((day) => !day.is_past) ?? [];
  const selectedDaily = selectedModel ? dailyByModel[selectedModel] : undefined;
  const selectedDayStats = selectedModel ? dayStatsByModel[selectedModel] ?? null : null;
  const selectedOverallStats = selectedModel ? overallStatsByModel[selectedModel] ?? null : null;
  const visibleSlips = (selectedDaily?.slips ?? []).filter(
    (slip) =>
      (slip.slip_kind ?? (slip.slip_key.startsWith("ladder_") ? "ladder" : "parlay")) ===
        viewKind && strategyFamilyOf(slip) === strategyFamily
  );
  const selectedStrategy =
    STRATEGY_TABS.find((strategy) => strategy.key === strategyFamily) ?? STRATEGY_TABS[0];
  const historicalOutcomesMissing =
    Boolean(selectedCalendarDay?.is_past) &&
    Boolean(selectedDaily?.slips.some((slip) => slip.picks_pending > 0));
  const livePickByEvent = new Map<number, BettingSlipPick>();
  for (const slip of selectedDaily?.slips ?? []) {
    for (const pick of slip.picks) {
      if (isLiveMatch(pick) && !livePickByEvent.has(pick.event_key)) {
        livePickByEvent.set(pick.event_key, pick);
      }
    }
  }
  const livePanelItems = Array.from(livePickByEvent.values()).map((pick) => ({
    eventKey: pick.event_key,
    player1: pick.player_1,
    player2: pick.player_2,
    tournament: pick.tournament_name,
    score: formatLiveScore(pick.live_score),
    status: pick.event_status ?? pick.match_lifecycle_label ?? null,
    detail: `Pick: ${pick.predicted_winner_label ?? pick.predicted_winner}`
  }));

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Consiglio schedina</h2>
          <p>
            {formatDate(selectedDate)} · Confronta Schedine e Scalate nelle quattro strategie
            persistite · mercati Match / 1° set / O/U
          </p>
        </div>
        <div className="page-header-actions">
          <label className="min-edge-field">
            <span>Margine sicurezza</span>
            <input
              type="number"
              min={0}
              max={100}
              step={0.5}
              value={minEdgePercent}
              onChange={(event) => setMinEdgePercent(Number(event.target.value) || 0)}
            />
            <small>% sopra quota void (default 2). A 0% solo BORDERLINE → PLAY; NO BET resta se quota &lt; void.</small>
          </label>
          <button
            type="button"
            className="action-button"
            onClick={() => void handleRegenerate()}
            disabled={regenerating || loadingDay || Boolean(selectedCalendarDay?.is_past)}
          >
            {regenerating ? "Aggiornamento..." : "Arricchisci schedine"}
          </button>
          <button
            type="button"
            className="action-button secondary"
            onClick={() => void handleDownloadAllImages()}
            disabled={
              downloadingZip ||
              loadingDay ||
              !selectedModel ||
              !(selectedDaily?.slips.length)
            }
          >
            {downloadingZip ? "Download immagini..." : "Scarica immagini"}
          </button>
        </div>
      </header>

      {availableVersions.length > 1 ? (
        <div className="tab-list" aria-label="Versioni modello">
          {availableVersions.map((entry) => (
            <button
              key={entry.version}
              type="button"
              className={activeVersion === entry.version ? "active" : undefined}
              onClick={() => {
                const next = entry.version as MLModelVersion;
                writeStoredModelVersion(next);
                setActiveVersion(next);
              }}
            >
              {modelVersionLabel(entry.version)}
            </button>
          ))}
        </div>
      ) : null}

      <LiveMatchesPanel items={livePanelItems} />

      {calendar ? (
        <article className="panel">
          <div className="panel-header">
            <h3>Calendario schedine</h3>
            <span className="pill pill-ok">
              {formatDate(calendar.window_from)} → {formatDate(calendar.window_to)}
            </span>
          </div>
          {pastDays.length ? (
            <>
              <p className="calendar-section-label">Storico</p>
              <div className="slip-day-tabs" aria-label="Giorni storici">
                {pastDays.map((day) => (
                  <button
                    key={day.date}
                    type="button"
                    className={`slip-day-tab past ${selectedDate === day.date ? "active" : ""}`}
                    onClick={() => setSelectedDate(day.date)}
                  >
                    {calendarDayLabel(day)}
                    {day.has_slips ? <span className="slip-day-badge">{day.slip_count}</span> : null}
                  </button>
                ))}
              </div>
            </>
          ) : null}
          <p className="calendar-section-label">Prossime giornate</p>
          <div className="slip-day-tabs" aria-label="Giorni disponibili">
            {upcomingDays.map((day) => (
              <button
                key={day.date}
                type="button"
                className={`slip-day-tab ${day.is_today ? "today" : "upcoming"} ${selectedDate === day.date ? "active" : ""}`}
                onClick={() => setSelectedDate(day.date)}
              >
                {calendarDayLabel(day)}
                <span className="slip-day-meta">{day.fixture_count} match</span>
                {day.has_slips ? <span className="slip-day-badge">{day.slip_count}</span> : null}
              </button>
            ))}
          </div>
        </article>
      ) : null}

      {loadingDay ? <LoadingState title="Caricamento giorno selezionato..." /> : null}

      {actionMessage ? <p className="action-success">{actionMessage}</p> : null}
      {error ? <p className="action-error">{error}</p> : null}
      {selectedDaily && selectedDaily.candidate_pool_size >= 0 ? (
        <p className="note">Pool PLAY disponibile: {selectedDaily.candidate_pool_size}</p>
      ) : null}

      {selectedDaily?.market_models.length ? (
        <p className="note" data-testid="slip-market-models">
          Modelli del pool: {selectedDaily.market_models.map((model) => (
            `${model.label} ${model.model_version} / ${model.model_name}`
          )).join(" · ")}
        </p>
      ) : null}

      {selectedDaily?.warnings.map((warning) => (
        <p key={`${selectedDaily.model_name}-${warning}`} className="note">
          {warning}
        </p>
      ))}

      <div className="panel stake-panel">
        <label htmlFor="stake-input">
          {viewKind === "ladder" ? "Simula puntata iniziale scalata" : "Simula puntata"}
        </label>
        <div className="stake-controls">
          <input
            id="stake-input"
            type="number"
            min={0.01}
            step={0.5}
            value={stake}
            onChange={(event) => setStake(Number(event.target.value) || 1)}
          />
          {STAKE_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              className={stake === preset ? "pill active" : "pill"}
              onClick={() => setStake(preset)}
            >
              {preset} €
            </button>
          ))}
        </div>
      </div>

      <div className="tab-list" aria-label="Tipo consiglio">
        <button
          type="button"
          className={viewKind === "parlay" ? "active" : undefined}
          onClick={() => setViewKind("parlay")}
        >
          Schedine
        </button>
        <button
          type="button"
          className={viewKind === "ladder" ? "active" : undefined}
          onClick={() => setViewKind("ladder")}
        >
          Scalate
        </button>
      </div>
      <div className="tab-list strategy-tabs" aria-label="Strategia consiglio">
        {STRATEGY_TABS.map((strategy) => (
          <button
            key={strategy.key}
            type="button"
            className={strategyFamily === strategy.key ? "active" : undefined}
            onClick={() => setStrategyFamily(strategy.key)}
          >
            {strategy.label}
          </button>
        ))}
      </div>
      <p className="note strategy-note">
        <strong>{selectedStrategy.label}:</strong> {selectedStrategy.description}
        {strategyFamily !== "generic"
          ? " Risultati sperimentali: non pubblicati come consiglio ufficiale."
          : ""}
      </p>
      {viewKind === "ladder" ? (
        <p className="note">
          Ogni step è una singola: se vinci, il ritorno viene reinvestito nello step successivo
          (ordine di orario). Alla prima persa la catena si interrompe; gli step annullati
          trasmettono la puntata allo step seguente.
        </p>
      ) : null}

      <div className="result-legend">
        <span><span className="result-dot win" /> Presa</span>
        <span><span className="result-dot loss" /> Persa</span>
        <span><span className="result-dot pending" /> In corso</span>
        <span><span className="result-dot void" /> Annullata</span>
      </div>

      {!loadingDay && selectedModel && !visibleSlips.length ? (
        <EmptyState
          title={
            viewKind === "ladder"
              ? `Nessuna scalata disponibile · ${selectedStrategy.label}`
              : `Nessuna schedina disponibile · ${selectedStrategy.label}`
          }
          message={
            strategyFamily === "generic"
              ? 'Seleziona un altro giorno o usa "Aggiorna tutto" nella sidebar.'
              : "La strategia non ha trovato almeno due pick idonee oppure il giorno precede l'avvio dell'esperimento."
          }
        />
      ) : null}

      {!loadingDay && visibleSlips.length ? (
        <section className="slip-list">
          {visibleSlips.map((slip) => (
            <SlipCard
              key={`${selectedModel}-${slip.slip_key}`}
              slip={slip}
              stake={stake}
              historicalOutcomesMissing={historicalOutcomesMissing}
              globalMinEdge={minEdgePercent}
              downloadingImage={downloadingSlipKey === slip.slip_key}
              onDownloadImage={() => void handleDownloadSlipImage(slip.slip_key)}
            />
          ))}
        </section>
      ) : null}

      {!loadingDay ? (
        <SlipStatsPanel
          title={viewKind === "ladder" ? "Statistiche giorno (focus scalate)" : "Statistiche giorno"}
          subtitle={`Risultati per ${formatDate(selectedDate)}${selectedModel ? ` · Match Winner: ${selectedModel}` : ""}. Profili filtrati sul tab attivo.`}
          stats={selectedDayStats}
          focusKind={viewKind}
          focusStrategyFamily={strategyFamily}
        />
      ) : null}

      <SlipStatsPanel
        title={
          viewKind === "ladder" ? "Statistiche complessive (focus scalate)" : "Statistiche complessive"
        }
        subtitle={
          selectedOverallStats
            ? `Storico completo dal ${formatDate(selectedOverallStats.from_date)} al ${formatDate(selectedOverallStats.to_date)}${selectedModel ? ` · Match Winner: ${selectedModel}` : ""}.`
            : "Storico completo di tutte le schedine salvate."
        }
        stats={selectedOverallStats}
        focusKind={viewKind}
        focusStrategyFamily={strategyFamily}
      />

      <p className="disclaimer">
        Simulazione basata su previsioni ML. Nelle schedine multi-leg una pick persa invalida
        l&apos;intera schedina; nelle scalate la prima persa interrompe la catena. Non costituisce
        consiglio di scommessa reale.
      </p>
    </section>
  );
}
