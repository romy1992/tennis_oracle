import type { MLModelName, MLModelVersion } from "../types/api";

const VERSION_STORAGE_KEY = "tennis_oracle_selected_model_version";
const NAME_STORAGE_KEY = "tennis_oracle_selected_model_name";

export const MODEL_VERSIONS: Array<{ value: MLModelVersion; label: string }> = [
  { value: "v1", label: "v1" },
  { value: "v2", label: "v2" },
  { value: "v3", label: "v3 odds-aware" },
  { value: "v4", label: "v4 ensemble (voting)" }
];

export const MODEL_NAMES: Array<{ value: MLModelName; label: string }> = [
  { value: "logistic_regression", label: "Logistic regression" },
  { value: "random_forest", label: "Random forest" },
  { value: "voting_ensemble", label: "Voting ensemble (v4)" }
];

export const DEFAULT_MODEL_VERSION: MLModelVersion = "v4";
const FALLBACK_MODEL_NAME: MLModelName = "voting_ensemble";

function isMLModelVersion(value: string | null | undefined): value is MLModelVersion {
  return value === "v1" || value === "v2" || value === "v3" || value === "v4";
}

export function readStoredModelVersion(): MLModelVersion {
  const value = window.localStorage.getItem(VERSION_STORAGE_KEY);
  if (isMLModelVersion(value)) {
    return value;
  }
  return DEFAULT_MODEL_VERSION;
}

export function writeStoredModelVersion(value: MLModelVersion) {
  window.localStorage.setItem(VERSION_STORAGE_KEY, value);
}

/** Prefer stored/default (v3) when present in the catalog; otherwise first available. */
export function resolvePreferredModelVersion(
  available: Array<{ version: string }>,
  preferred: MLModelVersion = readStoredModelVersion()
): MLModelVersion {
  const versions = available.map((entry) => entry.version);
  if (versions.includes(preferred) && isMLModelVersion(preferred)) {
    return preferred;
  }
  if (versions.includes(DEFAULT_MODEL_VERSION)) {
    return DEFAULT_MODEL_VERSION;
  }
  const first = versions[0];
  if (isMLModelVersion(first)) {
    return first;
  }
  return DEFAULT_MODEL_VERSION;
}

export function readStoredModelName(): MLModelName {
  const value = window.localStorage.getItem(NAME_STORAGE_KEY);
  if (value === "logistic_regression" || value === "random_forest" || value === "voting_ensemble") {
    return value;
  }
  return FALLBACK_MODEL_NAME;
}

export function writeStoredModelName(value: MLModelName) {
  window.localStorage.setItem(NAME_STORAGE_KEY, value);
}
