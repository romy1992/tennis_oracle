import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { MetricCard } from "../components/MetricCard";
import { MarketTabs } from "../components/MarketTabs";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type {
  LiveBetaDashboardResponse,
  LiveDashboardMarket,
  LivePublicationEmptyReason,
  OddsBand,
  PublishedSettledTip,
  SingleMatchValueDecision
} from "../types/api";
import { DEFAULT_LIVE_MARKET, marketLabel } from "../utils/markets";
import { todayLocalISODate } from "../utils/tennis";

const EM_DASH = "—";
const TIP_LIMIT = 25;

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
  if (value === null || value === undefined) return EM_DASH;
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 2 })}%`;
}

function formatNum(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return EM_DASH;
  return value.toLocaleString("it-IT", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return EM_DASH;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("it-IT");
}

function formatEventDate(tip: PublishedSettledTip) {
  if (!tip.event_date) return EM_DASH;
  const parsed = new Date(`${tip.event_date}T00:00:00`);
  const dateLabel = Number.isNaN(parsed.getTime())
    ? tip.event_date
    : parsed.toLocaleDateString("it-IT");
  return tip.event_time ? `${dateLabel} ${tip.event_time.slice(0, 5)}` : dateLabel;
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

function decisionClass(decision: SingleMatchValueDecision | "NON_PLAY") {
  if (decision === "PLAY") return "play";
  if (decision === "BORDERLINE") return "borderline";
  if (decision === "NO BET") return "no-bet";
  return "unavailable";
}

function playIndicator(tip: PublishedSettledTip) {
  if (tip.official_play === true) {
    return { label: "PLAY", className: decisionClass("PLAY") };
  }
  if (tip.value_decision) {
    return { label: tip.value_decision, className: decisionClass(tip.value_decision) };
  }
  if (tip.official_play === false) {
    return { label: "Non PLAY", className: decisionClass("NON_PLAY") };
  }
  return null;
}

function pipelineStatusLabel(status: string | null | undefined) {
  switch (status) {
    case "completed":
      return "Completato";
    case "running":
      return "In esecuzione";
    case "pending":
      return "In attesa";
    case "failed":
      return "Fallito";
    case "completed_with_errors":
      return "Completato con errori";
    case "cancelled":
      return "Annullato";
    default:
      return status || "Nessun aggiornamento";
  }
}

function healthStatusLabel(reason: LivePublicationEmptyReason) {
  switch (reason) {
    case "ok":
      return "Operativa";
    case "publication_disabled":
      return "Pubblicazione disabilitata";
    case "public_model_unconfigured":
      return "Configurazione mancante";
    case "public_model_invalid":
      return "Configurazione non valida";
    case "pipeline_never_run":
      return "Pipeline mai eseguita";
    case "pipeline_run_no_qualified_plays":
      return "Nessun PLAY qualificato";
    case "publication_errors":
      return "Errori di pubblicazione";
    case "table_unavailable":
      return "Registro non disponibile";
  }
}

function closingStatusLabel(status: string) {
  switch (status) {
    case "available":
      return "disponibile";
    case "partial":
      return "parziale";
    case "missing":
      return "mancante";
    default:
      return "non determinato";
  }
}

function errorSourceLabel(source: string) {
  return source === "global_update" ? "Aggiornamento" : "Telegram";
}

function TipsTable({
  title,
  tips,
  emptyMessage,
  market
}: {
  title: string;
  tips: PublishedSettledTip[];
  emptyMessage: string;
  market: LiveDashboardMarket;
}) {
  const orderedTips = [...tips].sort((left, right) => {
    const leftTime = Date.parse(left.published_at);
    const rightTime = Date.parse(right.published_at);
    if (Number.isNaN(leftTime) || Number.isNaN(rightTime)) return right.id - left.id;
    return rightTime - leftTime || right.id - left.id;
  });

  return (
    <article className="panel live-tips-panel">
      <div className="panel-header live-tips-header">
        <div>
          <h3>{title}</h3>
          <p className="note">Ordine: pubblicazione più recente.</p>
        </div>
        <span className="pill" aria-label={`${orderedTips.length} righe mostrate, limite ${TIP_LIMIT}`}>
          {orderedTips.length} mostrati · limite {TIP_LIMIT}
        </span>
      </div>
      {orderedTips.length === 0 ? (
        <EmptyState title="Nessun pronostico" message={emptyMessage} />
      ) : (
        <div className="table-wrap">
          <table className="live-tips-table">
            <thead>
              <tr>
                <th>Pubblicato</th>
                <th>Evento</th>
                <th>Mercato</th>
                <th>Selezione</th>
                <th>Valore</th>
                <th>Quota tip</th>
                <th>Snapshot pubblicazione</th>
                <th>Closing</th>
                <th>CLV</th>
                <th>Esito</th>
                <th>Profitto (unità)</th>
                <th>Superficie</th>
              </tr>
            </thead>
            <tbody>
              {orderedTips.map((tip) => {
                const indicator = playIndicator(tip);
                const tipMarket = tip.market || market;
                return (
                  <tr key={tip.id}>
                    <td>{formatDateTime(tip.published_at)}</td>
                    <td>
                      {tip.player_1_name && tip.player_2_name
                        ? `${tip.player_1_name} vs ${tip.player_2_name}`
                        : tip.event_key}
                      <div className="note">{formatEventDate(tip)}</div>
                      {tip.tournament_name ? (
                        <div className="note">{tip.tournament_name}</div>
                      ) : null}
                    </td>
                    <td>
                      <span className={`market-badge market-${tipMarket}`}>
                        {marketLabel(tipMarket)}
                      </span>
                    </td>
                    <td>{tip.selection}</td>
                    <td>
                      {indicator ? (
                        <span className={`value-decision-badge ${indicator.className}`}>
                          {indicator.label}
                        </span>
                      ) : (
                        EM_DASH
                      )}
                    </td>
                    <td>{formatNum(tip.odds)}</td>
                    <td>{formatNum(tip.publication_odds)}</td>
                    <td>{formatNum(tip.closing_odds)}</td>
                    <td>{formatPct(tip.clv_pct)}</td>
                    <td>{outcomeLabel(tip.outcome)}</td>
                    <td>
                      {tip.outcome !== "pending" ? formatNum(tip.profit) : EM_DASH}
                    </td>
                    <td>{tip.surface || EM_DASH}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}

export function LiveBetaDashboardPage() {
  const [data, setData] = useState<LiveBetaDashboardResponse | null>(null);
  const [market, setMarket] = useState<LiveDashboardMarket>(DEFAULT_LIVE_MARKET);
  const [fromDate, setFromDate] = useState(() => daysAgoIso(89));
  const [toDate, setToDate] = useState(() => todayLocalISODate());
  const [tournamentDraft, setTournamentDraft] = useState("");
  const [tournamentName, setTournamentName] = useState("");
  const [surface, setSurface] = useState("");
  const [oddsBand, setOddsBand] = useState<"" | OddsBand>("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        const response = await apiClient.getLiveBetaDashboard({
          from: fromDate,
          to: toDate,
          market,
          include_archived: market === "match_winner" ? includeArchived : false,
          official_only: false,
          tournament_name: tournamentName.trim() || undefined,
          surface: surface || undefined,
          odds_band: oddsBand || undefined,
          latest_only: true,
          tip_limit: TIP_LIMIT
        });
        if (!cancelled) {
          setData(response);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Errore inatteso.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [fromDate, toDate, market, tournamentName, surface, oddsBand, includeArchived]);

  function applyTournamentFilter() {
    setTournamentName(tournamentDraft.trim());
  }

  function selectMarket(nextMarket: LiveDashboardMarket) {
    if (nextMarket === market) return;
    setData(null);
    setError(null);
    setMarket(nextMarket);
    setIncludeArchived(false);
  }

  if (loading && !data) {
    return <LoadingState title="Caricamento dashboard live..." />;
  }

  if (error && !data) {
    return <ErrorState title="Dashboard live non disponibile" message={error} />;
  }

  if (!data) {
    return <EmptyState title="Nessun dato" message="La dashboard live non ha restituito contenuti." />;
  }

  const stats = data.live_stats;
  const officialStats = data.official_live_stats ?? null;
  const pipelineRun = data.pipeline.active_run || data.pipeline.latest_run;
  const health = data.publication_health;
  const legacyContract = data.market === undefined || data.official_live_stats === undefined;
  const publicModelConfigured = Boolean(health.public_model_version && health.public_model_name);

  return (
    <section className="page" aria-busy={loading}>
      <header className="page-header">
        <div>
          <div className="mode-badge-row">
            <span className="mode-badge mode-badge-live">LIVE</span>
            <span className="mode-badge mode-badge-muted">Registro pubblicazioni</span>
          </div>
          <h2>Dashboard live</h2>
          <p>
            Risultati realmente pubblicati, separando l'accuratezza di tutti i pronostici dalla
            performance finanziaria dei soli PLAY ufficiali.
          </p>
        </div>
      </header>

      <MarketTabs
        value={market}
        onChange={selectMarket}
        ariaLabel="Mercato live"
        disabled={loading}
      />

      {legacyContract ? (
        <p className="live-contract-warning" role="status">
          Il server ha restituito il formato precedente: i dati restano consultabili, ma le
          metriche dei PLAY ufficiali non sono disponibili finché il backend non viene aggiornato.
        </p>
      ) : null}

      <div className="filters-grid live-dashboard-filters">
        <label>
          Data pubblicazione da
          <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
        </label>
        <label>
          Data pubblicazione a
          <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
        </label>
        <label>
          Torneo
          <input
            type="text"
            value={tournamentDraft}
            placeholder="es. Roland Garros"
            onChange={(event) => setTournamentDraft(event.target.value)}
            onBlur={applyTournamentFilter}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                applyTournamentFilter();
              }
            }}
          />
        </label>
        <label>
          Superficie
          <select value={surface} onChange={(event) => setSurface(event.target.value)}>
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
            onChange={(event) => setOddsBand(event.target.value as "" | OddsBand)}
          >
            {ODDS_BAND_OPTIONS.map((item) => (
              <option key={item.value || "all"} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        {market === "match_winner" ? (
          <label className="checkbox-field live-history-filter">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(event) => setIncludeArchived(event.target.checked)}
            />
            <span>
              Includi storico
              <small>Aggiunge le pubblicazioni dei modelli non più attivi.</small>
            </span>
          </label>
        ) : null}
      </div>

      {error ? (
        <p className="live-contract-warning" role="alert">
          Aggiornamento filtri non riuscito. I dati mostrati sono quelli caricati in precedenza:
          {" "}
          {error}
        </p>
      ) : null}

      <article className="panel live-metric-section">
        <div className="panel-header">
          <div>
            <h3>Tutti i pronostici</h3>
            <p className="note">
              Conteggi e accuratezza di tutte le pubblicazioni del mercato, indipendentemente
              dall'indicazione PLAY.
            </p>
          </div>
          <span className={`market-badge market-${market}`}>{marketLabel(market)}</span>
        </div>
        <div className="metrics-grid">
          <MetricCard label="Pronostici pubblicati" value={String(stats.predictions_total)} />
          <MetricCard label="Aperti" value={String(stats.open)} />
          <MetricCard
            label="Chiusi (vinti o persi)"
            value={String(stats.closed)}
            hint="I void sono conteggiati a parte."
          />
          <MetricCard label="Void" value={String(stats.void)} />
          <MetricCard label="Vinti / persi" value={`${stats.won} / ${stats.lost}`} />
          <MetricCard label="Hit rate (%)" value={formatPct(stats.hit_rate_pct)} />
        </div>
      </article>

      <article className="panel live-metric-section live-official-section">
        <div className="panel-header">
          <div>
            <h3>PLAY ufficiali</h3>
            <p className="note">
              Solo pronostici pubblicati come PLAY ufficiali; le metriche finanziarie usano quote
              reali e stake liquidato.
            </p>
          </div>
          <span className="value-decision-badge play">PLAY</span>
        </div>
        {!officialStats ? (
          <p className="live-finance-note">
            Il riepilogo PLAY ufficiale non è presente nella risposta del server.
          </p>
        ) : null}
        <div className="metrics-grid">
          <MetricCard
            label="PLAY pubblicati"
            value={officialStats ? String(officialStats.predictions_total) : EM_DASH}
          />
          <MetricCard
            label="Stake liquidato (unità)"
            value={officialStats ? formatNum(officialStats.stake_settled) : EM_DASH}
          />
          <MetricCard
            label="Profitto (unità)"
            value={officialStats ? formatNum(officialStats.profit) : EM_DASH}
          />
          <MetricCard
            label="ROI (%)"
            value={officialStats ? formatPct(officialStats.roi_pct) : EM_DASH}
          />
          <MetricCard
            label="Max drawdown (unità)"
            value={officialStats ? formatNum(officialStats.max_drawdown) : EM_DASH}
          />
          <MetricCard
            label="CLV medio (%)"
            value={officialStats ? formatPct(officialStats.clv_avg_pct) : EM_DASH}
          />
        </div>
      </article>

      <TipsTable
        title="Pubblicazioni di oggi"
        tips={data.published_today}
        emptyMessage="Nessun pronostico pubblicato oggi per questo mercato e questi filtri."
        market={market}
      />
      <TipsTable
        title="Pronostici aperti più recenti"
        tips={data.open_predictions}
        emptyMessage="Nessun pronostico ancora da liquidare nel periodo filtrato."
        market={market}
      />
      <TipsTable
        title="Pronostici chiusi più recenti"
        tips={data.closed_predictions}
        emptyMessage="Nessun pronostico vinto, perso o void nel periodo filtrato."
        market={market}
      />

      <article className="panel">
        <div className="panel-header">
          <div>
            <h3>Completezza dati</h3>
            <p className="note">Calcolata sui pronostici del mercato e del periodo selezionati.</p>
          </div>
        </div>
        <div className="metrics-grid">
          <MetricCard
            label="Tip con quota dedicata"
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
            label="Eventi con snapshot quote"
            value={formatPct(data.data_completeness.odds_snapshot_coverage_pct)}
            hint="Percentuale di eventi distinti, non di tip."
          />
        </div>
        <p className="note">
          Snapshot quote: apertura {data.data_completeness.snapshots_opening}, osservati{" "}
          {data.data_completeness.snapshots_observed}, pubblicazione{" "}
          {data.data_completeness.snapshots_publication}, closing{" "}
          {data.data_completeness.snapshots_closing}. Copertura closing{" "}
          {closingStatusLabel(data.data_completeness.closing_odds_status)}
          {data.data_completeness.tips_with_closing_snapshot_pct != null
            ? ` (${formatPct(data.data_completeness.tips_with_closing_snapshot_pct)} dei tip)`
            : ""}
          .
        </p>
        {data.data_completeness.closing_odds_note ? (
          <p className="note">{data.data_completeness.closing_odds_note}</p>
        ) : null}
      </article>

      <article className="panel mode-panel mode-panel-live">
        <div className="panel-header">
          <div>
            <h3>Stato pubblicazione live</h3>
            <p className="note">Stato globale: non cambia con i filtri del mercato.</p>
          </div>
          <span className={`pill ${health.empty_reason === "ok" ? "pill-ok" : ""}`}>
            {healthStatusLabel(health.empty_reason)}
          </span>
        </div>
        <p>{health.message}</p>
        <div className="metrics-grid">
          <MetricCard
            label="Pubblicazione automatica"
            value={health.live_publication_enabled ? "Abilitata" : "Disabilitata"}
          />
          <MetricCard
            label="Modello pubblico"
            value={publicModelConfigured ? "Configurato" : "Non configurato"}
          />
          <MetricCard
            label="Inizio registro live"
            value={formatDateTime(health.validation_started_at)}
          />
          <MetricCard
            label="Pubblicazioni ultimo run"
            value={
              health.last_run_publications_created == null
                ? EM_DASH
                : String(health.last_run_publications_created)
            }
          />
          <MetricCard
            label="Duplicati ignorati (ultimo run)"
            value={
              health.last_run_duplicates_skipped == null
                ? EM_DASH
                : String(health.last_run_duplicates_skipped)
            }
          />
        </div>
      </article>

      <article className="panel mode-panel mode-panel-live">
        <div className="panel-header">
          <div>
            <h3>Pipeline LIVE</h3>
            <p className="note">Stato globale dell'aggiornamento dati.</p>
          </div>
          <span className={`pill ${pipelineRun?.status === "completed" ? "pill-ok" : ""}`}>
            {pipelineStatusLabel(pipelineRun?.status)}
          </span>
        </div>
        <div className="metrics-grid">
          <MetricCard
            label="Ultima attività pipeline"
            value={formatDateTime(data.pipeline.last_updated_at)}
          />
          <MetricCard label="Fase corrente" value={pipelineRun?.current_phase || EM_DASH} />
          <MetricCard
            label="Next fixtures importate oggi"
            value={data.pipeline.import_status.next_fixtures_imported_today ? "Sì" : "No"}
          />
          <MetricCard
            label="Ultimo import fixtures"
            value={formatDateTime(data.pipeline.import_status.fixtures_last_imported_at)}
          />
        </div>
        <p className="note live-panel-link">
          <Link to="/global-update-report">Apri il report aggiornamento</Link>
        </p>
      </article>

      <article className="panel live-bot-panel">
        <div className="panel-header">
          <h3>Bot Telegram</h3>
          <Link to="/telegram-bot">Apri dettaglio bot</Link>
        </div>
        <p className="live-bot-status">
          <strong>{data.bot_usage.events_today}</strong> eventi oggi
          <span aria-hidden="true">·</span>
          <strong>{data.bot_usage.unique_users}</strong> utenti unici nel periodo
          {data.bot_usage.top_action ? (
            <>
              <span aria-hidden="true">·</span>
              azione più usata <strong>{data.bot_usage.top_action}</strong>
            </>
          ) : null}
        </p>
      </article>

      <article className="panel">
        <div className="panel-header">
          <div>
            <h3>Errori operativi recenti</h3>
            <p className="note">Ultimo aggiornamento globale e fallimenti Telegram recenti.</p>
          </div>
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
                    <td>{errorSourceLabel(item.source)}</td>
                    <td>{item.message}</td>
                    <td>{item.detail || EM_DASH}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>
    </section>
  );
}
