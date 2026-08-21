import type { LiveScore } from "../types/api";

type LiveMatchLike = {
  event_live?: string | null;
  event_status?: string | null;
  is_completed?: boolean | null;
  match_lifecycle_status?: string | null;
  outcome?: string | null;
  pick_status?: string | null;
  live_score?: LiveScore | null;
};

const TERMINAL_OUTCOMES = new Set(["won", "lost", "void"]);
const TERMINAL_STATUSES = ["finished", "completed", "cancelled", "canceled", "abandoned"];

function formatSetScores(score: LiveScore | null | undefined): string | null {
  if (!score) return null;
  return (
    (score.sets ?? [])
      .filter((set) => set.score_first != null || set.score_second != null)
      .map((set) => `${set.score_first ?? "-"}-${set.score_second ?? "-"}`)
      .join("  ") || null
  );
}

export function formatLiveScore(score: LiveScore | null | undefined): string | null {
  if (!score) return null;
  const sets = formatSetScores(score);
  const currentGame = score.current_game?.trim();
  const game = currentGame && currentGame !== "-" ? `Game ${currentGame}` : null;
  return [sets || null, game].filter(Boolean).join(" · ") || null;
}

export function formatFinalScore(score: LiveScore | null | undefined): string | null {
  if (!score) return null;
  const rawFinal = score.final_result?.trim();
  const finalResult = rawFinal && !["-", "0 - 0", "0-0"].includes(rawFinal) ? rawFinal : null;
  const sets = formatSetScores(score);
  return [finalResult, sets].filter(Boolean).join(" · ") || null;
}

export function isLiveMatch(item: LiveMatchLike): boolean {
  if (item.is_completed) return false;
  if (TERMINAL_OUTCOMES.has(item.outcome ?? item.pick_status ?? "")) return false;

  const lifecycle = item.match_lifecycle_status?.trim().toLowerCase();
  if (lifecycle === "started" || lifecycle === "live") return true;

  const liveFlag = item.event_live?.trim().toLowerCase();
  if (["1", "true", "yes", "y", "live", "inprogress"].includes(liveFlag ?? "")) {
    return true;
  }

  const status = (item.event_status ?? item.live_score?.status ?? "").trim().toLowerCase();
  if (!status || TERMINAL_STATUSES.some((terminal) => status.includes(terminal))) {
    return false;
  }
  return Boolean(item.live_score) && !["not started", "scheduled"].includes(status);
}
