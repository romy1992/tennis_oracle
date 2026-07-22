import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type {
  LiveBetaDashboardResponse,
  OddsBand,
  PublishedSettledTip
} from "../types/api";
import { MODEL_NAMES, MODEL_VERSIONS } from "../utils/modelVersion";
import { todayLocalISODate } from "../utils/tennis";

const ODDS_BAND_OPTIONS: Array<{ value: "" | OddsBand; label: string }> = [
  { value: "", label: "Tutte" },
  { value: "lt_1_50", label: "< 1.50" },
  { value: "1_50_2_00", label: "1.50 – 2.00" },
  { value: "2_00_3_00", label: "2.00 – 3.00" },
  { value: "gte_3_00", label: "≥ 3.00" },
  { value: "missing", label: "Senza quota" }
];

const SURFACE_OPTIONS = ["", "Hard", "Clay", "Grass", "Carpet"];

function daysAgoIso(days: number) {
  const value = new Date();
  value.setDate(value.getDate() - days);
  return todayLocalISODate(value);
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 2 })}%`;
}

function formatNum(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return "-";
  return value.toLocaleString("it-IT", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("it-IT");
}

function outcomeLabel(outcome: PublishedSettledTip["outcome"]) {
  switch (outcome) {
    case "won":
      return "Vinta";
    case "lost":
      return "Persa";
    case "void":
      return "Void";
    default:
      return "Aperta";
  }
}

function TipsTable({
  title,
  tips,
  emptyMessage
}: {
  title: string;
  tips: PublishedSettledTip[];
  emptyMessage: string;
}) {
  return (
    <article className="panel">
      <div className="panel-header">
        <h3>{title}</h3>
        <span className="pill">{tips.length}</span>
      </div>
      {tips.length === 0 ? (
        <EmptyState title="Nessun tip" message={emptyMessage} />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Evento</th>
                <th>Selezione</th>
                <th>Modello</th>
                <th>Quota</th>
                <th>Esito</th>
                <th>Profitto</th>
                <th>Superficie</th>
              </tr>
            </thead>
            <tbody>
              {tips.map((tip) => (
                <tr key={tip.id}>
                  <td>
                    {tip.player_1_name && tip.player_2_name
                      ? `${tip.player_1_name} vs ${tip.player_2_name}`
                      : tip.event_key}
                    {tip.tournament_name ? (
                      <div className="note">{tip.tournament_name}</div>
                    ) : null}
                  </td>
                  <td>{tip.selection}</td>
                  <td>
                    {tip.model_version} / {tip.model_name}
                  </td>
                  <td>{formatNum(tip.odds)}</td>
                  <td>{outcomeLabel(tip.outcome)}</td>
                  <td>{formatNum(tip.profit)}</td>
                  <td>{tip.surface || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}

export function LiveBetaDashboardPage() {
  const [data, setData] = useState<LiveBetaDashboardResponse | null>(null);
  const [fromDate, setFromDate] = useState(() => daysAgoIso(89));
  const [toDate, setToDate] = useState(() => todayLocalISODate());
  const [modelVersion, setModelVersion] = useState("");
  const [modelName, setModelName] = useState("");
  const [tournamentDraft, setTournamentDraft] = useState("");
  const [tournamentName, setTournamentName] = useState("");
  const [surface, setSurface] = useState("");
  const [oddsBand, setOddsBand] = useState<"" | OddsBand>("");
  const [latestOnly, setLatestOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const response = await apiClient.getLiveBetaDashboard({
          from: fromDate,
          to: toDate,
          model_version: modelVersion || undefined,
          model_name: modelName || undefined,
          tournament_name: tournamentName.trim() || undefined,
          surface: surface || undefined,
          odds_band: oddsBand || undefined,
          latest_only: latestOnly
        });
        setData(response);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [fromDate, toDate, modelVersion, modelName, tournamentName, surface, oddsBand, latestOnly]);

  function applyTournamentFilter() {
    setTournamentName(tournamentDraft.trim());
  }

  if (loading && !data) {
    return <LoadingState title="Caricamento dashboard beta live..." />;
  }

  if (error && !data) {
    return <ErrorState title="Dashboard beta live non disponibile" message={error} />;
  }

  if (!data) {
    return (
      <EmptyState
        title="Nessun dato"
        message="La dashboard beta live non ha restituito contenuti."
      />
    );
  }

  const stats = data.live_stats;
  const pipelineRun = data.pipeline.active_run || data.pipeline.latest_run;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <div className="mode-badge-row">
            <span className="mode-badge mode-badge-live">LIVE</span>
            <span className="mode-badge mode-badge-muted">Beta tipbook</span>
          </div>
          <h2>Dashboard beta live</h2>
          <p>
            Vista operativa sul registro immutabile delle pubblicazioni: pipeline, KPI live,
            bot e completezza dati. Non include metriche di training o backtest.
          </p>
        </div>
      </header>

      <div className="filters-grid">
        <label>
          Da
          <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
        </label>
        <label>
          A
          <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
        </label>
        <label>
          Versione modello
          <select value={modelVersion} onChange={(e) => setModelVersion(e.target.value)}>
            <option value="">Tutte</option>
            {MODEL_VERSIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Modello
          <select value={modelName} onChange={(e) => setModelName(e.target.value)}>
            <option value="">Tutti</option>
            {MODEL_NAMES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Torneo
          <input
            type="text"
            value={tournamentDraft}
            placeholder="es. Roland Garros"
            onChange={(e) => setTournamentDraft(e.target.value)}
            onBlur={applyTournamentFilter}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                applyTournamentFilter();
              }
            }}
          />
        </label>
        <label>
          Superficie
          <select value={surface} onChange={(e) => setSurface(e.target.value)}>
            {SURFACE_OPTIONS.map((item) => (
              <option key={item || "all"} value={item}>
                {item || "Tutte"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Fascia quota
          <select
            value={oddsBand}
            onChange={(e) => setOddsBand(e.target.value as "" | OddsBand)}
          >
            {ODDS_BAND_OPTIONS.map((item) => (
              <option key={item.value || "all"} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={latestOnly}
            onChange={(e) => setLatestOnly(e.target.checked)}
          />{" "}
          Solo versione più recente
        </label>
      </div>

      {error ? <p className="note">Aggiornamento filtri non riuscito: {error}</p> : null}

      <article className="panel mode-panel mode-panel-live">
        <div className="panel-header">
          <h3>Pipeline LIVE</h3>
          <span className={`pill ${pipelineRun?.status === "completed" ? "pill-ok" : ""}`}>
            {pipelineRun?.status || "nessun run"}
          </span>
        </div>
        <div className="metrics-grid">
          <MetricCard
            label="Ultimo aggiornamento"
            value={formatDateTime(data.pipeline.last_updated_at)}
          />
          <MetricCard label="Fase corrente" value={pipelineRun?.current_phase || "-"} />
          <MetricCard
            label="Import next fixtures oggi"
            value={data.pipeline.import_status.next_fixtures_imported_today ? "Sì" : "No"}
          />
          <MetricCard
            label="Ultimo import fixtures"
            value={formatDateTime(data.pipeline.import_status.fixtures_last_imported_at)}
          />
        </div>
        {pipelineRun ? (
          <p className="note">
            Run #{pipelineRun.id} · origine {pipelineRun.origin} ·{" "}
            <Link to="/global-update-report">Apri report aggiornamento</Link>
          </p>
        ) : null}
      </article>

      <div className="metrics-grid">
        <MetricCard label="Pronostici totali" value={String(stats.predictions_total)} />
        <MetricCard label="Aperti" value={String(stats.open)} />
        <MetricCard label="Chiusi" value={String(stats.closed)} />
        <MetricCard label="Void" value={String(stats.void)} />
        <MetricCard label="Hit rate" value={formatPct(stats.hit_rate_pct)} />
        <MetricCard label="Profitto" value={formatNum(stats.profit)} />
        <MetricCard label="ROI" value={formatPct(stats.roi_pct)} />
        <MetricCard label="Yield" value={formatPct(stats.yield_pct)} />
        <MetricCard label="Max drawdown" value={formatNum(stats.max_drawdown)} />
        <MetricCard
          label="Serie +/-"
          value={`${stats.max_winning_streak} / ${stats.max_losing_streak}`}
        />
        <MetricCard label="Eventi bot oggi" value={String(data.bot_usage.events_today)} />
        <MetricCard label="Utenti bot unici" value={String(data.bot_usage.unique_users)} />
      </div>

      <TipsTable
        title="Pronostici pubblicati oggi"
        tips={data.published_today}
        emptyMessage="Nessuna pubblicazione con data odierna."
      />
      <TipsTable
        title="Pronostici aperti"
        tips={data.open_predictions}
        emptyMessage="Nessun tip ancora da liquidare nel periodo filtrato."
      />
      <TipsTable
        title="Pronostici chiusi"
        tips={data.closed_predictions}
        emptyMessage="Nessun tip chiuso (won/lost/void) nel periodo filtrato."
      />

      <article className="panel">
        <div className="panel-header">
          <h3>Completezza dati</h3>
        </div>
        <div className="metrics-grid">
          <MetricCard
            label="Tip con quota"
            value={formatPct(data.data_completeness.tips_with_odds_pct)}
          />
          <MetricCard
            label="Tip con data evento"
            value={formatPct(data.data_completeness.tips_with_event_date_pct)}
          />
          <MetricCard
            label="Tip con match collegato"
            value={formatPct(data.data_completeness.tips_with_match_context_pct)}
          />
          <MetricCard
            label="Coverage snapshot quote"
            value={formatPct(data.data_completeness.odds_snapshot_coverage_pct)}
          />
        </div>
        <p className="note">
          Snapshot: opening {data.data_completeness.snapshots_opening}, observed{" "}
          {data.data_completeness.snapshots_observed}, publication{" "}
          {data.data_completeness.snapshots_publication}, closing{" "}
          {data.data_completeness.snapshots_closing}.
        </p>
      </article>

      <article className="panel">
        <div className="panel-header">
          <h3>Utilizzo bot</h3>
          <Link to="/telegram-bot">Dettaglio bot</Link>
        </div>
        <div className="metrics-grid">
          <MetricCard label="Eventi totali" value={String(data.bot_usage.total_events)} />
          <MetricCard label="Eventi oggi" value={String(data.bot_usage.events_today)} />
          <MetricCard label="Utenti unici" value={String(data.bot_usage.unique_users)} />
          <MetricCard label="Azione top" value={data.bot_usage.top_action || "-"} />
        </div>
      </article>

      <article className="panel">
        <div className="panel-header">
          <h3>Errori recenti</h3>
        </div>
        {data.recent_errors.length === 0 ? (
          <EmptyState
            title="Nessun errore recente"
            message="Pipeline e bot senza errori segnalati."
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Quando</th>
                  <th>Fonte</th>
                  <th>Messaggio</th>
                  <th>Dettaglio</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_errors.map((item, index) => (
                  <tr key={`${item.source}-${item.created_at}-${index}`}>
                    <td>{formatDateTime(item.created_at)}</td>
                    <td>{item.source}</td>
                    <td>{item.message}</td>
                    <td>{item.detail || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>

      <article className="panel mode-panel mode-panel-backtest">
        <div className="panel-header">
          <h3>
            <span className="mode-badge mode-badge-backtest">BACKTEST</span> Area separata
          </h3>
        </div>
        <p>{data.backtest.message}</p>
        <p className="note">
          Pagine correlate:{" "}
          {data.backtest.related_paths.map((path, index) => (
            <span key={path}>
              {index > 0 ? " · " : null}
              <Link to={path}>{path}</Link>
            </span>
          ))}
        </p>
      </article>
    </section>
  );
}
