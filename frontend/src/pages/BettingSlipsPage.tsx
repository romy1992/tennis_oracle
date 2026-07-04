import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type {
  BettingSlip,
  BettingSlipCalendarDay,
  BettingSlipCalendarResponse,
  BettingSlipPick,
  BettingSlipStatsResponse,
  BettingSlipsDailyResponse
} from "../types/api";
import { formatDate } from "../utils/tennis";

const STAKE_PRESETS = [1, 5, 10, 25, 50];

function formatProb(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${(value * 100).toLocaleString("it-IT", { maximumFractionDigits: 1 })}%`;
}

function formatTime(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(0, 5);
}

function formatOdds(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return value.toLocaleString("it-IT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${value.toLocaleString("it-IT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })} €`;
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 1 })}%`;
}

function pickDotClass(status: BettingSlipPick["pick_status"]) {
  if (status === "won") return "win";
  if (status === "lost") return "loss";
  return "pending";
}

function slipStatusLabel(status: BettingSlip["slip_status"]) {
  if (status === "won") return "Presa";
  if (status === "lost") return "Persa";
  return "In corso";
}

function computeStakeValues(slip: BettingSlip, stake: number) {
  const potentialReturn = stake * slip.combined_odds;
  const potentialProfit = potentialReturn - stake;
  let actualOutcome: number | null = null;
  if (slip.slip_status === "won") {
    actualOutcome = potentialReturn;
  } else if (slip.slip_status === "lost") {
    actualOutcome = -stake;
  }
  return { potentialReturn, potentialProfit, actualOutcome };
}

function buildSlipClipboard(slip: BettingSlip, stake: number) {
  const lines = slip.picks.map(
    (pick) =>
      `${formatTime(pick.event_time)} ${pick.tournament_name ?? "-"} | ${pick.player_1 ?? "?"} vs ${pick.player_2 ?? "?"} -> ${pick.predicted_winner_label ?? "-"} @ ${formatOdds(pick.odds)}`
  );
  const { potentialReturn } = computeStakeValues(slip, stake);
  return [
    `${slip.label} (${slip.slip_status})`,
    ...lines,
    `Quota combinata: ${formatOdds(slip.combined_odds)} | Puntata: ${formatMoney(stake)} | Vincita potenziale: ${formatMoney(potentialReturn)}`
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
  stats
}: {
  title: string;
  subtitle: string;
  stats: BettingSlipStatsResponse | null;
}) {
  const daysWithSlips = [...(stats?.days ?? [])]
    .filter((day) => day.slips_total > 0)
    .sort((left, right) => right.date.localeCompare(left.date));

  if (!stats || stats.summary.slips_total === 0) {
    return (
      <section className="panel slip-stats-panel">
        <header className="section-header">
          <div>
            <h3>{title}</h3>
            <p>{subtitle}</p>
          </div>
        </header>
        <EmptyState title="Nessun dato" message="Non ci sono schedine salvate per questo periodo." />
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
          <strong>{stats.summary.slips_total}</strong>
        </div>
        <div className="metric-card">
          <span>Win rate schedine</span>
          <strong>{formatPct(stats.summary.slip_win_rate_pct)}</strong>
        </div>
        <div className="metric-card">
          <span>Hit rate pick</span>
          <strong>{formatPct(stats.summary.pick_hit_rate_pct)}</strong>
        </div>
        <div className="metric-card">
          <span>Profitto teorico</span>
          <strong>{formatMoney(stats.summary.theoretical_profit_units)}</strong>
        </div>
      </div>

      {daysWithSlips.length > 1 ? (
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

      {stats.summary.by_profile.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Profilo</th>
                <th>Schedine</th>
                <th>Prese</th>
                <th>Perse</th>
                <th>Win rate</th>
              </tr>
            </thead>
            <tbody>
              {stats.summary.by_profile.map((profile) => (
                <tr key={profile.slip_key}>
                  <td>{profile.label}</td>
                  <td>{profile.slips_total}</td>
                  <td>{profile.slips_won}</td>
                  <td>{profile.slips_lost}</td>
                  <td>{formatPct(profile.slip_win_rate_pct)}</td>
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

function SlipCard({ slip, stake }: { slip: BettingSlip; stake: number }) {
  const { potentialReturn, potentialProfit, actualOutcome } = computeStakeValues(slip, stake);

  async function copySlip() {
    await navigator.clipboard.writeText(buildSlipClipboard(slip, stake));
  }

  return (
    <article className={`panel slip-card ${slip.slip_status}`}>
      <header className="slip-card-header">
        <div className="slip-card-title">
          <span className="pill">{slip.label}</span>
          <p className="slip-description">{slip.description}</p>
        </div>
        <div className="slip-card-meta">
          <span className={`slip-status-badge ${slip.slip_status}`}>{slipStatusLabel(slip.slip_status)}</span>
          <span className="slip-pick-counter">
            {slip.picks_won}/{slip.picks_total} pick corrette
          </span>
        </div>
      </header>

      <div className="table-wrap slip-table-wrap">
        <table className="slip-picks-table">
          <thead>
            <tr>
              <th className="slip-col-status" aria-label="Esito" />
              <th>Ora</th>
              <th>Torneo</th>
              <th>Match</th>
              <th>Pick</th>
              <th>Quota</th>
              <th>Conf.</th>
            </tr>
          </thead>
          <tbody>
            {slip.picks.map((pick) => (
              <tr key={pick.event_key}>
                <td className="slip-col-status">
                  <span
                    className={`result-dot ${pickDotClass(pick.pick_status)}`}
                    title={
                      pick.pick_status === "won"
                        ? "Presa"
                        : pick.pick_status === "lost"
                          ? "Persa"
                          : "In corso"
                    }
                  />
                </td>
                <td className="slip-col-time">{formatTime(pick.event_time)}</td>
                <td className="slip-col-tournament" title={pick.tournament_name ?? undefined}>
                  {truncateText(pick.tournament_name, 32)}
                </td>
                <td className="slip-col-match">
                  {pick.player_1 ?? "?"} vs {pick.player_2 ?? "?"}
                </td>
                <td className="slip-col-pick">
                  <strong>{pick.predicted_winner_label ?? "-"}</strong>
                </td>
                <td className="slip-col-odds">{formatOdds(pick.odds)}</td>
                <td className="slip-col-confidence">{formatProb(pick.confidence)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <footer className="slip-card-footer">
        <div className="slip-metrics-grid">
          <div>
            <span>Quota combinata</span>
            <strong>{formatOdds(slip.combined_odds)}</strong>
          </div>
          <div>
            <span>Puntata</span>
            <strong>{formatMoney(stake)}</strong>
          </div>
          <div>
            <span>Vincita potenziale</span>
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
        <button type="button" className="action-button" onClick={() => void copySlip()}>
          Copia schedina
        </button>
      </footer>
    </article>
  );
}

export function BettingSlipsPage() {
  const [calendar, setCalendar] = useState<BettingSlipCalendarResponse | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const [daily, setDaily] = useState<BettingSlipsDailyResponse | null>(null);
  const [dayStats, setDayStats] = useState<BettingSlipStatsResponse | null>(null);
  const [overallStats, setOverallStats] = useState<BettingSlipStatsResponse | null>(null);
  const [stake, setStake] = useState(10);
  const [loading, setLoading] = useState(true);
  const [loadingDay, setLoadingDay] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedCalendarDay = useMemo(
    () => calendar?.days.find((day) => day.date === selectedDate) ?? null,
    [calendar, selectedDate]
  );

  const loadDayData = useCallback(async (date: string) => {
    const [dailyData, dayStatsData, overallStatsData] = await Promise.all([
      apiClient.getDailyBettingSlips({ model_version: "v2", stake, date }),
      apiClient.getBettingSlipStats({
        model_version: "v2",
        from: date,
        to: date,
        stake
      }),
      apiClient.getBettingSlipStats({
        model_version: "v2",
        all_time: true,
        stake
      })
    ]);
    setDaily(dailyData);
    setDayStats(dayStatsData);
    setOverallStats(overallStatsData);
  }, [stake]);

  useEffect(() => {
    async function loadCalendar() {
      try {
        setLoading(true);
        const calendarData = await apiClient.getBettingSlipCalendar({ model_version: "v2" });
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
    void loadCalendar();
  }, []);

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

  async function handleRefresh() {
    try {
      setRefreshing(true);
      setActionMessage(null);
      const [result, calendarData] = await Promise.all([
        apiClient.refreshBettingSlips({ model_version: "v2", stake, date: selectedDate }),
        apiClient.getBettingSlipCalendar({ model_version: "v2" })
      ]);
      setCalendar(calendarData);
      setDaily(result);
      const [dayStatsData, overallStatsData] = await Promise.all([
        apiClient.getBettingSlipStats({
          model_version: "v2",
          from: selectedDate,
          to: selectedDate,
          stake
        }),
        apiClient.getBettingSlipStats({
          model_version: "v2",
          all_time: true,
          stake
        })
      ]);
      setDayStats(dayStatsData);
      setOverallStats(overallStatsData);
      const resolvedPicks = result.slips.reduce(
        (total, slip) => total + slip.picks_won + slip.picks_lost,
        0
      );
      const wonSlips = result.slips.filter((slip) => slip.slip_status === "won").length;
      setActionMessage(
        `${resolvedPicks} pick aggiornate, ${wonSlips} schedina${wonSlips === 1 ? "" : "e"} vinta${wonSlips === 1 ? "" : "e"}.`
      );
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante l'aggiornamento.");
    } finally {
      setRefreshing(false);
    }
  }

  if (loading) {
    return <LoadingState title="Caricamento schedine..." />;
  }

  if (error && !daily) {
    return <ErrorState title="Schedine non disponibili" message={error} />;
  }

  const pastDays = calendar?.days.filter((day) => day.is_past) ?? [];
  const upcomingDays = calendar?.days.filter((day) => !day.is_past) ?? [];

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Consiglio schedina</h2>
          <p>
            {daily ? formatDate(daily.date) : "-"} · modello {daily?.model_name ?? "v2"} · pool{" "}
            {daily?.candidate_pool_size ?? 0} partite
            {selectedCalendarDay
              ? ` · ${selectedCalendarDay.fixture_count} match in calendario`
              : ""}
          </p>
        </div>
        <div className="header-actions">
          <button
            type="button"
            className="action-button"
            disabled={refreshing || loadingDay}
            onClick={() => void handleRefresh()}
          >
            {refreshing ? "Aggiornamento esiti..." : "Aggiorna"}
          </button>
        </div>
      </header>

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
      {daily?.warnings.length ? (
        <div className="panel">
          {daily.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      ) : null}

      <div className="panel stake-panel">
        <label htmlFor="stake-input">Simula puntata</label>
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

      <div className="result-legend">
        <span><span className="result-dot win" /> Presa</span>
        <span><span className="result-dot loss" /> Persa</span>
        <span><span className="result-dot pending" /> In corso</span>
      </div>

      {!loadingDay && !daily?.slips.length ? (
        <EmptyState
          title="Nessuna schedina disponibile per questo giorno"
          message='Seleziona un altro giorno o usa "Aggiorna" per importare partite e previsioni.'
        />
      ) : null}

      {!loadingDay && daily?.slips.length ? (
        <div className="slip-list">
          {daily.slips.map((slip) => (
            <SlipCard key={slip.slip_key} slip={slip} stake={stake} />
          ))}
        </div>
      ) : null}

      <SlipStatsPanel
        title="Statistiche del giorno selezionato"
        subtitle={`Risultati per ${formatDate(selectedDate)}.`}
        stats={dayStats}
      />

      <SlipStatsPanel
        title="Statistiche complessive"
        subtitle={
          overallStats
            ? `Storico completo dal ${formatDate(overallStats.from_date)} al ${formatDate(overallStats.to_date)}.`
            : "Storico completo di tutte le schedine salvate."
        }
        stats={overallStats}
      />

      <p className="disclaimer">
        Simulazione basata su previsioni ML. Una pick persa invalida l&apos;intera schedina. Non
        costituisce consiglio di scommessa reale.
      </p>
    </section>
  );
}
