import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { GlobalUpdateControls } from "./GlobalUpdateControls";

type NavLeaf = { to: string; label: string };
type NavGroup = { label: string; items: NavLeaf[] };
type NavEntry = NavLeaf | NavGroup;

function isGroup(entry: NavEntry): entry is NavGroup {
  return "items" in entry;
}

const navSections: Array<{
  label?: string;
  items: NavEntry[];
}> = [
  {
    items: [
      { to: "/live-beta-dashboard", label: "Dashboard live" },
      { to: "/predictions", label: "Partite" },
      { to: "/betting-slips", label: "Consiglio schedina" }
    ]
  },
  {
    label: "LIVE",
    items: [
      { to: "/published-predictions", label: "Storico pubblicazioni" },
      { to: "/published-live-stats", label: "Statistiche live" },
      { to: "/subscriptions-dashboard", label: "Dashboard abbonamenti" },
      { to: "/global-update-report", label: "Report aggiornamento" },
      {
        label: "Telegram",
        items: [
          { to: "/telegram-bot", label: "Bot Telegram" },
          { to: "/telegram-users", label: "Utenti beta Telegram" },
          { to: "/telegram-feedback", label: "Feedback Telegram" },
          { to: "/weekly-beta-report", label: "Report settimanale beta" }
        ]
      }
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

function NavGroupItem({ group, currentPath }: { group: NavGroup; currentPath: string }) {
  const hasActiveChild = group.items.some((item) => currentPath.startsWith(item.to));
  const [open, setOpen] = useState(hasActiveChild);

  useEffect(() => {
    if (hasActiveChild) {
      setOpen(true);
    }
  }, [hasActiveChild]);

  return (
    <div className="nav-group">
      <button
        type="button"
        className={`nav-group-toggle${hasActiveChild ? " active-parent" : ""}`}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span>{group.label}</span>
        <span className="nav-group-caret" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open ? (
        <div className="nav-group-items">
          {group.items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? "active" : undefined)}
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function Layout() {
  const { username, logout } = useAuth();
  const { pathname } = useLocation();

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
              {section.items.map((entry) =>
                isGroup(entry) ? (
                  <NavGroupItem key={entry.label} group={entry} currentPath={pathname} />
                ) : (
                  <NavLink
                    key={entry.to}
                    to={entry.to}
                    className={({ isActive }) => (isActive ? "active" : undefined)}
                  >
                    {entry.label}
                  </NavLink>
                )
              )}
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
