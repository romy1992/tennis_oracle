import { NavLink, Outlet } from "react-router-dom";

const navItems = [
  { to: "/", label: "Dashboard" },
  { to: "/matches", label: "Partite" },
  { to: "/players", label: "Giocatori" },
  { to: "/tournaments", label: "Tornei" }
];

export function Layout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <h1>tennis_oracle</h1>
          <p>Dati tennis importati dal backend FastAPI.</p>
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
