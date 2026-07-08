import type { MLModelName, MLModelVersion } from "../types/api";
import {
  MODEL_NAMES,
  MODEL_VERSIONS,
  writeStoredModelName,
  writeStoredModelVersion
} from "../utils/modelVersion";

type ModelControlsProps = {
  modelVersion: MLModelVersion;
  modelName: MLModelName;
  onModelVersionChange: (value: MLModelVersion) => void;
  onModelNameChange: (value: MLModelName) => void;
  disabled?: boolean;
};

export function ModelControls({
  modelVersion,
  modelName,
  onModelVersionChange,
  onModelNameChange,
  disabled = false
}: ModelControlsProps) {
  return (
    <>
      <label className="filters-grid" style={{ minWidth: 180 }}>
        <span>Versione modello</span>
        <select
          value={modelVersion}
          onChange={(event) => {
            const nextVersion = event.target.value as MLModelVersion;
            writeStoredModelVersion(nextVersion);
            onModelVersionChange(nextVersion);
          }}
          disabled={disabled}
        >
          {MODEL_VERSIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      <label className="filters-grid" style={{ minWidth: 220 }}>
        <span>Modello</span>
        <select
          value={modelName}
          onChange={(event) => {
            const nextName = event.target.value as MLModelName;
            writeStoredModelName(nextName);
            onModelNameChange(nextName);
          }}
          disabled={disabled}
        >
          {MODEL_NAMES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}
