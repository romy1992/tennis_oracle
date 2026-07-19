import type { SingleMatchValueDecision } from "../types/api";

export function classifySingleBetValue(
  marketOdds: number,
  voidOdds: number,
  minEdgePercent: number
): SingleMatchValueDecision {
  const playThreshold = voidOdds * (1 + minEdgePercent / 100);
  if (marketOdds >= playThreshold) return "PLAY";
  if (marketOdds < voidOdds) return "NO BET";
  return "BORDERLINE";
}
