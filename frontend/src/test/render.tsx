import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { appRoutes } from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { storeSession } from "../auth/session";
import { GlobalUpdateProvider } from "../hooks/useGlobalUpdate";
import { futureExpiresAt } from "./fixtures";

export function seedAdminSession(token = "test-token") {
  storeSession(token, futureExpiresAt());
}

type RenderAppOptions = {
  initialEntries?: string[];
  authenticated?: boolean;
};

export function renderApp({
  initialEntries = ["/predictions"],
  authenticated = true
}: RenderAppOptions = {}) {
  if (authenticated) {
    seedAdminSession();
  }
  const router = createMemoryRouter(appRoutes, { initialEntries });
  return {
    router,
    ...render(
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    )
  };
}

function Providers({ children }: { children: ReactNode }) {
  return (
    <GlobalUpdateProvider>
      <RouterProvider
        router={createMemoryRouter([{ path: "*", element: <>{children}</> }], {
          initialEntries: ["/"]
        })}
      />
    </GlobalUpdateProvider>
  );
}

export function renderWithProviders(
  ui: ReactElement,
  options?: Omit<RenderOptions, "wrapper">
) {
  return render(ui, { wrapper: Providers, ...options });
}

export function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
