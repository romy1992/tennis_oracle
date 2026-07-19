import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { useGlobalUpdate } from "../hooks/useGlobalUpdate";
import { apiClient } from "../services/apiClient";
import type {
  ImportStatusResponse,
  MLModelVersion,
  MatchPrediction,
  ModelsVersionsResultsResponse,
  NextFixtureWithPrediction,
  SingleMatchValueDecision,
  SingleMatchValueResponse
} from "../types/api";
import { classifySingleBetValue } from "../utils/minEdge";
import {
  DEFAULT_MODEL_VERSION,
  resolvePreferredModelVersion,
  writeStoredModelVersion
} from "../utils/modelVersion";
import { formatDate } from "../utils/tennis";

// #region agent log
function agentLog(payload: {
  hypothesisId: string;
  location: string;
  message: string;
  data?: Record<string, unknown>;
  runId?: string;
}) {
  const body = {
    sessionId: "839b99",
    runId: payload.runId ?? "post-fix",
    hypothesisId: payload.hypothesisId,
    location: payload.location,
    message: payload.message,
    data: payload.data ?? {},
    timestamp: Date.now()
  };
  const encoded = JSON.stringify(body);
  fetch("http://127.0.0.1:7516/ingest/51ba4cbe-10fb-4c0d-94ec-cc65bebcec2f", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "839b99" },
    body: encoded
  }).catch(() => {});
  // Prefer 127.0.0.1 (known-good in this session); also try localhost / VITE base.
  for (const base of [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    import.meta.env.VITE_API_BASE_URL
  ].filter(Boolean)) {
    fetch(`${base}/api/debug/agent-log`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: encoded
    }).catch(() => {});
  }
}
// #endregion

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

function resultDot(fixture: MergedFixtureRow, show: boolean) {
  if (!show || !fixture.is_completed) return null;
  const anyPrediction = Object.values(fixture.predictionsByModel).find(Boolean);
  if (anyPrediction?.is_correct === null || anyPrediction?.is_correct === undefined) {
    return null;
  }
  return anyPrediction.is_correct ? "win" : "loss";
}

function decisionClass(decision: SingleMatchValueDecision) {
  return decision.toLowerCase().replace(/\s+/g, "-");
}

function modelProbForWinner(
  predictedWinner: string | null | undefined,
  probPlayer1Win: number | null | undefined
): number | null {
  if (probPlayer1Win == null || !predictedWinner) return null;
  if (predictedWinner === "First Player") return probPlayer1Win;
  if (predictedWinner === "Second Player") return 1 - probPlayer1Win;
  return null;
}

function resolveValueItem(
  analysis: SingleMatchValueResponse | undefined,
  eventKey: number,
  globalMinEdge: number,
  prediction?: MatchPrediction | null
): { void_odds: number; decision: SingleMatchValueDecision } | null {
  const item = analysis?.items.find((entry) => entry.match_id === eventKey);
  if (item) {
    const decision = classifySingleBetValue(item.market_odds, item.void_odds, globalMinEdge);
    // #region agent log
    if (globalMinEdge === 0 || item.decision !== decision) {
      fetch('http://127.0.0.1:7516/ingest/51ba4cbe-10fb-4c0d-94ec-cc65bebcec2f',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'839b99'},body:JSON.stringify({sessionId:'839b99',runId:'pre-fix',hypothesisId:'C,D',location:'PredictionsPage.tsx:resolveValueItem',message:'classify from SMVA item',data:{eventKey,globalMinEdge,marketOdds:item.market_odds,voidOdds:item.void_odds,apiDecision:item.decision,clientDecision:decision,playThreshold:item.void_odds*(1+globalMinEdge/100)},timestamp:Date.now()})}).catch(()=>{});
    }
    // #endregion
    return {
      void_odds: item.void_odds,
      decision
    };
  }

  // Fallback for played rows: derive void/decision from the prediction already on the fixture.
  const modelProb = modelProbForWinner(
    prediction?.predicted_winner,
    prediction?.prob_player_1_win
  );
  const marketOdds = prediction?.predicted_winner_odds;
  if (modelProb == null || modelProb <= 0 || marketOdds == null) {
    return null;
  }
  const voidOdds = 1 / modelProb;
  const decision = classifySingleBetValue(marketOdds, voidOdds, globalMinEdge);
  // #region agent log
  if (globalMinEdge === 0) {
    fetch('http://127.0.0.1:7516/ingest/51ba4cbe-10fb-4c0d-94ec-cc65bebcec2f',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'839b99'},body:JSON.stringify({sessionId:'839b99',runId:'pre-fix',hypothesisId:'C,D',location:'PredictionsPage.tsx:resolveValueItem',message:'classify from prediction fallback',data:{eventKey,globalMinEdge,marketOdds,voidOdds,clientDecision:decision,playThreshold:voidOdds*(1+globalMinEdge/100)},timestamp:Date.now()})}).catch(()=>{});
  }
  // #endregion
  return {
    void_odds: voidOdds,
    decision
  };
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

type MergedFixtureRow = NextFixtureWithPrediction & {
  predictionsByModel: Record<string, MatchPrediction | null>;
};

function modelLabel(name: string) {
  if (name === "logistic_regression") return "Logistic";
  if (name === "random_forest") return "Random Forest";
  return name;
}

export function PredictionsPage() {
  const { status: globalStatus, isRunning: globalUpdating, lastCompletedAt } = useGlobalUpdate();
  const [availableVersions, setAvailableVersions] = useState<ModelsVersionsResultsResponse["versions"]>([]);
  const [activeVersion, setActiveVersion] = useState<MLModelVersion>(DEFAULT_MODEL_VERSION);
  const [fixtures, setFixtures] = useState<MergedFixtureRow[]>([]);
  const [modelNames, setModelNames] = useState<string[]>([]);
  const [totalFixtures, setTotalFixtures] = useState(0);
  const [singleValueByModel, setSingleValueByModel] = useState<Record<string, SingleMatchValueResponse>>({});
  const [importStatus, setImportStatus] = useState<ImportStatusResponse | null>(null);
  const [statusFilter, setStatusFilter] = useState<FixtureStatusFilter>("upcoming");
  const [outcomeFilter, setOutcomeFilter] = useState<OutcomeFilter>("all");
  const [page, setPage] = useState(1);
  const [daysBack, setDaysBack] = useState(1);
  const [loading, setLoading] = useState(true);
  const [importingFixtures, setImportingFixtures] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [playerSearch, setPlayerSearch] = useState("");
  const [playerQuery, setPlayerQuery] = useState("");
  const [minEdgePercent, setMinEdgePercent] = useState(2);
  const [error, setError] = useState<string | null>(null);
  const [lastReloadToken, setLastReloadToken] = useState<string | null>(null);

  const totalPages = Math.max(1, Math.ceil(totalFixtures / PAGE_SIZE));
  const showResultDots = statusFilter === "played" || statusFilter === "all";

  useEffect(() => {
    async function loadCatalog() {
      try {
        const catalog = await apiClient.getModelsVersionsResults();
        setAvailableVersions(catalog.versions);
        if (catalog.versions.length > 0) {
          setActiveVersion(resolvePreferredModelVersion(catalog.versions));
        }
      } catch {
        setAvailableVersions([]);
      }
    }
    void loadCatalog();
  }, [lastCompletedAt]);

  useEffect(() => {
    setPage(1);
  }, [statusFilter, outcomeFilter, playerQuery, activeVersion]);

  const activeModels = useMemo(
    () =>
      availableVersions.find((entry) => entry.version === activeVersion)?.models.map((m) => m.model) ??
      [],
    [availableVersions, activeVersion]
  );

  const loadPageData = useCallback(async () => {
    const offset = (page - 1) * PAGE_SIZE;
    const trimmedPlayer = playerQuery.trim();
    const models = activeModels.length ? activeModels : ["logistic_regression"];

    const fixtureResponses = await Promise.all(
      models.map((modelName) =>
        apiClient.getUpcomingPredictions({
          model_version: activeVersion,
          model_name: modelName,
          status: statusFilter,
          outcome: statusFilter === "played" ? outcomeFilter : undefined,
          limit: PAGE_SIZE,
          offset,
          player: trimmedPlayer || undefined
        })
      )
    );

    // #region agent log
    agentLog({
      hypothesisId: "B",
      location: "PredictionsPage.tsx:loadPageData",
      message: "fetching fixtures+SMVA (margin not a reload trigger)",
      data: { statusFilter, activeVersion, models }
    });
    // #endregion
    // Fetch odds/void once; PLAY/BORDERLINE/NO BET is reclassified client-side from minEdgePercent.
    const valueResponses = await Promise.all(
      models.map((modelName) =>
        apiClient.getSingleMatchValueAnalysis({
          model_version: activeVersion,
          model_name: modelName,
          status: statusFilter,
          outcome: statusFilter === "played" ? outcomeFilter : undefined,
          limit: 200,
          offset: 0,
          player: trimmedPlayer || undefined,
          min_edge_percent: 0
        })
      )
    );

    const statusData = await apiClient.getImportStatus();
    const base = fixtureResponses[0];
    const merged: MergedFixtureRow[] = (base?.items ?? []).map((fixture) => {
      const predictionsByModel: Record<string, MatchPrediction | null> = {};
      models.forEach((modelName, index) => {
        const match = fixtureResponses[index]?.items.find((item) => item.event_key === fixture.event_key);
        predictionsByModel[modelName] = match?.prediction ?? null;
      });
      return { ...fixture, predictionsByModel };
    });

    const values: Record<string, SingleMatchValueResponse> = {};
    models.forEach((modelName, index) => {
      values[modelName] = valueResponses[index];
    });

    setFixtures(merged);
    setModelNames(models);
    setTotalFixtures(base?.total ?? 0);
    setSingleValueByModel(values);
    setImportStatus(statusData);
  }, [statusFilter, outcomeFilter, page, playerQuery, activeVersion, activeModels]);

  const decisionCounts = useMemo(() => {
    const counts = { PLAY: 0, BORDERLINE: 0, "NO BET": 0, missing: 0 };
    const primaryModel = modelNames[0];
    const analysis = primaryModel ? singleValueByModel[primaryModel] : undefined;
    for (const fixture of fixtures) {
      const prediction = primaryModel ? fixture.predictionsByModel[primaryModel] : null;
      const value = resolveValueItem(analysis, fixture.event_key, minEdgePercent, prediction);
      if (!value) {
        counts.missing += 1;
        continue;
      }
      counts[value.decision] += 1;
    }
    return counts;
  }, [fixtures, singleValueByModel, modelNames, minEdgePercent]);

  useEffect(() => {
    // #region agent log
    agentLog({
      hypothesisId: "C,E",
      location: "PredictionsPage.tsx:decisionCounts",
      message: "visible page decision counts for current margin",
      data: { minEdgePercent, decisionCounts, fixtureCount: fixtures.length }
    });
    // #endregion
  }, [minEdgePercent, decisionCounts, fixtures.length]);

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

  useEffect(() => {
    if (!lastCompletedAt || lastCompletedAt === lastReloadToken) {
      return;
    }
    setLastReloadToken(lastCompletedAt);
    void loadPageData();
    setActionMessage("Dati aggiornati dall'ultima run globale.");
  }, [lastCompletedAt, lastReloadToken, loadPageData]);

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
      ? `Calendario coperto fino al ${formatDate(importStatus.next_fixtures_max_date)} (previsto fino al ${formatDate(importStatus.next_fixtures_window_until)}). Usa Aggiorna tutto nella sidebar.`
      : importStatus?.next_fixtures_window_until
        ? `Finestra da giocare: oggi → ${formatDate(importStatus.next_fixtures_window_until)} (${importStatus.next_fixtures_window_days} giorni).`
        : null;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Partite</h2>
          <p>
            Calendario e previsioni salvate per tutte le versioni e i modelli disponibili.
            L&apos;aggiornamento globale e nella sidebar.
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
              onChange={(event) => {
                const raw = event.target.value;
                const next = Number(raw) || 0;
                // #region agent log
                agentLog({
                  hypothesisId: "A",
                  location: "PredictionsPage.tsx:minEdge.onChange",
                  message: "margin input changed",
                  data: { raw, parsed: Number(raw), next, previous: minEdgePercent }
                });
                // #endregion
                setMinEdgePercent(next);
              }}
              disabled={globalUpdating || importingFixtures}
            />
            <small>% sopra quota void (default 2). A 0% solo BORDERLINE → PLAY.</small>
            <small>
              Pagina: PLAY {decisionCounts.PLAY} · BORDERLINE {decisionCounts.BORDERLINE} · NO BET{" "}
              {decisionCounts["NO BET"]}
            </small>
          </label>
          {globalStatus ? (
            <div className="header-actions">
              <span className="pill">{globalStatus.current_phase ?? globalStatus.status}</span>
              {globalUpdating ? <span className="pill">Run in corso</span> : null}
            </div>
          ) : null}
        </div>
      </header>

      {availableVersions.length ? (
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
              {entry.version}
            </button>
          ))}
        </div>
      ) : null}

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
              disabled={importingFixtures || globalUpdating}
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
            disabled={importingFixtures || globalUpdating}
          >
            {importingFixtures ? "Import in corso..." : "Importa disputate"}
          </button>
        </div>

        {actionMessage ? <p className="note action-note">{actionMessage}</p> : null}
        {error ? <p className="note action-error">{error}</p> : null}
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

        <p className="note">
          Per ogni modello: quota void e stato PLAY / BORDERLINE / NO BET in base al margine di
          sicurezza impostato in alto nella pagina.
          {statusFilter === "played"
            ? " In Giocate compaiono prima le partite con pronostico salvato; senza previsione restano vuote (usa Aggiorna tutto prima che finiscano)."
            : null}
        </p>

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
                    {modelNames.map((name) => (
                      <th key={name} colSpan={4}>
                        {modelLabel(name)}
                      </th>
                    ))}
                    <th>Stato</th>
                  </tr>
                  <tr>
                    <th colSpan={showResultDots ? 6 : 5} />
                    {modelNames.map((name) => (
                      <Fragment key={name}>
                        <th>Predetto</th>
                        <th>Conf.</th>
                        <th>Void</th>
                        <th>Valore</th>
                      </Fragment>
                    ))}
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {fixtures.map((fixture) => {
                    const dot = resultDot(fixture, showResultDots);
                    const hasAnyPrediction = Object.values(fixture.predictionsByModel).some(Boolean);
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
                        {modelNames.map((name) => {
                          const prediction = fixture.predictionsByModel[name];
                          const valueItem = resolveValueItem(
                            singleValueByModel[name],
                            fixture.event_key,
                            minEdgePercent,
                            prediction
                          );
                          return (
                            <Fragment key={`${fixture.event_key}-${name}`}>
                              <td>{winnerLabel(fixture, prediction?.predicted_winner)}</td>
                              <td>{formatProb(prediction?.confidence)}</td>
                              <td>{formatOdds(valueItem?.void_odds)}</td>
                              <td>
                                {valueItem ? (
                                  <span
                                    className={`value-decision-badge ${decisionClass(valueItem.decision)}`}
                                  >
                                    {valueItem.decision}
                                  </span>
                                ) : (
                                  "-"
                                )}
                              </td>
                            </Fragment>
                          );
                        })}
                        <td>
                          {fixture.is_completed
                            ? "Giocata"
                            : hasAnyPrediction
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
