import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { apiClient } from "../services/apiClient";
import type { GlobalUpdateRunRead } from "../types/api";

type GlobalUpdateContextValue = {
  status: GlobalUpdateRunRead | null;
  isRunning: boolean;
  refreshStatus: () => Promise<GlobalUpdateRunRead | null>;
  triggerUpdate: (force?: boolean, versions?: string[]) => Promise<GlobalUpdateRunRead | null>;
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
    setStatus(next);
    return next;
  }, []);

  const triggerUpdate = useCallback(
    async (force = false, versions?: string[]) => {
      await apiClient.startGlobalUpdate({ force, versions });
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
