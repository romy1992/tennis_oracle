import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError } from "../services/apiClient";
import { scheduledJobsList } from "../test/fixtures";
import type { ApiTennisProviderSettings } from "../types/api";
import { SettingsPage } from "./SettingsPage";

const apiMocks = vi.hoisted(() => ({
  getApiTennisSettings: vi.fn(),
  testApiTennisConnection: vi.fn(),
  updateApiTennisKey: vi.fn(),
  getScheduledJobs: vi.fn(),
  updateScheduledJob: vi.fn()
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
    apiMocks.getScheduledJobs.mockResolvedValue(scheduledJobsList);
    apiMocks.updateScheduledJob.mockImplementation(async (jobKey: string, payload) => {
      const current = scheduledJobsList.items.find((item) => item.job_key === jobKey);
      return {
        ...(current || scheduledJobsList.items[0]),
        ...payload,
        job_key: jobKey,
        source: "database" as const,
        updated_at: "2026-09-11T08:00:00Z",
        updated_by: "admin"
      };
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
    expect(screen.getByText("Override nel database")).toBeInTheDocument();
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

  it("does not require an extra storage key to save", async () => {
    apiMocks.getApiTennisSettings.mockResolvedValue({
      ...environmentSettings,
      storage_ready: false
    });
    render(<SettingsPage />);

    expect(await screen.findByRole("heading", { name: "Impostazioni" })).toBeInTheDocument();
    expect(screen.queryByText(/RUNTIME_SECRETS_MASTER_KEY/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Salva e attiva" })).toBeEnabled();
  });

  it("lists scheduler jobs and toggles them without a restart", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    expect(await screen.findByRole("heading", { name: "Job automatici" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Disattiva Aggiorna tutto" })).toBeInTheDocument();
    expect(screen.getByLabelText("Orario Aggiorna tutto")).toHaveValue("08:00");
    expect(screen.getByLabelText("Intervallo Polling live schedine")).toHaveValue(3);

    await user.click(screen.getByRole("switch", { name: "Attiva Polling live schedine" }));

    expect(apiMocks.updateScheduledJob).toHaveBeenCalledWith("betting_slip_live_poll", {
      enabled: true
    });
    expect(await screen.findByText("Salvato: Polling live schedine.")).toBeInTheDocument();
  });

  it("saves a new clock time for a daily job", async () => {
    render(<SettingsPage />);

    const timeInput = await screen.findByLabelText("Orario Aggiorna tutto");
    fireEvent.change(timeInput, { target: { value: "07:15" } });

    expect(apiMocks.updateScheduledJob).toHaveBeenCalledWith("daily_global_update", {
      clock_time: "07:15"
    });
  });
});
