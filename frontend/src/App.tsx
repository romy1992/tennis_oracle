import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { MatchesPage } from "./pages/MatchesPage";
import { PlayerDetailPage } from "./pages/PlayerDetailPage";
import { PlayersPage } from "./pages/PlayersPage";
import { TournamentsPage } from "./pages/TournamentsPage";

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: "matches", element: <MatchesPage /> },
      { path: "players", element: <PlayersPage /> },
      { path: "players/:playerId", element: <PlayerDetailPage /> },
      { path: "tournaments", element: <TournamentsPage /> }
    ]
  }
]);

export function App() {
  return <RouterProvider router={router} />;
}
