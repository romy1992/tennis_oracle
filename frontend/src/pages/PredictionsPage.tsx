import { useCallback, useEffect, useState } from "react";

import { ModelControls } from "../components/ModelControls";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type {
  ImportStatusResponse,
  MLModelName,
  MLModelVersion,
  NextFixtureWithPrediction,
  SingleMatchValueDecision,
  SingleMatchValueResponse
} from "../types/api";
import { readStoredModelName, readStoredModelVersion } from "../utils/modelVersion";
import { formatDate } from "../utils/tennis";

type FixtureStatusFilter = "upcoming" | "played" | "all";
type OutcomeFilter = "all" | "won" | "lost";

const PAGE_SIZE = 50;

const statusTabs: Array<{ value: FixtureStatusFilter; label: string }> = [
  { value: "upcoming", label: "Da giocare" },
  { value: "played", label: "Giocate" },
  { value: "all", label: "Tutte" }
];

const outcomeTabs: Array<{ value: OutcomeFilter; label: string }> = [
  { value: "all", label: "Tutte" },
  { value: "won", label: "Prese" },
  { value: "lost", label: "Perse" }
];

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

function formatSignedPercent(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toLocaleString("it-IT", { maximumFractionDigits: 2 })}%`;
}

function formatSignedPercentValue(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("it-IT", { maximumFractionDigits: 2 })}%`;
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function winnerLabel(
  fixture: NextFixtureWithPrediction,
  winner: string | null | undefined
) {
  if (!winner) return "-";
  if (winner === "First Player") return fixture.event_first_player ?? "Player 1";
  if (winner === "Second Player") return fixture.event_second_player ?? "Player 2";
  return winner;
}

function resultDot(fixture: NextFixtureWithPrediction, show: boolean) {
  if (!show || !fixture.is_completed) return null;
  if (fixture.prediction?.is_correct === null || fixture.prediction?.is_correct === undefined) {
    return null;
  }
  return fixture.prediction.is_correct ? "win" : "loss";
}

function decisionClass(decision: SingleMatchValueDecision) {
  return decision.toLowerCase().replace(/\s+/g, "-");
}

function PaginationControls({
  page,
  totalPages,
  onPrevious,
  onNext
}: {
  page: number;
  totalPages: number;
  onPrevious: () => void;
  onNext: () => void;
}) {
  if (totalPages <= 1) return null;

  return (
    <div className="pagination">
      <button
        type="button"
        className="action-button"
        disabled={page <= 1}
        onClick={onPrevious}
      >
        Precedente
      </button>
      <span className="pagination-label">
        Pagina {page} di {totalPages}
      </span>
      <button
        type="button"
        className="action-button"
        disabled={page >= totalPages}
        onClick={onNext}
      >
        Successiva
      </button>
    </div>
  );
}

export function PredictionsPage() {
  const [fixtures, setFixtures] = useState<NextFixtureWithPrediction[]>([]);
  const [totalFixtures, setTotalFixtures] = useState(0);
  const [singleValue, setSingleValue] = useState<SingleMatchValueResponse | null>(null);
  const [importStatus, setImportStatus] = useState<ImportStatusResponse | null>(null);
  const [statusFilter, setStatusFilter] = useState<FixtureStatusFilter>("upcoming");
  const [outcomeFilter, setOutcomeFilter] = useState<OutcomeFilter>("all");
  const [modelVersion, setModelVersion] = useState<MLModelVersion>(() => readStoredModelVersion());
  const [page, setPage] = useState(1);
  const [daysBack, setDaysBack] = useState(1);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [importingFixtures, setImportingFixtures] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [playerSearch, setPlayerSearch] = useState("");
  const [playerQuery, setPlayerQuery] = useState("");
  const [minEdgePercent, setMinEdgePercent] = useState(3);
  const [modelName, setModelName] = useState<MLModelName>(() => readStoredModelName());
  const [error, setError] = useState<string | null>(null);

  const totalPages = Math.max(1, Math.ceil(totalFixtures / PAGE_SIZE));
  const showResultDots = statusFilter === "played" || statusFilter === "all";

  useEffect(() => {
    setPage(1);
  }, [statusFilter, outcomeFilter, playerQuery, modelVersion, modelName, minEdgePercent]);

  const loadPageData = useCallback(async () => {
    const offset = (page - 1) * PAGE_SIZE;
    const trimmedPlayer = playerQuery.trim();
    const [fixturesPage, valueData, statusData] = await Promise.all([
      apiClient.getUpcomingPredictions({
        model_version: modelVersion,
        model_name: modelName,
        status: statusFilter,
        outcome: statusFilter === "played" ? outcomeFilter : undefined,
        limit: PAGE_SIZE,
        offset,
        player: trimmedPlayer || undefined
      }),
      apiClient.getSingleMatchValueAnalysis({
        model_version: modelVersion,
        model_name: modelName,
        status: statusFilter,
        outcome: statusFilter === "played" ? outcomeFilter : undefined,
        limit: PAGE_SIZE,
        offset,
        player: trimmedPlayer || undefined,
        min_edge_percent: minEdgePercent
      }),
      apiClient.getImportStatus()
    ]);
    setFixtures(fixturesPage.items);
    setTotalFixtures(fixturesPage.total);
    setSingleValue(valueData);
    setImportStatus(statusData);
  }, [statusFilter, outcomeFilter, page, playerQuery, modelVersion, modelName, minEdgePercent]);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        await loadPageData();
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore inatteso.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [loadPageData]);

  async function handleRefresh() {
    try {
      setRefreshing(true);
      setActionMessage(null);
      const statusBefore = importStatus ?? (await apiClient.getImportStatus());
      const coverageIncomplete =
        statusBefore.next_fixtures_max_date !== null &&
        statusBefore.next_fixtures_window_until !== null &&
        statusBefore.next_fixtures_max_date < statusBefore.next_fixtures_window_until;
      const result = await apiClient.refreshMatches({
        model_version: modelVersion,
        model_name: modelName,
        force_next_import: coverageIncomplete || !statusBefore.next_fixtures_imported_today
      });
      setPage(1);
      await loadPageData();
      const importedToday = result.import_status.next_fixtures_imported_today;
      const importedNow = result.next_fixtures_imported;
      setActionMessage(
        importedNow
          ? coverageIncomplete
            ? "Calendario reimportato (copertura incompleta) e previsioni rigenerate."
            : "Calendario aggiornato e previsioni rigenerate."
          : importedToday
            ? "Previsioni rigenerate. Il calendario era gia aggiornato oggi."
            : "Previsioni rigenerate."
      );
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante l'aggiornamento.");
    } finally {
      setRefreshing(false);
    }
  }

  async function handleImportFixtures() {
    try {
      setImportingFixtures(true);
      setActionMessage(null);
      await apiClient.importPlayedFixtures(daysBack);
      const status = await apiClient.getImportStatus();
      setImportStatus(status);
      if (statusFilter !== "upcoming") {
        setPage(1);
        await loadPageData();
      }
      setActionMessage(`Import disputate completato (${daysBack} giorni indietro).`);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante l'import fixtures.");
    } finally {
      setImportingFixtures(false);
    }
  }

  if (loading) {
    return <LoadingState title="Caricamento partite..." />;
  }

  if (error && fixtures.length === 0 && !importStatus) {
    return <ErrorState title="Partite non disponibili" message={error} />;
  }

  const calendarCoverageNote =
    importStatus?.next_fixtures_max_date &&
    importStatus.next_fixtures_window_until &&
    importStatus.next_fixtures_max_date < importStatus.next_fixtures_window_until
      ? `Calendario coperto fino al ${formatDate(importStatus.next_fixtures_max_date)} (previsto fino al ${formatDate(importStatus.next_fixtures_window_until)}). Usa Aggiorna per reimportare.`
      : importStatus?.next_fixtures_window_until
        ? `Finestra da giocare: oggi → ${formatDate(importStatus.next_fixtures_window_until)} (${importStatus.next_fixtures_window_days} giorni).`
        : null;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Partite</h2>
          <p>
            Calendario, previsioni salvate e import manuali. Usa Aggiorna per
            sincronizzare next_fixture e rigenerare le prediction del giorno.
          </p>
        </div>
        <div className="header-actions">
          <ModelControls
            modelVersion={modelVersion}
            modelName={modelName}
            onModelVersionChange={setModelVersion}
            onModelNameChange={setModelName}
            disabled={refreshing || importingFixtures}
          />
          <button
            type="button"
            className="action-button primary"
            onClick={() => void handleRefresh()}
            disabled={refreshing || importingFixtures}
          >
            {refreshing ? "Aggiornamento..." : "Aggiorna"}
          </button>
        </div>
      </header>

      <article className="panel">
        <div className="panel-header">
          <h3>Stato import</h3>
        </div>
        <div className="import-status-grid">
          <div>
            <span className="import-status-label">Copertura calendario (da giocare)</span>
            <strong>
              {importStatus?.next_fixtures_max_date
                ? formatDate(importStatus.next_fixtures_max_date)
                : "-"}
            </strong>
            <small>
              {importStatus?.next_fixtures_window_until
                ? `Previsto fino al ${formatDate(importStatus.next_fixtures_window_until)}`
                : "Non disponibile"}
            </small>
          </div>
          <div>
            <span className="import-status-label">Ultimo aggiornamento calendario</span>
            <strong>{formatDateTime(importStatus?.next_fixtures_last_imported_at)}</strong>
            <small>
              {importStatus?.next_fixtures_imported_today
                ? "Gia aggiornato oggi"
                : "Non ancora aggiornato oggi"}
            </small>
          </div>
          <div>
            <span className="import-status-label">Ultima giornata disputata importata</span>
            <strong>{formatDate(importStatus?.fixtures_last_match_date ?? null)}</strong>
            <small>
              Import eseguito il {formatDateTime(importStatus?.fixtures_last_imported_at)}
            </small>
          </div>
        </div>

        <div className="import-actions">
          <label className="import-days-field">
            <span>Giorni indietro (fixtures disputate)</span>
            <select
              value={daysBack}
              onChange={(event) => setDaysBack(Number(event.target.value))}
              disabled={importingFixtures || refreshing}
            >
              {[0, 1, 2, 3, 5, 7, 14, 30].map((value) => (
                <option key={value} value={value}>
                  {value === 0 ? "Solo oggi" : `${value} giorni`}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="action-button"
            onClick={() => void handleImportFixtures()}
            disabled={importingFixtures || refreshing}
          >
            {importingFixtures ? "Import in corso..." : "Importa disputate"}
          </button>
        </div>

        {actionMessage ? <p className="note action-note">{actionMessage}</p> : null}
        {error ? <p className="note action-error">{error}</p> : null}
      </article>

      <article className="panel single-value-panel">
        <div className="section-header">
          <div>
            <h3>Single Match Value Analysis</h3>
            <p>
              Analisi da investitore sulla singola partita: una giocata non basta che sia
              probabile, deve superare la quota void.
            </p>
          </div>
          <label className="min-edge-field">
            <span>Margine sicurezza</span>
            <input
              type="number"
              min="0"
              max="100"
              step="0.5"
              value={minEdgePercent}
              onChange={(event) => setMinEdgePercent(Number(event.target.value))}
              disabled={refreshing || importingFixtures}
            />
            <small>% sopra quota void</small>
          </label>
        </div>

        {singleValue ? (
          <>
            <div className="single-value-summary">
              <div>
                <span>PLAY</span>
                <strong>{singleValue.summary.play_count}</strong>
                <small>Valore reale intercettato</small>
              </div>
              <div>
                <span>BORDERLINE</span>
                <strong>{singleValue.summary.borderline_count}</strong>
                <small>Quota in area void</small>
              </div>
              <div>
                <span>NO BET</span>
                <strong>{singleValue.summary.no_bet_count}</strong>
                <small>Quota sotto valore</small>
              </div>
              <div>
                <span>ROI medio atteso</span>
                <strong>{formatSignedPercent(singleValue.summary.avg_expected_roi)}</strong>
                <small>Stake simulato 1 unita</small>
              </div>
            </div>

            {singleValue.simulation.play_bets.resolved_count > 0 ? (
              <p className="note">
                Simulazione storica PLAY: {singleValue.simulation.play_bets.resolved_count} giocate
                risolte, ROI {formatSignedPercentValue(singleValue.simulation.play_bets.roi_pct)},
                hit rate {formatSignedPercentValue(singleValue.simulation.play_bets.hit_rate_pct)},
                P/L {singleValue.simulation.play_bets.profit_loss_units.toLocaleString("it-IT", {
                  maximumFractionDigits: 2
                })}{" "}
                unita.
              </p>
            ) : (
              <p className="note">
                La simulazione storica si popola quando ci sono partite risolte classificate PLAY.
              </p>
            )}

            {singleValue.items.length === 0 ? (
              <EmptyState
                title="Nessuna singola analizzabile"
                message="Servono prediction AI e quote bookmaker disponibili per calcolare quota void e valore."
              />
            ) : (
              <div className="single-value-list">
                {singleValue.items.map((item) => (
                  <section key={item.match_id} className="single-value-card">
                    <div className="single-value-card-header">
                      <div>
                        <span className="single-value-market">{item.market}</span>
                        <h4>
                          {item.player_a ?? "?"} vs {item.player_b ?? "?"}
                        </h4>
                        <p>
                          {item.tournament_name ?? "Torneo non disponibile"} · Selezione:{" "}
                          <strong>{item.selection}</strong>
                        </p>
                      </div>
                      <span className={`value-decision-badge ${decisionClass(item.decision)}`}>
                        {item.decision}
                      </span>
                    </div>

                    <div className="single-value-metrics">
                      <div>
                        <span>Probabilita AI</span>
                        <strong>{formatProb(item.model_probability)}</strong>
                      </div>
                      <div>
                        <span>Quota mercato</span>
                        <strong>{formatOdds(item.market_odds)}</strong>
                      </div>
                      <div>
                        <span>Quota void</span>
                        <strong>{formatOdds(item.void_odds)}</strong>
                      </div>
                      <div>
                        <span>Margine</span>
                        <strong className={item.edge_percent >= 0 ? "positive-value" : "negative-value"}>
                          {formatSignedPercentValue(item.edge_percent)}
                        </strong>
                      </div>
                      <div>
                        <span>ROI atteso</span>
                        <strong className={item.expected_roi >= 0 ? "positive-value" : "negative-value"}>
                          {formatSignedPercent(item.expected_roi)}
                        </strong>
                      </div>
                      <div>
                        <span>Stake simulato</span>
                        <strong>{item.stake.toLocaleString("it-IT")} unita</strong>
                      </div>
                    </div>

                    <p className="single-value-explanation">
                      <strong>{item.value_label}.</strong> {item.explanation}
                    </p>
                  </section>
                ))}
              </div>
            )}
          </>
        ) : (
          <LoadingState title="Caricamento analisi valore..." />
        )}
      </article>

      <article className="panel">
        <div className="panel-header">
          <h3>Calendario</h3>
          <span className="pill pill-ok">
            {totalFixtures === 0
              ? "0 match"
              : `${fixtures.length} di ${totalFixtures} match`}
          </span>
        </div>

        <div className="tab-list" aria-label="Filtro stato partite">
          {statusTabs.map((tab) => (
            <button
              key={tab.value}
              type="button"
              className={statusFilter === tab.value ? "active" : undefined}
              onClick={() => setStatusFilter(tab.value)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {statusFilter === "played" ? (
          <div className="tab-list outcome-tabs" aria-label="Filtro esito previsione">
            {outcomeTabs.map((tab) => (
              <button
                key={tab.value}
                type="button"
                className={outcomeFilter === tab.value ? "active" : undefined}
                onClick={() => setOutcomeFilter(tab.value)}
              >
                {tab.value === "won" ? (
                  <>
                    <span className="result-dot win" aria-hidden="true" /> {tab.label}
                  </>
                ) : tab.value === "lost" ? (
                  <>
                    <span className="result-dot loss" aria-hidden="true" /> {tab.label}
                  </>
                ) : (
                  tab.label
                )}
              </button>
            ))}
          </div>
        ) : null}

        {calendarCoverageNote && statusFilter !== "played" ? (
          <p className="note">{calendarCoverageNote}</p>
        ) : null}

        {statusFilter === "played" ? (
          <p className="note">
            Mostra tutte le partite concluse negli ultimi 30 giorni, anche senza previsione.
            Le partite appena terminate compaiono qui dopo Aggiorna o Importa disputate.
          </p>
        ) : null}

        <div className="player-search-row">
          <label htmlFor="player-search">Cerca giocatore</label>
          <div className="player-search-controls">
            <input
              id="player-search"
              type="search"
              placeholder="Es. Sinner, Alcaraz..."
              value={playerSearch}
              onChange={(event) => setPlayerSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  setPlayerQuery(playerSearch.trim());
                  setPage(1);
                }
              }}
            />
            <button
              type="button"
              className="action-button"
              onClick={() => {
                setPlayerQuery(playerSearch.trim());
                setPage(1);
              }}
            >
              Cerca
            </button>
            {playerQuery ? (
              <button
                type="button"
                className="pill"
                onClick={() => {
                  setPlayerSearch("");
                  setPlayerQuery("");
                  setPage(1);
                }}
              >
                Cancella
              </button>
            ) : null}
          </div>
        </div>

        {showResultDots ? (
          <p className="note result-legend">
            <span className="result-dot win" aria-hidden="true" /> Previsione corretta
            <span className="result-dot loss" aria-hidden="true" /> Previsione errata
          </p>
        ) : null}

        {fixtures.length === 0 ? (
          <EmptyState
            title="Nessuna partita"
            message="Usa Aggiorna per importare il calendario e generare le previsioni."
          />
        ) : (
          <>
            <PaginationControls
              page={page}
              totalPages={totalPages}
              onPrevious={() => setPage((current) => Math.max(1, current - 1))}
              onNext={() => setPage((current) => Math.min(totalPages, current + 1))}
            />

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {showResultDots ? <th /> : null}
                    <th>Data</th>
                    <th>Ora</th>
                    <th>Torneo</th>
                    <th>Surface</th>
                    <th>Match</th>
                    <th>Prob P1</th>
                    <th>Predetto</th>
                    <th>Quota predetto</th>
                    <th>Confidence</th>
                    <th>Versione</th>
                    <th>Modello</th>
                    <th>Stato</th>
                  </tr>
                </thead>
                <tbody>
                  {fixtures.map((fixture) => {
                    const dot = resultDot(fixture, showResultDots);
                    return (
                      <tr key={fixture.event_key}>
                        {showResultDots ? (
                          <td className="result-dot-cell">
                            {dot ? (
                              <span
                                className={`result-dot ${dot}`}
                                title={dot === "win" ? "Previsione corretta" : "Previsione errata"}
                              />
                            ) : null}
                          </td>
                        ) : null}
                        <td>{formatDate(fixture.event_date)}</td>
                        <td>{formatTime(fixture.event_time)}</td>
                        <td>{fixture.tournament_name ?? "-"}</td>
                        <td>{fixture.surface ?? "-"}</td>
                        <td>
                          {fixture.event_first_player ?? "?"} vs{" "}
                          {fixture.event_second_player ?? "?"}
                        </td>
                        <td>{formatProb(fixture.prediction?.prob_player_1_win)}</td>
                        <td>{winnerLabel(fixture, fixture.prediction?.predicted_winner)}</td>
                        <td>{formatOdds(fixture.prediction?.predicted_winner_odds)}</td>
                        <td>{formatProb(fixture.prediction?.confidence)}</td>
                        <td>{fixture.prediction?.model_version ?? "-"}</td>
                        <td>{fixture.prediction?.model_name ?? "-"}</td>
                        <td>
                          {fixture.is_completed
                            ? "Giocata"
                            : fixture.prediction
                              ? "Da giocare"
                              : "Da generare"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <PaginationControls
              page={page}
              totalPages={totalPages}
              onPrevious={() => setPage((current) => Math.max(1, current - 1))}
              onNext={() => setPage((current) => Math.min(totalPages, current + 1))}
            />
          </>
        )}
      </article>
    </section>
  );
}
