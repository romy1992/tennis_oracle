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
import { LiveBetaDashboardPage } from "./pages/LiveBetaDashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { PredictionStatsPage } from "./pages/PredictionStatsPage";
import { PredictionsPage } from "./pages/PredictionsPage";
import { PublishedLiveStatsPage } from "./pages/PublishedLiveStatsPage";
import { PublishedPredictionsPage } from "./pages/PublishedPredictionsPage";
import { TelegramBotPage } from "./pages/TelegramBotPage";
import { TelegramFeedbackPage } from "./pages/TelegramFeedbackPage";
import { TelegramUsersPage } from "./pages/TelegramUsersPage";
import { WeeklyBetaReportPage } from "./pages/WeeklyBetaReportPage";
import { WalkForwardPage } from "./pages/WalkForwardPage";
import { CalibrationPage } from "./pages/CalibrationPage";
import { PublicModelRegistryPage } from "./pages/PublicModelRegistryPage";
import { ProbabilityBandsPage } from "./pages/ProbabilityBandsPage";
import { SegmentRoiPage } from "./pages/SegmentRoiPage";
import { SubscriptionsDashboardPage } from "./pages/SubscriptionsDashboardPage";

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
          { path: "live-beta-dashboard", element: <LiveBetaDashboardPage /> },
          { path: "predictions", element: <PredictionsPage /> },
          { path: "prediction-stats", element: <PredictionStatsPage /> },
          { path: "betting-slips", element: <BettingSlipsPage /> },
          { path: "betting-slip-model-stats", element: <BettingSlipModelStatsPage /> },
          { path: "global-update-report", element: <GlobalUpdateReportPage /> },
          { path: "published-predictions", element: <PublishedPredictionsPage /> },
          { path: "public-model-registry", element: <PublicModelRegistryPage /> },
          { path: "published-live-stats", element: <PublishedLiveStatsPage /> },
          { path: "telegram-bot", element: <TelegramBotPage /> },
          { path: "telegram-users", element: <TelegramUsersPage /> },
          { path: "telegram-feedback", element: <TelegramFeedbackPage /> },
          { path: "weekly-beta-report", element: <WeeklyBetaReportPage /> },
          { path: "walk-forward", element: <WalkForwardPage /> },
          { path: "calibration", element: <CalibrationPage /> },
          { path: "probability-bands", element: <ProbabilityBandsPage /> },
          { path: "segment-roi", element: <SegmentRoiPage /> },
          { path: "subscriptions-dashboard", element: <SubscriptionsDashboardPage /> }
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
