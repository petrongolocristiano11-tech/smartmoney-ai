import { NavLink } from "react-router-dom";

function getLinkClasses({ isActive }) {
  return [
    "rounded-lg px-4 py-2 text-sm font-semibold transition",
    isActive
      ? "bg-blue-600 text-white"
      : "text-slate-300 hover:bg-slate-800 hover:text-white",
  ].join(" ");
}

function Navbar() {
  return (
    <nav className="sticky top-0 z-50 border-b border-slate-700 bg-slate-950/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-8">
        <NavLink
          to="/"
          className="flex shrink-0 items-center gap-2 text-lg font-bold text-white"
        >
          <span>🚀</span>
          <span>SmartMoney AI</span>
        </NavLink>

        <div className="flex items-center gap-2 overflow-x-auto">
          <NavLink to="/" end className={getLinkClasses}>
            Dashboard
          </NavLink>

          <NavLink to="/live" className={getLinkClasses}>
            Live
          </NavLink>

          <NavLink
            to="/discovery"
            className={getLinkClasses}
          >
            Discovery
          </NavLink>

          <NavLink
            to="/signals"
            className={getLinkClasses}
          >
            Signals
          </NavLink>

          <NavLink
            to="/alerts"
            className={getLinkClasses}
          >
            Alerts
          </NavLink>

          <NavLink
            to="/watchlist"
            className={getLinkClasses}
          >
            Watchlist
          </NavLink>
        </div>
      </div>
    </nav>
  );
}

export default Navbar; 