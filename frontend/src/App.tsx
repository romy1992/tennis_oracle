import { Navigate, createBrowserRouter, RouterProvider } from "react-router-dom";

import { Layout } from "./components/Layout";
import { BettingSlipsPage } from "./pages/BettingSlipsPage";
import { PredictionStatsPage } from "./pages/PredictionStatsPage";
import { PredictionsPage } from "./pages/PredictionsPage";

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/predictions" replace /> },
      { path: "predictions", element: <PredictionsPage /> },
      { path: "prediction-stats", element: <PredictionStatsPage /> },
      { path: "betting-slips", element: <BettingSlipsPage /> }
    ]
  }
]);

export function App() {
  return <RouterProvider router={router} />;
}
