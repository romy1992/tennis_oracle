import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { GlobalUpdateControls } from "./GlobalUpdateControls";

const navSections: Array<{
  label?: string;
  items: Array<{ to: string; label: string }>;
}> = [
  {
    items: [
      { to: "/live-beta-dashboard", label: "Dashboard beta live" },
      { to: "/predictions", label: "Partite" },
      { to: "/betting-slips", label: "Consiglio schedina" }
    ]
  },
  {
    label: "LIVE",
    items: [
      { to: "/published-predictions", label: "Storico pubblicazioni" },
      { to: "/public-model-registry", label: "Registro modello pubblico" },
      { to: "/published-live-stats", label: "Statistiche live" },
      { to: "/telegram-bot", label: "Bot Telegram" },
      { to: "/telegram-users", label: "Utenti beta Telegram" },
      { to: "/telegram-feedback", label: "Feedback Telegram" },
      { to: "/weekly-beta-report", label: "Report settimanale beta" },
      { to: "/global-update-report", label: "Report aggiornamento" }
    ]
  },
  {
    label: "BACKTEST / OPS",
    items: [
      { to: "/prediction-stats", label: "Statistiche previsioni" },
      { to: "/betting-slip-model-stats", label: "Statistiche schedine" },
      { to: "/walk-forward", label: "Walk-forward" },
      { to: "/calibration", label: "Calibrazione" },
      { to: "/probability-bands", label: "Fasce probabilità" },
      { to: "/segment-roi", label: "ROI per segmento" }
    ]
  }
];

export function Layout() {
  const { username, logout } = useAuth();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <h1>tennis_oracle</h1>
          <p>Previsioni e risultati tennis aggiornati ogni giorno.</p>
        </div>
        <GlobalUpdateControls />
        <nav>
          {navSections.map((section) => (
            <div key={section.label || "main"} className="nav-section">
              {section.label ? (
                <div className="nav-section-label">{section.label}</div>
              ) : null}
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) => (isActive ? "active" : undefined)}
                >
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-auth">
          {username ? <span className="sidebar-user">{username}</span> : null}
          <button type="button" className="action-button" onClick={() => void logout()}>
            Esci
          </button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
