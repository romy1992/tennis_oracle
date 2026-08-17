import type { MLModelName, MLModelVersion } from "../types/api";

const VERSION_STORAGE_KEY = "tennis_oracle_selected_model_version";
const NAME_STORAGE_KEY = "tennis_oracle_selected_model_name";

/**
 * Mercato "Vincitore partita": innescato da "Aggiorna tutto"/cron e unica
 * opzione selezionabile per nuove predizioni/aggiornamenti. La label NON
 * espone piu' la versione interna del modello (v1/v2/v3/v4 sono un dettaglio
 * implementativo di backend/versioning, mai mostrato all'utente): l'unico
 * concetto rilevante lato UI e' il MERCATO ("Vincitore partita").
 *
 * v1/v2/v3 sono ARCHIVIATE (non eliminate): restano nel backend (codice,
 * dataset, .pkl, dati storici già generati) per backtest/confronto, ma non
 * appaiono più qui. Deve restare allineato con
 * ``backend/src/app/ml/model_versioning.py::ACTIVE_MATCH_WINNER_VERSIONS``
 * (unica fonte di verità per l'orchestratore); questo array è la sua
 * proiezione lato FE per i selettori statici (checkbox "Aggiorna tutto",
 * ``ModelControls``). Le pagine che leggono il catalogo dinamico
 * (``getModelsVersionsResults`` → Partite / Statistiche previsioni /
 * Consiglio schedina) si allineano già da sole, nessuna modifica lì.
 */
export const MODEL_VERSIONS: Array<{ value: MLModelVersion; label: string }> = [
  { value: "v4", label: "Vincitore partita" }
];

export const MODEL_NAMES: Array<{ value: MLModelName; label: string }> = [
  { value: "logistic_regression", label: "Logistic regression" },
  { value: "random_forest", label: "Random forest" },
  { value: "voting_ensemble", label: "Ensemble (consigliato)" }
];

/**
 * Mercati "extra" (oltre al vincitore partita, sempre attivi insieme ad esso):
 * Vincitore 1° set, Over/Under Games. Pubblicati direttamente nel ledger
 * ``PublishedPrediction`` da ``generate_extra_market_predictions.py`` (vedi
 * backend), NON gestiti da ``GlobalUpdateControls``/``ModelControls``
 * (retraining/selezione modello ufficiale): per questo restano fuori da
 * ``MODEL_VERSIONS`` e vivono in una costante separata, usata sia dai filtri
 * "Versione modello" delle pagine di pubblicazione/statistiche sia dal
 * pannello informativo di "Aggiorna tutto" (``ACTIVE_MARKETS``). Le label non
 * espongono piu' il suffisso "(v1)": la versione del modello resta un
 * dettaglio interno.
 */
export const EXTRA_MARKET_MODEL_VERSIONS: Array<{ value: string; label: string }> = [
  { value: "first_set_winner_v2", label: "Vincitore 1° set" },
  { value: "over_under_games_v1", label: "Over/Under Games" }
];

/** Tutte le versioni selezionabili nei filtri di pubblicazione/statistiche:
 * modelli match-winner ufficiali + mercati extra. */
export const PUBLISHED_MODEL_VERSION_OPTIONS: Array<{ value: string; label: string }> = [
  ...MODEL_VERSIONS,
  ...EXTRA_MARKET_MODEL_VERSIONS
];

/** Tutti i mercati attivi coperti da "Aggiorna tutto" (sempre generati
 * insieme, nessuna selezione parziale possibile): usato dal pannello
 * informativo di ``GlobalUpdateControls`` per mostrare chiaramente che i 3
 * mercati (Vincitore partita, Vincitore 1° set, Over/Under Games) sono
 * SEMPRE coperti, non solo il match-winner. */
export const ACTIVE_MARKETS: Array<{ value: string; label: string }> = [
  ...MODEL_VERSIONS,
  ...EXTRA_MARKET_MODEL_VERSIONS
];

/** Etichetta leggibile per una versione modello/mercato (fallback: valore grezzo
 * se non riconosciuto). Usata per non mostrare mai "v4"/"over_under_games_v1"
 * grezzi nella UI (tab versione in Partite/Consiglio schedina, ecc.). */
export function modelVersionLabel(value: string): string {
  const found = PUBLISHED_MODEL_VERSION_OPTIONS.find((option) => option.value === value);
  if (found) return found.label;
  // Archived match-winner versions still map to the market name (never "v2").
  if (value === "v1" || value === "v2" || value === "v3" || value === "v4") {
    return "Vincitore partita";
  }
  if (value.startsWith("first_set_winner")) return "Vincitore 1° set";
  if (value.startsWith("over_under_games")) return "Over/Under Games";
  return value;
}

export const DEFAULT_MODEL_VERSION: MLModelVersion = "v4";
const FALLBACK_MODEL_NAME: MLModelName = "voting_ensemble";

function isMLModelVersion(value: string | null | undefined): value is MLModelVersion {
  return value === "v1" || value === "v2" || value === "v3" || value === "v4";
}

export { isMLModelVersion };

/** True only for versions still active (see MODEL_VERSIONS docstring). */
function isActiveModelVersion(value: string | null | undefined): value is MLModelVersion {
  return isMLModelVersion(value) && MODEL_VERSIONS.some((entry) => entry.value === value);
}

export function readStoredModelVersion(): MLModelVersion {
  const value = window.localStorage.getItem(VERSION_STORAGE_KEY);
  // Ignora preferenze salvate in passato su versioni ora archiviate (v1-v3):
  // altrimenti un <select> con solo v4 tra le opzioni riceverebbe un `value`
  // non presente tra le <option>, "de-selezionandosi" visivamente nel browser.
  if (isActiveModelVersion(value)) {
    return value;
  }
  return DEFAULT_MODEL_VERSION;
}

export function writeStoredModelVersion(value: MLModelVersion) {
  window.localStorage.setItem(VERSION_STORAGE_KEY, value);
}

/** Prefer stored/default (v4) when present in the catalog; otherwise first available. */
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
