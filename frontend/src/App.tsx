import {
  Navigate,
  createBrowserRouter,
  RouterProvider,
  type RouteObject
} from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { GlobalUpdateProvider } from "./hooks/useGlobalUpdate";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { BettingSlipModelStatsPage } from "./pages/BettingSlipModelStatsPage";
import { BettingSlipsPage } from "./pages/BettingSlipsPage";
import { GlobalUpdateReportPage } from "./pages/GlobalUpdateReportPage";
import { LoginPage } from "./pages/LoginPage";
import { PredictionStatsPage } from "./pages/PredictionStatsPage";
import { PredictionsPage } from "./pages/PredictionsPage";
import { TelegramBotPage } from "./pages/TelegramBotPage";

function AuthenticatedShell() {
  return (
    <GlobalUpdateProvider>
      <Layout />
    </GlobalUpdateProvider>
  );
}

/** Shared route tree for browser runtime and memory-router tests. */
export const appRoutes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: <ProtectedRoute />,
    children: [
      {
        element: <AuthenticatedShell />,
        children: [
          { index: true, element: <Navigate to="/predictions" replace /> },
          { path: "predictions", element: <PredictionsPage /> },
          { path: "prediction-stats", element: <PredictionStatsPage /> },
          { path: "betting-slips", element: <BettingSlipsPage /> },
          { path: "betting-slip-model-stats", element: <BettingSlipModelStatsPage /> },
          { path: "global-update-report", element: <GlobalUpdateReportPage /> },
          { path: "telegram-bot", element: <TelegramBotPage /> }
        ]
      }
    ]
  }
];

export function App() {
  return (
    <AuthProvider>
      <RouterProvider router={createBrowserRouter(appRoutes)} />
    </AuthProvider>
  );
}
