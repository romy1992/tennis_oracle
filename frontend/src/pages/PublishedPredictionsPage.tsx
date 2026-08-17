import { useEffect, useState } from "react";

import { MarketTabs } from "../components/MarketTabs";
import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient } from "../services/apiClient";
import type {
  LiveDashboardMarket,
  PublishedPrediction,
  PublishedPredictionListResponse,
  PublishedPredictionVersionChainResponse
} from "../types/api";
import { DEFAULT_LIVE_MARKET, marketLabel } from "../utils/markets";
import { formatDate, todayLocalISODate } from "../utils/tennis";

const PAGE_SIZE = 50;

function todayIso() {
  return todayLocalISODate();
}

function daysAgoIso(days: number) {
  const value = new Date();
  value.setDate(value.getDate() - days);
  return todayLocalISODate(value);
}

function formatDateTime(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("it-IT", {
    dateStyle: "short",
    timeStyle: "medium",
    timeZone: "UTC"
  });
}

function formatPct(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "-";
  return `${(value * 100).toFixed(1)}%`;
}

function formatNum(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "-";
  return value.toFixed(digits);
}

function matchLabel(item: PublishedPrediction) {
  const p1 = item.player_1_name ?? "?";
  const p2 = item.player_2_name ?? "?";
  return `${p1} vs ${p2}`;
}

export function PublishedPredictionsPage() {
  const [data, setData] = useState<PublishedPredictionListResponse | null>(null);
  const [versions, setVersions] = useState<PublishedPredictionVersionChainResponse | null>(
    null
  );
  const [fromDate, setFromDate] = useState(() => daysAgoIso(30));
  const [toDate, setToDate] = useState(() => todayIso());
  const [eventKey, setEventKey] = useState("");
  const [source, setSource] = useState("");
  const [market, setMarket] = useState<LiveDashboardMarket>(DEFAULT_LIVE_MARKET);
  const [latestOnly, setLatestOnly] = useState(true);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [versionsError, setVersionsError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const parsedEventKey = eventKey.trim() ? Number(eventKey.trim()) : undefined;
        const response = await apiClient.getPublishedPredictions({
          from: fromDate,
          to: toDate,
          event_key:
            parsedEventKey !== undefined && Number.isFinite(parsedEventKey)
              ? parsedEventKey
              : undefined,
          publication_source: source.trim() || undefined,
          market,
          include_archived: false,
          latest_only: latestOnly,
          limit: PAGE_SIZE,
          offset
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
  }, [fromDate, toDate, eventKey, source, market, latestOnly, offset]);

  async function openVersions(publicationId: string) {
    try {
      setVersionsError(null);
      const chain = await apiClient.getPublishedPredictionVersions(publicationId);
      setVersions(chain);
    } catch (err) {
      setVersions(null);
      setVersionsError(err instanceof Error ? err.message : "Errore caricamento versioni.");
    }
  }

  function selectMarket(next: LiveDashboardMarket) {
    setOffset(0);
    setVersions(null);
    setMarket(next);
  }

  if (loading && !data) return <LoadingState />;
  if (error && !data) {
    return <ErrorState title="Storico non disponibile" message={error} />;
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const frozenCount = items.filter((item) => item.match_started).length;
  const latestCount = items.filter((item) => item.is_latest).length;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h2>Storico pubblicazioni</h2>
          <p>
            Registro immutabile per mercato. Dopo l&apos;inizio partita le righe non sono
            modificabili; le correzioni creano una nuova versione.
          </p>
        </div>
        <span className={`market-badge market-${market}`}>{marketLabel(market)}</span>
      </header>

      <MarketTabs
        value={market}
        onChange={selectMarket}
        ariaLabel="Mercato storico pubblicazioni"
        disabled={loading}
      />

      <div className="filters-grid">
        <label>
          Da
          <input
            type="date"
            value={fromDate}
            onChange={(event) => {
              setOffset(0);
              setFromDate(event.target.value);
            }}
          />
        </label>
        <label>
          A
          <input
            type="date"
            value={toDate}
            onChange={(event) => {
              setOffset(0);
              setToDate(event.target.value);
            }}
          />
        </label>
        <label>
          Event key
          <input
            type="text"
            inputMode="numeric"
            placeholder="es. 12345"
            value={eventKey}
            onChange={(event) => {
              setOffset(0);
              setEventKey(event.target.value);
            }}
          />
        </label>
        <label>
          Fonte
          <input
            type="text"
            placeholder="admin_api, telegram…"
            value={source}
            onChange={(event) => {
              setOffset(0);
              setSource(event.target.value);
            }}
          />
        </label>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={latestOnly}
            onChange={(event) => {
              setOffset(0);
              setLatestOnly(event.target.checked);
            }}
          />
          Solo versione corrente
        </label>
      </div>

      {error ? <ErrorState title="Aggiornamento parziale" message={error} /> : null}

      <div className="metrics-grid">
        <MetricCard label="Pubblicazioni" value={String(total)} />
        <MetricCard label="In pagina" value={String(items.length)} />
        <MetricCard label="Versioni correnti" value={String(latestCount)} />
        <MetricCard label="Partita iniziata" value={String(frozenCount)} />
      </div>

      <article className="panel">
        <div className="panel-header">
          <h3>Registro</h3>
          <span className="pill">
            pagina {page}/{totalPages}
          </span>
        </div>
        {items.length === 0 ? (
          <EmptyState
            title="Nessuna pubblicazione"
            message={`Nessuna pubblicazione ${marketLabel(market)} nel periodo selezionato.`}
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>UTC</th>
                  <th>Partita</th>
                  <th>Mercato</th>
                  <th>Selezione</th>
                  <th>P</th>
                  <th>Quota</th>
                  <th>Void</th>
                  <th>Edge</th>
                  <th>Stake</th>
                  <th>Fonte</th>
                  <th>Ver</th>
                  <th>Stato</th>
                  <th>Hash</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const tipMarket = item.market || market;
                  return (
                    <tr key={item.id}>
                      <td>{formatDateTime(item.published_at)}</td>
                      <td>
                        <div>{matchLabel(item)}</div>
                        <div className="note">
                          #{item.event_key}
                          {item.event_date ? ` · ${formatDate(item.event_date)}` : ""}
                          {item.tournament_name ? ` · ${item.tournament_name}` : ""}
                        </div>
                      </td>
                      <td>
                        <span className={`market-badge market-${tipMarket}`}>
                          {marketLabel(tipMarket)}
                        </span>
                      </td>
                      <td>{item.selection}</td>
                      <td>{formatPct(item.probability)}</td>
                      <td>{formatNum(item.odds)}</td>
                      <td>{formatNum(item.void_odds)}</td>
                      <td>{item.edge == null ? "-" : `${formatNum(item.edge, 1)}%`}</td>
                      <td>{formatNum(item.unit_stake)}</td>
                      <td>{item.publication_source}</td>
                      <td>v{item.content_version}</td>
                      <td>
                        {item.match_started ? "congelata" : item.initial_status}
                        {item.is_latest ? "" : " · superseduta"}
                      </td>
                      <td>
                        <code title={item.content_hash}>{item.content_hash.slice(0, 8)}…</code>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="action-button"
                          onClick={() => void openVersions(item.publication_id)}
                        >
                          Versioni
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="pagination">
          <button
            type="button"
            className="action-button"
            disabled={offset <= 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Precedente
          </button>
          <button
            type="button"
            className="action-button"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Successiva
          </button>
        </div>
      </article>

      {versionsError ? (
        <ErrorState title="Versioni non disponibili" message={versionsError} />
      ) : null}
      {versions ? (
        <article className="panel">
          <div className="panel-header">
            <h3>Catena versioni</h3>
            <span className="pill">{versions.publication_id}</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ver</th>
                  <th>UTC</th>
                  <th>Selezione</th>
                  <th>P</th>
                  <th>Quota</th>
                  <th>Edge</th>
                  <th>Hash</th>
                  <th>Prev</th>
                </tr>
              </thead>
              <tbody>
                {versions.items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      v{item.content_version}
                      {item.is_latest ? " (corrente)" : ""}
                    </td>
                    <td>{formatDateTime(item.published_at)}</td>
                    <td>{item.selection}</td>
                    <td>{formatPct(item.probability)}</td>
                    <td>{formatNum(item.odds)}</td>
                    <td>{item.edge == null ? "-" : `${formatNum(item.edge, 1)}%`}</td>
                    <td>
                      <code title={item.content_hash}>{item.content_hash.slice(0, 12)}…</code>
                    </td>
                    <td>{item.previous_version_id ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      ) : null}
    </section>
  );
}
