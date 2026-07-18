import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { apiClient } from "../services/apiClient";
import type { GlobalUpdateRunRead } from "../types/api";

type GlobalUpdateContextValue = {
  status: GlobalUpdateRunRead | null;
  isRunning: boolean;
  refreshStatus: () => Promise<GlobalUpdateRunRead | null>;
  triggerUpdate: (force?: boolean) => Promise<GlobalUpdateRunRead | null>;
  cancelUpdate: () => Promise<GlobalUpdateRunRead | null>;
  lastCompletedAt: string | null;
  lastOrigin: string | null;
};

const GlobalUpdateContext = createContext<GlobalUpdateContextValue | null>(null);

const RUNNING = new Set(["pending", "running"]);

export function GlobalUpdateProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<GlobalUpdateRunRead | null>(null);

  const refreshStatus = useCallback(async () => {
    const next = await apiClient.getGlobalUpdateStatus();
    //region agent log
    fetch("http://127.0.0.1:7516/ingest/51ba4cbe-10fb-4c0d-94ec-cc65bebcec2f", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "ce07cd" },
      body: JSON.stringify({
        sessionId: "ce07cd",
        hypothesisId: "H5",
        location: "useGlobalUpdate.tsx:refreshStatus",
        message: "polled global update status",
        data: {
          status: next?.status ?? null,
          progress_pct: next?.progress_pct ?? null,
          current_phase: next?.current_phase ?? null,
          run_id: next?.id ?? null
        },
        timestamp: Date.now()
      })
    }).catch(() => {});
    //endregion
    setStatus(next);
    return next;
  }, []);

  const triggerUpdate = useCallback(
    async (force = false) => {
      await apiClient.startGlobalUpdate({ force });
      const next = await refreshStatus();
      return next;
    },
    [refreshStatus]
  );

  const cancelUpdate = useCallback(async () => {
    if (!status?.id) {
      return null;
    }
    await apiClient.cancelGlobalUpdate(status.id);
    const next = await refreshStatus();
    return next;
  }, [status?.id, refreshStatus]);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    if (!status || !RUNNING.has(status.status)) {
      return;
    }
    const timer = window.setInterval(() => {
      void refreshStatus();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [status, refreshStatus]);

  const isRunning = status ? RUNNING.has(status.status) : false;
  const lastCompletedAt =
    status && !RUNNING.has(status.status) ? status.finished_at ?? null : null;
  const lastOrigin = status?.origin ?? null;

  const value = useMemo(
    () => ({
      status,
      isRunning,
      refreshStatus,
      triggerUpdate,
      cancelUpdate,
      lastCompletedAt,
      lastOrigin
    }),
    [status, isRunning, refreshStatus, triggerUpdate, cancelUpdate, lastCompletedAt, lastOrigin]
  );

  return (
    <GlobalUpdateContext.Provider value={value}>{children}</GlobalUpdateContext.Provider>
  );
}

export function useGlobalUpdate() {
  const context = useContext(GlobalUpdateContext);
  if (!context) {
    throw new Error("useGlobalUpdate must be used within GlobalUpdateProvider");
  }
  return context;
}
