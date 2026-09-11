import { useEffect, useMemo, useState } from "react";

import { apiClient } from "../services/apiClient";
import type { ScheduledJob } from "../types/api";

const WEEKDAY_OPTIONS = [
  { value: 0, label: "Lunedì" },
  { value: 1, label: "Martedì" },
  { value: 2, label: "Mercoledì" },
  { value: 3, label: "Giovedì" },
  { value: 4, label: "Venerdì" },
  { value: 5, label: "Sabato" },
  { value: 6, label: "Domenica" }
] as const;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Operazione non riuscita.";
}

function formatDateTime(value: string | null): string {
  if (!value) return "Mai eseguito";
  const parsed = new Date(value.endsWith("Z") || value.includes("+") ? value : `${value}Z`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("it-IT", {
    dateStyle: "short",
    timeStyle: "short"
  });
}

function intervalParts(seconds: number | null): { value: string; unit: "minutes" | "seconds" } {
  const safe = Math.max(1, seconds ?? 60);
  if (safe >= 60 && safe % 60 === 0) {
    return { value: String(safe / 60), unit: "minutes" };
  }
  return { value: String(safe), unit: "seconds" };
}

function toIntervalSeconds(value: string, unit: "minutes" | "seconds"): number | null {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return unit === "minutes" ? parsed * 60 : parsed;
}

function lastRunLabel(job: ScheduledJob): string {
  const when = formatDateTime(job.last_run_at);
  if (!job.last_run_status) return when;
  return `${when} · ${job.last_run_status}`;
}

function JobScheduleControl({
  job,
  disabled,
  onChangeTime,
  onChangeWeekday,
  onChangeInterval
}: {
  job: ScheduledJob;
  disabled: boolean;
  onChangeTime: (clockTime: string) => void;
  onChangeWeekday: (weekday: number) => void;
  onChangeInterval: (intervalSeconds: number) => void;
}) {
  const initial = useMemo(() => intervalParts(job.interval_seconds), [job.interval_seconds]);
  const [intervalValue, setIntervalValue] = useState(initial.value);
  const [intervalUnit, setIntervalUnit] = useState<"minutes" | "seconds">(initial.unit);

  useEffect(() => {
    const next = intervalParts(job.interval_seconds);
    setIntervalValue(next.value);
    setIntervalUnit(next.unit);
  }, [job.interval_seconds, job.job_key]);

  const commitInterval = (rawValue: string, unit: "minutes" | "seconds") => {
    const seconds = toIntervalSeconds(rawValue, unit);
    if (seconds == null || seconds === job.interval_seconds) return;
    onChangeInterval(seconds);
  };

  if (job.schedule_kind === "interval") {
    return (
      <div className="settings-job-schedule">
        <input
          aria-label={`Intervallo ${job.label}`}
          className="settings-job-interval"
          disabled={disabled}
          inputMode="numeric"
          min={1}
          type="number"
          value={intervalValue}
          onChange={(event) => setIntervalValue(event.target.value)}
          onBlur={() => commitInterval(intervalValue, intervalUnit)}
        />
        <select
          aria-label={`Unità intervallo ${job.label}`}
          className="settings-job-unit"
          disabled={disabled}
          value={intervalUnit}
          onChange={(event) => {
            const unit = event.target.value === "minutes" ? "minutes" : "seconds";
            setIntervalUnit(unit);
            commitInterval(intervalValue, unit);
          }}
        >
          <option value="minutes">minuti</option>
          <option value="seconds">secondi</option>
        </select>
      </div>
    );
  }

  return (
    <div className="settings-job-schedule">
      {job.schedule_kind === "weekly_clock" ? (
        <select
          aria-label={`Giorno ${job.label}`}
          className="settings-job-weekday"
          disabled={disabled}
          value={job.weekday ?? 0}
          onChange={(event) => onChangeWeekday(Number(event.target.value))}
        >
          {WEEKDAY_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : null}
      <input
        aria-label={`Orario ${job.label}`}
        className="settings-job-time"
        disabled={disabled}
        type="time"
        value={job.clock_time ?? "08:00"}
        onChange={(event) => {
          if (event.target.value) onChangeTime(event.target.value);
        }}
      />
    </div>
  );
}

export function ScheduledJobsPanel() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [timezone, setTimezone] = useState("Europe/Rome");
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const loadJobs = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.getScheduledJobs();
      setJobs(response.items);
      setTimezone(response.timezone);
    } catch (loadError) {
      setError(errorMessage(loadError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadJobs();
  }, []);

  const patchJob = async (job: ScheduledJob, payload: {
    enabled?: boolean;
    clock_time?: string;
    weekday?: number;
    interval_seconds?: number;
  }) => {
    setBusyKey(job.job_key);
    setError(null);
    setMessage(null);
    try {
      const updated = await apiClient.updateScheduledJob(job.job_key, payload);
      setJobs((current) =>
        current.map((item) => (item.job_key === updated.job_key ? updated : item))
      );
      setMessage(`Salvato: ${updated.label}.`);
    } catch (patchError) {
      setError(errorMessage(patchError));
    } finally {
      setBusyKey(null);
    }
  };

  return (
    <section className="panel settings-jobs-panel">
      <div className="settings-jobs-header">
        <div>
          <span className="settings-eyebrow">Scheduler</span>
          <h3>Job automatici</h3>
          <p className="note">
            Attiva o disattiva i job e cambiane orario o intervallo. Le modifiche
            valgono dal prossimo ciclo, senza riavvio. Fuso: {timezone}.
          </p>
        </div>
        <button
          type="button"
          className="action-button"
          onClick={() => void loadJobs()}
          disabled={loading || busyKey !== null}
        >
          Aggiorna
        </button>
      </div>

      {loading ? (
        <p className="note">Caricamento job automatici...</p>
      ) : null}

      {!loading && jobs.length > 0 ? (
        <ul className="settings-jobs-list">
          {jobs.map((job) => {
            const busy = busyKey === job.job_key;
            return (
              <li key={job.job_key} className={`settings-job-row${job.enabled ? "" : " is-off"}`}>
                <div className="settings-job-copy">
                  <div className="settings-job-title-row">
                    <strong>{job.label}</strong>
                    {job.badge ? <span className="settings-job-badge">{job.badge}</span> : null}
                  </div>
                  <p>{job.description}</p>
                  <small>{lastRunLabel(job)}</small>
                </div>
                <JobScheduleControl
                  job={job}
                  disabled={busy}
                  onChangeTime={(clockTime) => void patchJob(job, { clock_time: clockTime })}
                  onChangeWeekday={(weekday) => void patchJob(job, { weekday })}
                  onChangeInterval={(intervalSeconds) =>
                    void patchJob(job, { interval_seconds: intervalSeconds })
                  }
                />
                <button
                  type="button"
                  role="switch"
                  aria-checked={job.enabled}
                  aria-label={`${job.enabled ? "Disattiva" : "Attiva"} ${job.label}`}
                  className={`settings-job-toggle${job.enabled ? " is-on" : ""}`}
                  disabled={busy}
                  onClick={() => void patchJob(job, { enabled: !job.enabled })}
                >
                  <span />
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}

      {message ? (
        <div className="settings-alert success" role="status">
          {message}
        </div>
      ) : null}
      {error ? (
        <div className="settings-alert error" role="alert">
          {error}
        </div>
      ) : null}
    </section>
  );
}
