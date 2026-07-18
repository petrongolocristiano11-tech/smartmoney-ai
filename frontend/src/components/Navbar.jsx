import {
  useEffect,
  useState,
} from "react";
import { NavLink } from "react-router-dom";

import {
  getUnreadNotificationCount,
  subscribeNotificationCenter,
} from "../services/notificationCenter";


const NAVIGATION_ITEMS = [
  {
    label: "Dashboard",
    path: "/",
    end: true,
  },
  {
    label: "Paper Trading",
    path: "/paper-trading",
  },
  {
    label: "Autopilot",
    path: "/autopilot",
  },
  {
    label: "Copy Trading",
    path: "/live-trading",
    liveTrading: true,
  },
  {
    label: "Live Scanner",
    path: "/live",
  },
  {
    label: "Discovery",
    path: "/discovery",
  },
  {
    label: "Signals",
    path: "/signals",
  },
  {
    label: "Alerts",
    path: "/alerts",
  },
  {
    label: "Analytics",
    path: "/analytics",
  },
  {
    label: "Portfolio",
    path: "/portfolio",
  },
  {
    label: "Backtest",
    path: "/backtesting",
  },
  {
    label: "Notifications",
    path: "/notifications",
    notificationBadge: true,
  },
  {
    label: "Watchlist",
    path: "/watchlist",
  },
];


function formatUnreadCount(count) {
  return count > 99
    ? "99+"
    : count;
}


function DesktopNavLink({
  item,
  unreadNotifications,
}) {
  return (
    <NavLink
      to={item.path}
      end={item.end}
      className={({ isActive }) =>
        [
          "flex shrink-0 items-center gap-2",
          "rounded-lg px-3 py-2",
          "text-sm font-semibold transition",
          isActive
            ? item.liveTrading
              ? "bg-red-600 text-white"
              : "bg-blue-600 text-white"
            : item.liveTrading
              ? "text-red-300 hover:bg-red-950/60 hover:text-red-200"
              : "text-slate-300 hover:bg-slate-800 hover:text-white",
        ].join(" ")
      }
    >
      {item.liveTrading && (
        <span
          className="h-2 w-2 rounded-full bg-red-400"
          aria-hidden="true"
        />
      )}

      <span>{item.label}</span>

      {item.notificationBadge
        && unreadNotifications > 0 && (
          <span className="flex min-w-5 items-center justify-center rounded-full bg-red-600 px-1.5 py-0.5 text-xs font-bold text-white">
            {formatUnreadCount(
              unreadNotifications
            )}
          </span>
        )}
    </NavLink>
  );
}


function MobileNavLink({
  item,
  unreadNotifications,
  onNavigate,
}) {
  return (
    <NavLink
      to={item.path}
      end={item.end}
      onClick={onNavigate}
      className={({ isActive }) =>
        [
          "flex w-full items-center justify-between",
          "rounded-xl px-4 py-3",
          "font-semibold transition",
          isActive
            ? item.liveTrading
              ? "bg-red-600 text-white"
              : "bg-blue-600 text-white"
            : item.liveTrading
              ? "text-red-300 hover:bg-red-950/60 hover:text-red-200"
              : "text-slate-300 hover:bg-slate-800 hover:text-white",
        ].join(" ")
      }
    >
      <span className="flex items-center gap-2">
        {item.liveTrading && (
          <span
            className="h-2 w-2 rounded-full bg-red-400"
            aria-hidden="true"
          />
        )}

        <span>{item.label}</span>
      </span>

      {item.notificationBadge
        && unreadNotifications > 0 && (
          <span className="flex min-w-6 items-center justify-center rounded-full bg-red-600 px-2 py-1 text-xs font-bold text-white">
            {formatUnreadCount(
              unreadNotifications
            )}
          </span>
        )}
    </NavLink>
  );
}


function MenuIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className="h-6 w-6"
      aria-hidden="true"
    >
      <path
        d="M4 7H20M4 12H20M4 17H20"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}


function CloseIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className="h-6 w-6"
      aria-hidden="true"
    >
      <path
        d="M6 6L18 18M18 6L6 18"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}


function Navbar() {
  const [menuOpen, setMenuOpen] =
    useState(false);

  const [
    unreadNotifications,
    setUnreadNotifications,
  ] = useState(
    getUnreadNotificationCount
  );

  useEffect(() => {
    return subscribeNotificationCenter(
      () => {
        setUnreadNotifications(
          getUnreadNotificationCount()
        );
      }
    );
  }, []);


  useEffect(() => {
    if (!menuOpen) {
      return undefined;
    }

    const previousOverflow =
      document.body.style.overflow;

    function handleEscape(event) {
      if (event.key === "Escape") {
        setMenuOpen(false);
      }
    }

    document.body.style.overflow =
      "hidden";

    window.addEventListener(
      "keydown",
      handleEscape
    );

    return () => {
      document.body.style.overflow =
        previousOverflow;

      window.removeEventListener(
        "keydown",
        handleEscape
      );
    };
  }, [menuOpen]);

  return (
    <>
      <nav className="sticky top-0 z-50 border-b border-slate-700 bg-slate-950/95 backdrop-blur">
        <div className="mx-auto flex min-h-16 max-w-[1600px] items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <NavLink
            to="/"
            className="flex shrink-0 items-center gap-2 text-lg font-bold text-white"
          >
            <span aria-hidden="true">
              🚀
            </span>

            <span>SmartMoney AI</span>
          </NavLink>

          <div className="hidden items-center gap-1 2xl:flex">
            {NAVIGATION_ITEMS.map(
              (item) => (
                <DesktopNavLink
                  key={item.path}
                  item={item}
                  unreadNotifications={
                    unreadNotifications
                  }
                />
              )
            )}
          </div>

          <button
            type="button"
            onClick={() =>
              setMenuOpen(
                (current) => !current
              )
            }
            className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-slate-700 bg-slate-900 text-slate-200 transition hover:border-slate-600 hover:bg-slate-800 2xl:hidden"
            aria-label="Apri menu"
            aria-expanded={menuOpen}
            aria-controls="mobile-navigation"
          >
            <MenuIcon />

            {unreadNotifications > 0 && (
              <span className="absolute -right-1 -top-1 flex min-h-5 min-w-5 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
                {formatUnreadCount(
                  unreadNotifications
                )}
              </span>
            )}
          </button>
        </div>
      </nav>

      {menuOpen && (
        <div className="2xl:hidden">
          <button
            type="button"
            aria-label="Chiudi menu"
            onClick={() =>
              setMenuOpen(false)
            }
            className="fixed inset-0 z-[60] cursor-default bg-black/65 backdrop-blur-sm"
          />

          <aside
            id="mobile-navigation"
            className="fixed right-0 top-0 z-[70] flex h-dvh w-[min(88vw,380px)] flex-col border-l border-slate-700 bg-slate-950 shadow-2xl"
          >
            <header className="flex min-h-16 items-center justify-between border-b border-slate-700 px-5">
              <div className="flex items-center gap-2 font-bold text-white">
                <span aria-hidden="true">
                  🚀
                </span>

                <span>SmartMoney AI</span>
              </div>

              <button
                type="button"
                onClick={() =>
                  setMenuOpen(false)
                }
                className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-700 text-slate-300 transition hover:bg-slate-800 hover:text-white"
                aria-label="Chiudi menu"
              >
                <CloseIcon />
              </button>
            </header>

            <div className="flex-1 overflow-y-auto p-4">
              <p className="mb-3 px-4 text-xs font-bold uppercase tracking-wider text-slate-500">
                Navigazione
              </p>

              <div className="space-y-2">
                {NAVIGATION_ITEMS.map(
                  (item) => (
                    <MobileNavLink
                      key={item.path}
                      item={item}
                      unreadNotifications={
                        unreadNotifications
                      }
                      onNavigate={() =>
                        setMenuOpen(false)
                      }
                    />
                  )
                )}
              </div>
            </div>

            <footer className="border-t border-slate-700 p-5">
              <div className="rounded-xl bg-slate-900 p-4">
                <p className="text-sm font-semibold text-slate-200">
                  SmartMoney AI
                </p>

                <p className="mt-1 text-xs text-slate-500">
                  Wallet intelligence e copy-trading controllato
                </p>
              </div>
            </footer>
          </aside>
        </div>
      )}
    </>
  );
}


export default Navbar; 