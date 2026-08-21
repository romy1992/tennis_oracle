import type { LiveScore } from "../types/api";
import { formatFinalScore, formatLiveScore } from "../utils/liveScore";

export type LiveMatchPanelItem = {
  eventKey: number;
  player1: string | null;
  player2: string | null;
  tournament: string | null;
  score: string | null;
  status: string | null;
  detail?: string | null;
};

export function LiveMatchesPanel({ items }: { items: LiveMatchPanelItem[] }) {
  if (!items.length) return null;

  return (
    <article className="panel live-now-panel" aria-label="Partite in diretta">
      <div className="live-now-header">
        <div>
          <span className="live-now-badge">
            <span aria-hidden="true" /> LIVE
          </span>
          <h3>In diretta</h3>
        </div>
        <small>Aggiornamento automatico ogni minuto</small>
      </div>
      <div className="live-now-grid">
        {items.map((item) => (
          <section className="live-now-card" key={item.eventKey}>
            <small>{item.tournament ?? "Torneo non disponibile"}</small>
            <strong>
              {item.player1 ?? "?"} <span>vs</span> {item.player2 ?? "?"}
            </strong>
            <div className="live-score-line">
              {item.score ?? item.status ?? "Punteggio in aggiornamento"}
            </div>
            {item.detail ? <small className="live-now-detail">{item.detail}</small> : null}
          </section>
        ))}
      </div>
    </article>
  );
}

export function MatchScoreSnapshot({
  live,
  completed,
  score,
  outcomeLabel,
  winnerLabel
}: {
  live: boolean;
  completed: boolean;
  score: LiveScore | null | undefined;
  outcomeLabel?: string | null;
  winnerLabel?: string | null;
}) {
  if (live) {
    return (
      <small className="live-inline-score">
        <span className="live-inline-badge">LIVE</span>
        {formatLiveScore(score) ?? "Punteggio in aggiornamento"}
      </small>
    );
  }
  if (!completed) return null;

  const details = [formatFinalScore(score), winnerLabel, outcomeLabel].filter(Boolean);
  return (
    <small className="final-inline-score">
      <span className="final-inline-badge">FINALE</span>
      {details.join(" · ") || "Risultato acquisito"}
    </small>
  );
}
