/** Shared prediction-market catalog for UI (never expose raw match-winner v*). */

import type { LiveDashboardMarket } from "../types/api";
import { DEFAULT_MODEL_VERSION } from "./modelVersion";

export type MarketOption = {
  value: LiveDashboardMarket;
  label: string;
  description: string;
  /** Internal persistence key (MatchPrediction / PublishedPrediction.model_version). */
  internalVersion: string;
};

export const MARKET_OPTIONS: MarketOption[] = [
  {
    value: "match_winner",
    label: "Vincitore partita",
    description: "Pronostici sul vincitore finale e relativo sottoinsieme di PLAY ufficiali.",
    internalVersion: DEFAULT_MODEL_VERSION
  },
  {
    value: "first_set_winner",
    label: "Vincitore 1° set",
    description:
      "Pronostici sul vincitore del primo set, con PLAY ufficiali quando quota e valore sono validi.",
    internalVersion: "first_set_winner_v2"
  },
  {
    value: "over_under_games",
    label: "Over/Under games",
    description:
      "Pronostici sul totale giochi, con PLAY ufficiali quando quota e valore sono validi.",
    internalVersion: "over_under_games_v1"
  }
];

export const DEFAULT_LIVE_MARKET: LiveDashboardMarket = "match_winner";

const ARCHIVED_MATCH_WINNER_VERSIONS = new Set(["v1", "v2", "v3"]);

export function isArchivedMatchWinnerVersion(version: string | null | undefined): boolean {
  return Boolean(version && ARCHIVED_MATCH_WINNER_VERSIONS.has(version));
}

export function isActiveMatchWinnerVersion(version: string | null | undefined): boolean {
  return version === DEFAULT_MODEL_VERSION;
}

export function marketLabel(market: LiveDashboardMarket | string | null | undefined): string {
  return MARKET_OPTIONS.find((option) => option.value === market)?.label ?? market ?? "—";
}

export function marketDescription(market: LiveDashboardMarket): string {
  return MARKET_OPTIONS.find((option) => option.value === market)?.description ?? "";
}

export function internalVersionForMarket(market: LiveDashboardMarket): string {
  return (
    MARKET_OPTIONS.find((option) => option.value === market)?.internalVersion ??
    DEFAULT_MODEL_VERSION
  );
}

/** Map any internal model_version string to a UI market when possible. */
export function marketFromInternalVersion(
  version: string | null | undefined
): LiveDashboardMarket | null {
  if (!version) return null;
  const known = MARKET_OPTIONS.find((option) => option.internalVersion === version);
  if (known) return known.value;
  if (version === "v1" || version === "v2" || version === "v3" || version === "v4") {
    return "match_winner";
  }
  if (version.startsWith("first_set_winner")) return "first_set_winner";
  if (version.startsWith("over_under_games")) return "over_under_games";
  return null;
}

/**
 * Human label for any internal version / market key. Never surfaces raw
 * match-winner tags like ``v4`` (those map to "Vincitore partita").
 */
export function uiVersionOrMarketLabel(value: string | null | undefined): string {
  if (!value) return "—";
  const asMarket = MARKET_OPTIONS.find((option) => option.value === value);
  if (asMarket) return asMarket.label;
  if (isArchivedMatchWinnerVersion(value)) return "Vincitore partita (archivio)";
  const fromVersion = marketFromInternalVersion(value);
  if (fromVersion) return marketLabel(fromVersion);
  return value;
}

/** Format a comma-separated versions_requested string as market labels. */
export function formatVersionsRequestedAsMarkets(value: string | null | undefined): string {
  if (!value) return "—";
  const labels = value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => uiVersionOrMarketLabel(part));
  return Array.from(new Set(labels)).join(", ") || "—";
}
