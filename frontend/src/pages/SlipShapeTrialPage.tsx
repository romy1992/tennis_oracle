import { useEffect, useState } from "react";

import { MetricCard } from "../components/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "../components/Status";
import { apiClient, ApiError } from "../services/apiClient";
import type { SlipShapeSelectionCheck, SlipShapeSingleSlice, SlipShapeSlice, SlipShapeTrial } from "../types/api";

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${value.toLocaleString("it-IT", { maximumFractionDigits: 1 })}%`;
}

function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return value.toLocaleString("it-IT", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function formatDate(value: string) {
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("it-IT");
}

function methodLabel(method: string) {
  if (method === "platt") return "Platt";
  if (method === "isotonic") return "Isotonica";
  return "Grezza";
}

function dimensionLabel(dimension: string) {
  return dimension === "odds" ? "Quota" : "Edge";
}

function SlipCards({ slip }: { slip: SlipShapeSlice }) {
  return (
    <div className="metric-grid">
      <MetricCard label="Schedine vinte / perse" value={`${slip.slips_won} / ${slip.slips_lost}`} hint={`${slip.slips_pending} aperte`} />
      <MetricCard label="Win rate schedina" value={formatPct(slip.slip_win_rate_pct)} />
      <MetricCard label="Hit pick" value={formatPct(slip.pick_hit_rate_pct)} hint={`${slip.picks_won} vinte, ${slip.picks_lost} perse`} />
      <MetricCard label="ROI" value={formatPct(slip.roi_pct)} hint={`profitto ${formatMoney(slip.profit_units)} su ${formatMoney(slip.stake_units)}`} />
    </div>
  );
}

function SingleRow({ row }: { row: SlipShapeSingleSlice }) {
  return (
    <tr>
      <td>{row.label}</td>
      <td>{row.won + row.lost}</td>
      <td>{formatPct(row.hit_rate_pct)}</td>
      <td>{formatPct(row.roi_pct)}</td>
      <td>{formatMoney(row.profit_units)}</td>
    </tr>
  );
}

function checkLabel(check: SlipShapeSelectionCheck) {
  return `${dimensionLabel(check.dimension)} ${check.band}`;
}

export function SlipShapeTrialPage() {
  const [trial, setTrial] = useState<SlipShapeTrial | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiClient
      .getSlipShapeTrial()
      .then((payload) => {
        if (!cancelled) setTrial(payload);
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof ApiError ? caught.message : "Prova schedine non disponibile.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return <LoadingState title="Caricamento prova schedine" message="Confronto sul periodo congelato." />;
  }
  if (error) {
    return <ErrorState title="Prova schedine non disponibile" message={error} />;
  }
  if (!trial) {
    return <EmptyState title="Nessun risultato" message="Il periodo di prova non ha schedine." />;
  }

  const visibleChecks = trial.checks.filter(
    (check) => check.august_settled > 0 || check.september_settled > 0
  );

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h2>Prova schedine</h2>
          <p className="muted">
            {formatDate(trial.window_from)} – {formatDate(trial.window_to)} · {trial.model_version} /{" "}
            {trial.model_name} · stake {trial.stake.toLocaleString("it-IT")} · split{" "}
            {formatDate(trial.split_date)} · minimo {trial.min_samples} casi per metà
          </p>
        </div>
      </header>

      <article className="panel">
        <h3>{trial.selection_passed ? "Selezione possibile" : "Selezione invariata"}</h3>
        <p>{trial.conclusion}</p>
        {trial.passing_rules.length > 0 ? (
          <p>
            Regole: <strong>{trial.passing_rules.join(", ")}</strong>
          </p>
        ) : null}
      </article>

      <article className="panel">
        <h3>Generiche</h3>
        <p className="muted">Schedine già salvate, stessa chiusura sulle partite finite. La pagina Consiglio non cambia.</p>
        <SlipCards slip={trial.official_slips} />
      </article>

      <article className="panel">
        <h3>Forma corta</h3>
        <p className="muted">{trial.short_slip_rule}</p>
        <SlipCards slip={trial.short_slips} />
      </article>

      <article className="panel">
        <h3>Singole, per mercato</h3>
        <p className="muted">Ogni partita conta una volta. Non sono schedine.</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Mercato</th>
                <th>Chiuse</th>
                <th>Hit</th>
                <th>ROI</th>
                <th>Profitto</th>
              </tr>
            </thead>
            <tbody>
              <SingleRow row={trial.match_winner_singles} />
              <SingleRow row={trial.first_set_singles} />
              <SingleRow row={trial.over_under_singles} />
            </tbody>
          </table>
        </div>
      </article>

      <article className="panel">
        <h3>Controllo a metà campione</h3>
        <p className="muted">
          Una riga passa solo se il ROI è positivo su agosto e su settembre, con almeno {trial.min_samples} casi in ciascuna metà.
          Per Platt e isotonica la probabilità è ricalibrata sull'altra metà.
        </p>
        {visibleChecks.length === 0 ? (
          <EmptyState title="Nessun controllo" message="Nel periodo non ci sono match winner chiusi con quota." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Regola</th>
                  <th>Probabilità</th>
                  <th>Agosto</th>
                  <th>ROI agosto</th>
                  <th>Settembre</th>
                  <th>ROI settembre</th>
                  <th>Esito</th>
                </tr>
              </thead>
              <tbody>
                {visibleChecks.map((check) => (
                  <tr key={`${check.method}-${check.dimension}-${check.band}`} className={check.passed ? "active-row" : undefined}>
                    <td>{checkLabel(check)}</td>
                    <td>{methodLabel(check.method)}</td>
                    <td>{check.august_settled}</td>
                    <td>{formatPct(check.august_roi_pct)}</td>
                    <td>{check.september_settled}</td>
                    <td>{formatPct(check.september_roi_pct)}</td>
                    <td>{check.passed ? "Regge" : "No"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>
    </div>
  );
}
