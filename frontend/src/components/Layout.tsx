import { NavLink, Outlet } from "react-router-dom";

const navItems = [
  { to: "/predictions", label: "Partite" },
  { to: "/betting-slips", label: "Consiglio schedina" },
  { to: "/betting-slip-model-stats", label: "Statistiche schedine" },
  { to: "/prediction-stats", label: "Statistiche previsioni" }
];

export function Layout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <h1>tennis_oracle</h1>
          <p>Previsioni e risultati tennis aggiornati ogni giorno.</p>
        </div>
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
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
