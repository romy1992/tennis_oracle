import { Navigate, createBrowserRouter, RouterProvider } from "react-router-dom";

import { GlobalUpdateProvider } from "./hooks/useGlobalUpdate";
import { Layout } from "./components/Layout";
import { BettingSlipModelStatsPage } from "./pages/BettingSlipModelStatsPage";
import { BettingSlipsPage } from "./pages/BettingSlipsPage";
import { GlobalUpdateReportPage } from "./pages/GlobalUpdateReportPage";
import { PredictionStatsPage } from "./pages/PredictionStatsPage";
import { PredictionsPage } from "./pages/PredictionsPage";
import { TelegramBotPage } from "./pages/TelegramBotPage";

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
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
]);

export function App() {
  return (
    <GlobalUpdateProvider>
      <RouterProvider router={router} />
    </GlobalUpdateProvider>
  );
}
