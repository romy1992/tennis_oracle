import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { GlobalUpdateControls } from "./GlobalUpdateControls";

const navItems = [
  { to: "/predictions", label: "Partite" },
  { to: "/betting-slips", label: "Consiglio schedina" },
  { to: "/betting-slip-model-stats", label: "Statistiche schedine" },
  { to: "/prediction-stats", label: "Statistiche previsioni" },
  { to: "/global-update-report", label: "Report aggiornamento" },
  { to: "/telegram-bot", label: "Bot Telegram" }
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
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? "active" : undefined)}
            >
              {item.label}
            </NavLink>
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
