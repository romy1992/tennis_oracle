import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError } from "../services/apiClient";
import type { ApiTennisProviderSettings } from "../types/api";
import { SettingsPage } from "./SettingsPage";


const apiMocks = vi.hoisted(() => ({
  getApiTennisSettings: vi.fn(),
  testApiTennisConnection: vi.fn(),
  updateApiTennisKey: vi.fn()
}));

vi.mock("../services/apiClient", async () => {
  const actual = await vi.importActual<typeof import("../services/apiClient")>(
    "../services/apiClient"
  );
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      ...apiMocks
    }
  };
});

const environmentSettings: ApiTennisProviderSettings = {
  provider: "api-tennis",
  environment: "local",
  configured: true,
  usable: true,
  source: "environment",
  fingerprint: "sha256:0123456789ab",
  storage_ready: true,
  database_override_present: false,
  base_url: "https://api.example.test/tennis/",
  timeout_seconds: 30,
  updated_at: null,
  updated_by: null,
  warning: null
};

const databaseSettings: ApiTennisProviderSettings = {
  ...environmentSettings,
  source: "database",
  database_override_present: true,
  fingerprint: "sha256:fedcba987654",
  updated_at: "2026-09-02T10:30:00",
  updated_by: "admin"
};

describe("SettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getApiTennisSettings.mockResolvedValue(environmentSettings);
    apiMocks.testApiTennisConnection.mockResolvedValue({
      ok: true,
      message: "Connessione API-Tennis verificata correttamente."
    });
    apiMocks.updateApiTennisKey.mockResolvedValue({
      message: "Nuova chiave API-Tennis salvata e attivata.",
      verified: true,
      settings: databaseSettings
    });
  });

  it("shows provider status without rendering secret material", async () => {
    render(<SettingsPage />);

    expect(await screen.findByRole("heading", { name: "Impostazioni" })).toBeInTheDocument();
    expect(screen.getByText("Variabile d'ambiente")).toBeInTheDocument();
    expect(screen.getByText("sha256:0123456789ab")).toBeInTheDocument();
    expect(screen.getByLabelText("Nuova chiave API")).toHaveAttribute("type", "password");
    expect(screen.queryByText("real-provider-secret")).not.toBeInTheDocument();
  });

  it("tests a candidate key without saving it", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.type(await screen.findByLabelText("Nuova chiave API"), "candidate-key");
    await user.click(screen.getByRole("button", { name: "Verifica nuova chiave" }));

    expect(apiMocks.testApiTennisConnection).toHaveBeenCalledWith({
      api_key: "candidate-key"
    });
    expect(
      await screen.findByText("Connessione API-Tennis verificata correttamente.")
    ).toBeInTheDocument();
    expect(apiMocks.updateApiTennisKey).not.toHaveBeenCalled();
  });

  it("requires confirmation then verifies and activates the replacement", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.type(await screen.findByLabelText("Nuova chiave API"), "replacement-key");
    await user.type(screen.getByLabelText("Password amministratore"), "admin-password");
    await user.click(screen.getByRole("button", { name: "Salva e attiva" }));

    expect(
      screen.getByRole("heading", { name: "Sostituire la chiave API-Tennis?" })
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Verifica e attiva" }));

    expect(apiMocks.updateApiTennisKey).toHaveBeenCalledWith({
      api_key: "replacement-key",
      admin_password: "admin-password",
      verify_before_save: true
    });
    expect(
      await screen.findByText("Nuova chiave API-Tennis salvata e attivata.")
    ).toBeInTheDocument();
    expect(screen.getByText("Override cifrato nel database")).toBeInTheDocument();
    expect(screen.getByLabelText("Nuova chiave API")).toHaveValue("");
  });

  it("offers an explicit force flow only after provider verification fails", async () => {
    const user = userEvent.setup();
    apiMocks.updateApiTennisKey
      .mockRejectedValueOnce(new ApiError("Verifica provider fallita", 422))
      .mockResolvedValueOnce({
        message: "Nuova chiave API-Tennis salvata e attivata.",
        verified: false,
        settings: databaseSettings
      });
    render(<SettingsPage />);

    await user.type(await screen.findByLabelText("Nuova chiave API"), "unverified-key");
    await user.type(screen.getByLabelText("Password amministratore"), "admin-password");
    await user.click(screen.getByRole("button", { name: "Salva e attiva" }));
    await user.click(screen.getByRole("button", { name: "Verifica e attiva" }));

    expect(await screen.findByText("Verifica provider fallita")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Salva senza verifica" }));
    expect(
      screen.getByRole("heading", { name: "Attivare una chiave non verificata?" })
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Forza" }));

    expect(apiMocks.updateApiTennisKey).toHaveBeenLastCalledWith({
      api_key: "unverified-key",
      admin_password: "admin-password",
      verify_before_save: false
    });
  });

  it("explains why save is disabled when encrypted storage is not configured", async () => {
    apiMocks.getApiTennisSettings.mockResolvedValue({
      ...environmentSettings,
      storage_ready: false
    });
    render(<SettingsPage />);

    expect(
      await screen.findByText(/RUNTIME_SECRETS_MASTER_KEY/)
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Salva e attiva" })).toBeDisabled();
  });
});
