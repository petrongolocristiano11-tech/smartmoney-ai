import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Link } from "react-router-dom";

import { getDashboard } from "../services/api";

const READ_ALERTS_STORAGE_KEY = "smartmoney-read-alerts";

function shortenAddress(address, start = 9, end = 7) {
  if (!address) return "-";

  if (address.length <= start + end + 3) {
    return address;
  }

  return `${address.slice(0, start)}...${address.slice(-end)}`;
}

function formatNumber(value, digits = 2) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "0";
  }

  return number.toLocaleString("it-IT", {
    maximumFractionDigits: digits,
  });
}

function getAlertId(alert) {
  return [
    alert.type,
    alert.token,
    alert.leader_wallet,
    alert.signal_score,
    alert.buyers,
  ].join("-");
}

function loadReadAlerts() {
  try {
    const storedValue = window.localStorage.getItem(
      READ_ALERTS_STORAGE_KEY
    );

    if (!storedValue) {
      return [];
    }

    const parsedValue = JSON.parse(storedValue);

    return Array.isArray(parsedValue) ? parsedValue : [];
  } catch (error) {
    console.error("Errore caricamento alert letti:", error);
    return [];
  }
}

function getConfidenceClasses(confidence) {
  switch (confidence) {
    case "HIGH":
      return "border-green-700 bg-green-900/40 text-green-300";

    case "MEDIUM":
      return "border-yellow-700 bg-yellow-900/40 text-yellow-300";

    default:
      return "border-slate-600 bg-slate-700 text-slate-300";
  }
}

function escapeCsvValue(value) {
  const normalized =
    value === null || value === undefined
      ? ""
      : String(value);

  return `"${normalized.replaceAll('"', '""')}"`;
}

function Alerts() {
  const [alerts, setAlerts] = useState([]);
  const [readAlerts, setReadAlerts] =
    useState(loadReadAlerts);

  const [search, setSearch] = useState("");
  const [confidence, setConfidence] = useState("ALL");
  const [statusFilter, setStatusFilter] = useState("ALL");

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);

  const loadAlerts = useCallback(
    async (manualRefresh = false) => {
      if (manualRefresh) {
        setRefreshing(true);
      }

      setError("");

      try {
        const response = await getDashboard();

        setAlerts(
          Array.isArray(response.data?.latest_alerts)
            ? response.data.latest_alerts
            : []
        );

        setLastUpdated(new Date());
      } catch (requestError) {
        console.error(
          "Errore caricamento alert:",
          requestError
        );

        setError(
          "Impossibile caricare gli alert dal backend."
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    []
  );

  useEffect(() => {
    loadAlerts();

    const intervalId = window.setInterval(() => {
      loadAlerts();
    }, 15000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [loadAlerts]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        READ_ALERTS_STORAGE_KEY,
        JSON.stringify(readAlerts)
      );
    } catch (storageError) {
      console.error(
        "Errore salvataggio alert letti:",
        storageError
      );
    }
  }, [readAlerts]);

  const filteredAlerts = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();

    return alerts.filter((alert) => {
      const alertId = getAlertId(alert);
      const isRead = readAlerts.includes(alertId);

      const matchesConfidence =
        confidence === "ALL" ||
        alert.confidence === confidence;

      const matchesStatus =
        statusFilter === "ALL" ||
        (statusFilter === "READ" && isRead) ||
        (statusFilter === "UNREAD" && !isRead);

      const matchesSearch =
        !normalizedSearch ||
        [
          alert.type,
          alert.token,
          alert.leader_wallet,
        ].some((value) =>
          String(value ?? "")
            .toLowerCase()
            .includes(normalizedSearch)
        );

      return (
        matchesConfidence &&
        matchesStatus &&
        matchesSearch
      );
    });
  }, [
    alerts,
    readAlerts,
    search,
    confidence,
    statusFilter,
  ]);

  const unreadCount = useMemo(
    () =>
      alerts.filter(
        (alert) =>
          !readAlerts.includes(getAlertId(alert))
      ).length,
    [alerts, readAlerts]
  );

  function toggleRead(alert) {
    const alertId = getAlertId(alert);

    setReadAlerts((currentReadAlerts) => {
      if (currentReadAlerts.includes(alertId)) {
        return currentReadAlerts.filter(
          (currentId) => currentId !== alertId
        );
      }

      return [...currentReadAlerts, alertId];
    });
  }

  function markAllAsRead() {
    const allAlertIds = alerts.map(getAlertId);

    setReadAlerts((currentReadAlerts) => [
      ...new Set([
        ...currentReadAlerts,
        ...allAlertIds,
      ]),
    ]);
  }

  function exportAlertsCsv() {
    if (filteredAlerts.length === 0) {
      alert("Nessun alert da esportare");
      return;
    }

    const headers = [
      "Type",
      "Token",
      "Signal Score",
      "Confidence",
      "Leader Wallet",
      "Buyers",
      "Average Smart Score",
      "Average ROI",
      "Volume SOL",
      "Read",
    ];

    const rows = filteredAlerts.map((alert) => [
      alert.type,
      alert.token,
      alert.signal_score,
      alert.confidence,
      alert.leader_wallet,
      alert.buyers,
      alert.average_smart_score,
      alert.average_roi,
      alert.total_volume_sol,
      readAlerts.includes(getAlertId(alert))
        ? "YES"
        : "NO",
    ]);

    const csvContent = [
      headers.map(escapeCsvValue).join(","),
      ...rows.map((row) =>
        row.map(escapeCsvValue).join(",")
      ),
    ].join("\n");

    const blob = new Blob([csvContent], {
      type: "text/csv;charset=utf-8;",
    });

    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = downloadUrl;
    link.download = `smartmoney-alerts-${new Date()
      .toISOString()
      .slice(0, 10)}.csv`;

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    URL.revokeObjectURL(downloadUrl);
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 p-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-3xl font-bold">
              Alert Center
            </h1>

            <p className="mt-2 text-slate-400">
              Gestisci gli alert generati dal motore
              SmartMoney
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <p className="text-sm text-slate-400">
              Ultimo aggiornamento:{" "}
              {lastUpdated
                ? lastUpdated.toLocaleTimeString("it-IT")
                : "-"}
            </p>

            <button
              type="button"
              onClick={() => loadAlerts(true)}
              disabled={refreshing}
              className="rounded-lg border border-blue-700 bg-blue-900/40 px-4 py-2 text-sm font-semibold text-blue-300 hover:bg-blue-900/70 disabled:opacity-50"
            >
              {refreshing
                ? "Aggiornamento..."
                : "Aggiorna"}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl p-4 sm:p-8">
        {error && (
          <div className="mb-6 rounded-lg border border-red-700 bg-red-900/30 p-4 text-red-300">
            {error}
          </div>
        )}

        <section className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Alert totali
            </p>

            <p className="mt-2 text-3xl font-bold text-red-300">
              {alerts.length}
            </p>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Non letti
            </p>

            <p className="mt-2 text-3xl font-bold text-yellow-300">
              {unreadCount}
            </p>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Visualizzati
            </p>

            <p className="mt-2 text-3xl font-bold text-blue-300">
              {filteredAlerts.length}
            </p>
          </div>
        </section>

        <section className="mb-8 rounded-xl border border-slate-700 bg-slate-800 p-5">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
            <input
              type="text"
              value={search}
              onChange={(event) =>
                setSearch(event.target.value)
              }
              placeholder="Cerca token, wallet o tipo..."
              className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-blue-500 lg:col-span-2"
            />

            <select
              value={confidence}
              onChange={(event) =>
                setConfidence(event.target.value)
              }
              className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-blue-500"
            >
              <option value="ALL">
                Tutte le confidence
              </option>
              <option value="HIGH">HIGH</option>
              <option value="MEDIUM">MEDIUM</option>
              <option value="LOW">LOW</option>
            </select>

            <select
              value={statusFilter}
              onChange={(event) =>
                setStatusFilter(event.target.value)
              }
              className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-blue-500"
            >
              <option value="ALL">Tutti</option>
              <option value="UNREAD">Non letti</option>
              <option value="READ">Letti</option>
            </select>
          </div>

          <div className="mt-4 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={markAllAsRead}
              disabled={alerts.length === 0}
              className="rounded-lg border border-green-700 bg-green-900/30 px-4 py-2 text-sm font-semibold text-green-300 hover:bg-green-900/60 disabled:opacity-40"
            >
              Segna tutti come letti
            </button>

            <button
              type="button"
              onClick={exportAlertsCsv}
              disabled={filteredAlerts.length === 0}
              className="rounded-lg border border-blue-700 bg-blue-900/30 px-4 py-2 text-sm font-semibold text-blue-300 hover:bg-blue-900/60 disabled:opacity-40"
            >
              Esporta CSV
            </button>
          </div>
        </section>

        <section className="space-y-4">
          {loading ? (
            <div className="rounded-xl border border-slate-700 bg-slate-800 p-12 text-center text-slate-400">
              Caricamento alert...
            </div>
          ) : filteredAlerts.length === 0 ? (
            <div className="rounded-xl border border-slate-700 bg-slate-800 p-12 text-center text-slate-400">
              Nessun alert trovato.
            </div>
          ) : (
            filteredAlerts.map((alert) => {
              const alertId = getAlertId(alert);
              const isRead = readAlerts.includes(alertId);

              return (
                <article
                  key={alertId}
                  className={`rounded-xl border p-5 ${
                    isRead
                      ? "border-slate-700 bg-slate-800 opacity-70"
                      : "border-red-800 bg-red-950/20"
                  }`}
                >
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-red-900/50 px-3 py-1 text-xs font-bold text-red-300">
                          {alert.type ??
                            "SMART_ACCUMULATION"}
                        </span>

                        <span
                          className={`rounded-full border px-3 py-1 text-xs font-semibold ${getConfidenceClasses(
                            alert.confidence
                          )}`}
                        >
                          {alert.confidence ?? "LOW"}
                        </span>

                        {!isRead && (
                          <span className="rounded-full bg-yellow-900/50 px-3 py-1 text-xs font-semibold text-yellow-300">
                            NUOVO
                          </span>
                        )}
                      </div>

                      <a
                        href={`https://solscan.io/token/${alert.token}`}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-3 block font-mono text-blue-300 hover:underline"
                        title={alert.token}
                      >
                        {shortenAddress(
                          alert.token,
                          12,
                          10
                        )}
                      </a>
                    </div>

                    <div className="flex items-center gap-4">
                      <div className="text-right">
                        <p className="text-sm text-slate-400">
                          Signal Score
                        </p>

                        <p className="text-3xl font-bold text-red-300">
                          {formatNumber(
                            alert.signal_score,
                            2
                          )}
                        </p>
                      </div>

                      <button
                        type="button"
                        onClick={() => toggleRead(alert)}
                        className="rounded-lg border border-slate-600 bg-slate-800 px-4 py-2 text-sm font-semibold hover:bg-slate-700"
                      >
                        {isRead
                          ? "Segna non letto"
                          : "Segna letto"}
                      </button>
                    </div>
                  </div>

                  <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
                    <div>
                      <p className="text-sm text-slate-500">
                        Buyers
                      </p>

                      <p className="mt-1 font-bold">
                        {alert.buyers ?? 0}
                      </p>
                    </div>

                    <div>
                      <p className="text-sm text-slate-500">
                        Smart Score medio
                      </p>

                      <p className="mt-1 font-bold">
                        {formatNumber(
                          alert.average_smart_score,
                          2
                        )}
                      </p>
                    </div>

                    <div>
                      <p className="text-sm text-slate-500">
                        ROI medio
                      </p>

                      <p className="mt-1 font-bold">
                        {formatNumber(
                          alert.average_roi,
                          2
                        )}
                        %
                      </p>
                    </div>

                    <div>
                      <p className="text-sm text-slate-500">
                        Volume
                      </p>

                      <p className="mt-1 font-bold">
                        {formatNumber(
                          alert.total_volume_sol,
                          4
                        )}{" "}
                        SOL
                      </p>
                    </div>
                  </div>

                  <div className="mt-5">
                    <span className="text-sm text-slate-500">
                      Leader wallet:{" "}
                    </span>

                    <Link
                      to={`/wallet/${alert.leader_wallet}`}
                      className="font-mono text-sm text-blue-400 hover:underline"
                      title={alert.leader_wallet}
                    >
                      {shortenAddress(
                        alert.leader_wallet
                      )}
                    </Link>
                  </div>
                </article>
              );
            })
          )}
        </section>
      </main>
    </div>
  );
}

export default Alerts; 