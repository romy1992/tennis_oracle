import { useState } from "react";

const ACTIVE_STATUSES = new Set(["pending", "running"]);

type LongRunningJobProgressProps = {
  status: string;
  currentPhase?: string | null;
  progressPct?: number | null;
  progressCurrent?: number | null;
  progressTotal?: number | null;
  onCancel?: () => void | Promise<void>;
};

export function isActiveJobStatus(status: string) {
  return ACTIVE_STATUSES.has(status);
}

export function LongRunningJobProgress({
  status,
  currentPhase,
  progressPct,
  progressCurrent,
  progressTotal,
  onCancel
}: LongRunningJobProgressProps) {
  const [cancelling, setCancelling] = useState(false);

  if (!isActiveJobStatus(status)) {
    return null;
  }

  const pct =
    progressPct !== null && progressPct !== undefined
      ? Math.max(0, Math.min(100, Math.round(progressPct)))
      : null;
  const hasCounter =
    progressCurrent !== null &&
    progressCurrent !== undefined &&
    progressTotal !== null &&
    progressTotal !== undefined &&
    progressTotal > 0;

  async function handleCancel() {
    if (!onCancel || cancelling) return;
    try {
      setCancelling(true);
      await onCancel();
    } finally {
      setCancelling(false);
    }
  }

  return (
    <article className="panel long-running-job-panel">
      <div className="long-running-job-header">
        <div>
          <h3>Esecuzione in corso</h3>
          {currentPhase ? <p className="muted small">{currentPhase}</p> : null}
        </div>
        {onCancel ? (
          <button
            type="button"
            className="action-button secondary"
            disabled={cancelling}
            onClick={() => void handleCancel()}
          >
            {cancelling ? "Annullamento..." : "Annulla"}
          </button>
        ) : null}
      </div>
      <div
        className="progress-bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct ?? 0}
        aria-label="Avanzamento"
      >
        <div className="progress-bar-fill" style={{ width: `${pct ?? 0}%` }} />
      </div>
      <div className="long-running-job-meta">
        {pct !== null ? <span>{pct}%</span> : null}
        {hasCounter ? (
          <span>
            {progressCurrent} / {progressTotal}
          </span>
        ) : null}
      </div>
    </article>
  );
}
