import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link } from "react-router-dom";

const API_URL = "http://127.0.0.1:8000";
const LIVE_STREAM_URL =
  `${API_URL}/live/stream?interval_seconds=2&min_alert_score=50`;
const LIVE_STATUS_URL = `${API_URL}/live/status`;
const MAX_EVENTS = 200;

function shortenAddress(address, start = 8, end = 6) {
  if (!address) {
    return "-";
  }

  if (address.length <= start + end + 3) {
    return address;
  }

  return `${address.slice(0, start)}...${address.slice(-end)}`;
}

function formatNumber(value, digits = 4) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "0";
  }

  return number.toLocaleString("it-IT", {
    maximumFractionDigits: digits,
  });
}

function formatTimestamp(timestamp) {
  if (!timestamp) {
    return "-";
  }

  const date = new Date(timestamp);

  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }

  return date.toLocaleString("it-IT");
}

function getEventKey(event) {
  if (event.event_type === "TRADE") {
    return `trade-${event.id}`;
  }

  if (event.event_type === "WALLET") {
    return `wallet-${event.id}`;
  }

  return `alert-${event.id}`;
}

function normalizeTrade(trade) {
  return {
    ...trade,
    event_type: "TRADE",
  };
}

function normalizeWallet(wallet) {
  return {
    ...wallet,
    event_type: "WALLET",
  };
}

function normalizeAlert(alert) {
  return {
    ...alert,
    event_type: "ALERT",
  };
}

function buildSnapshotEvents(snapshot) {
  return [
    ...(snapshot.recent_trades ?? []).map(
      normalizeTrade
    ),
    ...(snapshot.recent_wallets ?? []).map(
      normalizeWallet
    ),
    ...(snapshot.alerts ?? []).map(
      normalizeAlert
    ),
  ]
    .sort(
      (first, second) =>
        new Date(second.timestamp ?? 0).getTime() -
        new Date(first.timestamp ?? 0).getTime()
    )
    .slice(0, MAX_EVENTS);
}

function LiveEventCard({ event }) {
  if (event.event_type === "TRADE") {
    const isBuy = event.side === "BUY";

    return (
      <article className="rounded-xl border border-slate-700 bg-slate-800 p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3">
            <span
              className={`rounded-full px-3 py-1 text-xs font-bold ${
                isBuy
                  ? "bg-green-900/50 text-green-300"
                  : "bg-red-900/50 text-red-300"
              }`}
            >
              {event.side ?? "TRADE"}
            </span>

            <div>
              <p className="font-semibold">
                Smart wallet transaction
              </p>

              <p className="mt-1 text-sm text-slate-400">
                {formatTimestamp(event.timestamp)}
              </p>
            </div>
          </div>

          <p
            className={`text-xl font-bold ${
              isBuy
                ? "text-green-300"
                : "text-red-300"
            }`}
          >
            {formatNumber(event.sol_amount)} SOL
          </p>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
          <div>
            <p className="text-slate-500">Wallet</p>

            <Link
              to={`/wallet/${event.wallet}`}
              className="mt-1 block font-mono text-blue-400 hover:underline"
              title={event.wallet}
            >
              {shortenAddress(event.wallet)}
            </Link>
          </div>

          <div>
            <p className="text-slate-500">Token</p>

            {event.token ? (
              <a
                href={`https://solscan.io/token/${event.token}`}
                target="_blank"
                rel="noreferrer"
                className="mt-1 block font-mono text-blue-300 hover:underline"
                title={event.token}
              >
                {shortenAddress(event.token)}
              </a>
            ) : (
              <p className="mt-1">-</p>
            )}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-4 text-xs text-slate-500">
          <span>Source: {event.source ?? "-"}</span>

          {event.signature && (
            <a
              href={`https://solscan.io/tx/${event.signature}`}
              target="_blank"
              rel="noreferrer"
              className="text-blue-400 hover:underline"
            >
              Apri transazione
            </a>
          )}
        </div>
      </article>
    );
  }

  if (event.event_type === "ALERT") {
    return (
      <article className="rounded-xl border border-red-800 bg-red-950/20 p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <span className="rounded-full bg-red-900/60 px-3 py-1 text-xs font-bold text-red-300">
              LIVE ALERT
            </span>

            <h3 className="mt-3 text-lg font-bold">
              {event.type ?? "SMART_ACCUMULATION"}
            </h3>

            <p className="mt-1 text-sm text-slate-400">
              {formatTimestamp(event.timestamp)}
            </p>
          </div>

          <div className="text-left sm:text-right">
            <p className="text-sm text-slate-400">
              Signal Score
            </p>

            <p className="text-2xl font-bold text-red-300">
              {formatNumber(event.signal_score, 2)}
            </p>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-4 text-sm lg:grid-cols-4">
          <div>
            <p className="text-slate-500">Buyers</p>
            <p className="mt-1 font-bold">
              {event.buyers ?? 0}
            </p>
          </div>

          <div>
            <p className="text-slate-500">
              Confidence
            </p>
            <p className="mt-1 font-bold">
              {event.confidence ?? "LOW"}
            </p>
          </div>

          <div>
            <p className="text-slate-500">
              Average ROI
            </p>
            <p className="mt-1 font-bold">
              {formatNumber(event.average_roi, 2)}%
            </p>
          </div>

          <div>
            <p className="text-slate-500">
              Volume
            </p>
            <p className="mt-1 font-bold">
              {formatNumber(
                event.total_volume_sol
              )}{" "}
              SOL
            </p>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
          <div>
            <p className="text-slate-500">Token</p>

            <a
              href={`https://solscan.io/token/${event.token}`}
              target="_blank"
              rel="noreferrer"
              className="mt-1 block font-mono text-blue-300 hover:underline"
              title={event.token}
            >
              {shortenAddress(event.token)}
            </a>
          </div>

          <div>
            <p className="text-slate-500">
              Leader wallet
            </p>

            <Link
              to={`/wallet/${event.leader_wallet}`}
              className="mt-1 block font-mono text-blue-400 hover:underline"
              title={event.leader_wallet}
            >
              {shortenAddress(event.leader_wallet)}
            </Link>
          </div>
        </div>
      </article>
    );
  }

  return (
    <article className="rounded-xl border border-purple-800 bg-purple-950/20 p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <span className="rounded-full bg-purple-900/60 px-3 py-1 text-xs font-bold text-purple-300">
            NEW WALLET
          </span>

          <p className="mt-3 text-sm text-slate-400">
            {formatTimestamp(event.timestamp)}
          </p>
        </div>

        <div className="text-left sm:text-right">
          <p className="text-sm text-slate-400">
            Smart Score
          </p>

          <p className="text-2xl font-bold text-purple-300">
            {formatNumber(event.smart_score, 2)}
          </p>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <p className="text-slate-500">Wallet</p>

          <Link
            to={`/wallet/${event.wallet}`}
            className="mt-1 block font-mono text-blue-400 hover:underline"
            title={event.wallet}
          >
            {shortenAddress(event.wallet)}
          </Link>
        </div>

        <div>
          <p className="text-slate-500">ROI</p>
          <p className="mt-1 font-bold">
            {formatNumber(event.roi_percent, 2)}%
          </p>
        </div>

        <div>
          <p className="text-slate-500">Win Rate</p>
          <p className="mt-1 font-bold">
            {formatNumber(
              event.win_rate_percent,
              2
            )}
            %
          </p>
        </div>

        <div>
          <p className="text-slate-500">Status</p>
          <p className="mt-1 font-bold">
            {event.status ?? "DISCOVERED"}
          </p>
        </div>
      </div>
    </article>
  );
}

function LiveScanner() {
  const eventSourceRef = useRef(null);

  const [events, setEvents] = useState([]);
  const [backendStatus, setBackendStatus] =
    useState(null);

  const [connectionStatus, setConnectionStatus] =
    useState("CONNECTING");

  const [paused, setPaused] = useState(false);
  const [connectionVersion, setConnectionVersion] =
    useState(0);

  const [eventFilter, setEventFilter] =
    useState("ALL");
  const [search, setSearch] = useState("");
  const [lastMessageAt, setLastMessageAt] =
    useState(null);

  const addEvent = useCallback((event) => {
    setEvents((currentEvents) => {
      const eventKey = getEventKey(event);

      const withoutDuplicate =
        currentEvents.filter(
          (currentEvent) =>
            getEventKey(currentEvent) !== eventKey
        );

      return [
        event,
        ...withoutDuplicate,
      ].slice(0, MAX_EVENTS);
    });

    setLastMessageAt(new Date());
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const response = await fetch(LIVE_STATUS_URL);

      if (!response.ok) {
        throw new Error(
          `Status HTTP ${response.status}`
        );
      }

      const data = await response.json();
      setBackendStatus(data);
    } catch (error) {
      console.error(
        "Errore caricamento stato live:",
        error
      );
    }
  }, []);

  useEffect(() => {
    loadStatus();

    const statusInterval = window.setInterval(
      loadStatus,
      15000
    );

    return () => {
      window.clearInterval(statusInterval);
    };
  }, [loadStatus]);

  useEffect(() => {
    if (paused) {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      setConnectionStatus("PAUSED");

      return undefined;
    }

    setConnectionStatus("CONNECTING");

    const eventSource = new EventSource(
      LIVE_STREAM_URL
    );

    eventSourceRef.current = eventSource;

    eventSource.onopen = () => {
      setConnectionStatus("LIVE");
    };

    eventSource.onerror = () => {
      setConnectionStatus("RECONNECTING");
    };

    eventSource.addEventListener(
      "snapshot",
      (message) => {
        try {
          const snapshot = JSON.parse(message.data);

          setEvents(
            buildSnapshotEvents(snapshot)
          );

          setBackendStatus(snapshot.status);
          setLastMessageAt(new Date());
        } catch (error) {
          console.error(
            "Errore snapshot live:",
            error
          );
        }
      }
    );

    eventSource.addEventListener(
      "trade",
      (message) => {
        try {
          addEvent(
            normalizeTrade(
              JSON.parse(message.data)
            )
          );
        } catch (error) {
          console.error(
            "Errore evento trade:",
            error
          );
        }
      }
    );

    eventSource.addEventListener(
      "wallet",
      (message) => {
        try {
          addEvent(
            normalizeWallet(
              JSON.parse(message.data)
            )
          );
        } catch (error) {
          console.error(
            "Errore evento wallet:",
            error
          );
        }
      }
    );

    eventSource.addEventListener(
      "alert",
      (message) => {
        try {
          addEvent(
            normalizeAlert(
              JSON.parse(message.data)
            )
          );
        } catch (error) {
          console.error(
            "Errore evento alert:",
            error
          );
        }
      }
    );

    eventSource.addEventListener(
      "heartbeat",
      () => {
        setConnectionStatus("LIVE");
        setLastMessageAt(new Date());
      }
    );

    return () => {
      eventSource.close();

      if (eventSourceRef.current === eventSource) {
        eventSourceRef.current = null;
      }
    };
  }, [
    paused,
    connectionVersion,
    addEvent,
  ]);

  const filteredEvents = useMemo(() => {
    const normalizedSearch = search
      .trim()
      .toLowerCase();

    return events.filter((event) => {
      const matchesType =
        eventFilter === "ALL" ||
        event.event_type === eventFilter;

      const searchableValues = [
        event.wallet,
        event.token,
        event.leader_wallet,
        event.signature,
        event.type,
        event.side,
      ];

      const matchesSearch =
        !normalizedSearch ||
        searchableValues.some((value) =>
          String(value ?? "")
            .toLowerCase()
            .includes(normalizedSearch)
        );

      return matchesType && matchesSearch;
    });
  }, [events, eventFilter, search]);

  const eventCounts = useMemo(
    () => ({
      trades: events.filter(
        (event) =>
          event.event_type === "TRADE"
      ).length,
      alerts: events.filter(
        (event) =>
          event.event_type === "ALERT"
      ).length,
      wallets: events.filter(
        (event) =>
          event.event_type === "WALLET"
      ).length,
    }),
    [events]
  );

  function reconnect() {
    setPaused(false);
    setConnectionVersion(
      (current) => current + 1
    );
  }

  function getConnectionClasses() {
    switch (connectionStatus) {
      case "LIVE":
        return "border-green-700 bg-green-900/40 text-green-300";

      case "PAUSED":
        return "border-yellow-700 bg-yellow-900/40 text-yellow-300";

      case "RECONNECTING":
        return "border-orange-700 bg-orange-900/40 text-orange-300";

      default:
        return "border-blue-700 bg-blue-900/40 text-blue-300";
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 p-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-3xl font-bold">
              Live Scanner
            </h1>

            <p className="mt-2 text-slate-400">
              Transazioni, nuovi wallet e alert
              ricevuti tramite Server-Sent Events
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <span
              className={`rounded-full border px-4 py-2 text-sm font-bold ${getConnectionClasses()}`}
            >
              ● {connectionStatus}
            </span>

            <button
              type="button"
              onClick={() =>
                setPaused((current) => !current)
              }
              className="rounded-lg border border-slate-600 bg-slate-800 px-4 py-2 text-sm font-semibold hover:bg-slate-700"
            >
              {paused
                ? "Riprendi stream"
                : "Pausa stream"}
            </button>

            <button
              type="button"
              onClick={reconnect}
              className="rounded-lg border border-blue-700 bg-blue-900/40 px-4 py-2 text-sm font-semibold text-blue-300 hover:bg-blue-900/70"
            >
              Riconnetti
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl p-4 sm:p-8">
        <section className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-5">
          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Smart Wallet
            </p>

            <p className="mt-2 text-3xl font-bold text-blue-300">
              {backendStatus?.smart_wallets_monitored ??
                "-"}
            </p>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Live Trades
            </p>

            <p className="mt-2 text-3xl font-bold text-green-300">
              {eventCounts.trades}
            </p>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Live Alerts
            </p>

            <p className="mt-2 text-3xl font-bold text-red-300">
              {eventCounts.alerts}
            </p>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Nuovi Wallet
            </p>

            <p className="mt-2 text-3xl font-bold text-purple-300">
              {eventCounts.wallets}
            </p>
          </div>

          <div className="col-span-2 rounded-xl border border-slate-700 bg-slate-800 p-5 lg:col-span-1">
            <p className="text-sm text-slate-400">
              Ultimo messaggio
            </p>

            <p className="mt-2 text-lg font-bold">
              {lastMessageAt
                ? lastMessageAt.toLocaleTimeString(
                    "it-IT"
                  )
                : "-"}
            </p>
          </div>
        </section>

        <section className="mb-8 rounded-xl border border-slate-700 bg-slate-800 p-5">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <input
              type="text"
              value={search}
              onChange={(event) =>
                setSearch(event.target.value)
              }
              placeholder="Cerca wallet, token o transazione..."
              className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-blue-500 md:col-span-2"
            />

            <select
              value={eventFilter}
              onChange={(event) =>
                setEventFilter(event.target.value)
              }
              className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-blue-500"
            >
              <option value="ALL">
                Tutti gli eventi
              </option>

              <option value="TRADE">
                Solo trades
              </option>

              <option value="ALERT">
                Solo alert
              </option>

              <option value="WALLET">
                Solo nuovi wallet
              </option>
            </select>
          </div>

          <div className="mt-4 flex items-center justify-between">
            <p className="text-sm text-slate-400">
              {filteredEvents.length} eventi
              visualizzati
            </p>

            <button
              type="button"
              onClick={() => setEvents([])}
              disabled={events.length === 0}
              className="rounded-lg border border-red-700 bg-red-900/30 px-4 py-2 text-sm text-red-300 hover:bg-red-900/60 disabled:opacity-40"
            >
              Pulisci feed
            </button>
          </div>
        </section>

        <section className="space-y-4">
          {filteredEvents.length === 0 ? (
            <div className="rounded-xl border border-slate-700 bg-slate-800 p-12 text-center text-slate-400">
              In attesa di eventi live...
            </div>
          ) : (
            filteredEvents.map((event) => (
              <LiveEventCard
                key={getEventKey(event)}
                event={event}
              />
            ))
          )}
        </section>
      </main>
    </div>
  );
}

export default LiveScanner; 