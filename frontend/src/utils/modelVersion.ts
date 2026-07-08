import type { MLModelName, MLModelVersion } from "../types/api";

const VERSION_STORAGE_KEY = "tennis_oracle_selected_model_version";
const NAME_STORAGE_KEY = "tennis_oracle_selected_model_name";

export const MODEL_VERSIONS: Array<{ value: MLModelVersion; label: string }> = [
  { value: "v1", label: "v1" },
  { value: "v2", label: "v2" },
  { value: "v3", label: "v3 odds-aware" }
];

export const MODEL_NAMES: Array<{ value: MLModelName; label: string }> = [
  { value: "logistic_regression", label: "Logistic regression" },
  { value: "random_forest", label: "Random forest" }
];

const FALLBACK_MODEL_VERSION: MLModelVersion = "v3";
const FALLBACK_MODEL_NAME: MLModelName = "logistic_regression";

export function readStoredModelVersion(): MLModelVersion {
  const value = window.localStorage.getItem(VERSION_STORAGE_KEY);
  if (value === "v1" || value === "v2" || value === "v3") {
    return value;
  }
  return FALLBACK_MODEL_VERSION;
}

export function writeStoredModelVersion(value: MLModelVersion) {
  window.localStorage.setItem(VERSION_STORAGE_KEY, value);
}

export function readStoredModelName(): MLModelName {
  const value = window.localStorage.getItem(NAME_STORAGE_KEY);
  if (value === "logistic_regression" || value === "random_forest") {
    return value;
  }
  return FALLBACK_MODEL_NAME;
}

export function writeStoredModelName(value: MLModelName) {
  window.localStorage.setItem(NAME_STORAGE_KEY, value);
}
