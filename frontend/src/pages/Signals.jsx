import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import LatestAlerts from "../components/LatestAlerts";
import TopSignals from "../components/TopSignals";
import { getDashboard } from "../services/api";

function Signals() {
  const [dashboard, setDashboard] = useState(null);
  const [search, setSearch] = useState("");
  const [confidence, setConfidence] = useState("ALL");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);

  const loadData = useCallback(async (manualRefresh = false) => {
    if (manualRefresh) {
      setRefreshing(true);
    }

    setError("");

    try {
      const response = await getDashboard();

      setDashboard(response.data);
      setLastUpdated(new Date());
    } catch (requestError) {
      console.error(
        "Errore caricamento segnali:",
        requestError
      );

      setError(
        "Impossibile caricare segnali e alert dal backend."
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadData();

    const intervalId = window.setInterval(() => {
      loadData();
    }, 15000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [loadData]);

  const filteredSignals = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    const signals = dashboard?.top_signals ?? [];

    return signals.filter((signal) => {
      const matchesConfidence =
        confidence === "ALL" ||
        signal.confidence === confidence;

      const matchesSearch =
        !normalizedSearch ||
        (signal.token_mint ?? "")
          .toLowerCase()
          .includes(normalizedSearch) ||
        (signal.leader_wallet ?? "")
          .toLowerCase()
          .includes(normalizedSearch);

      return matchesConfidence && matchesSearch;
    });
  }, [dashboard, search, confidence]);

  const filteredAlerts = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    const alerts = dashboard?.latest_alerts ?? [];

    return alerts.filter((alert) => {
      const matchesConfidence =
        confidence === "ALL" ||
        alert.confidence === confidence;

      const matchesSearch =
        !normalizedSearch ||
        (alert.token ?? "")
          .toLowerCase()
          .includes(normalizedSearch) ||
        (alert.leader_wallet ?? "")
          .toLowerCase()
          .includes(normalizedSearch) ||
        (alert.type ?? "")
          .toLowerCase()
          .includes(normalizedSearch);

      return matchesConfidence && matchesSearch;
    });
  }, [dashboard, search, confidence]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-900 text-white">
        <div className="text-center">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-slate-700 border-t-blue-500" />

          <p className="mt-4 text-slate-400">
            Caricamento segnali...
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 p-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <Link
              to="/"
              className="text-sm text-blue-400 hover:underline"
            >
              ← Torna alla dashboard
            </Link>

            <h1 className="mt-3 text-3xl font-bold">
              Signals Intelligence
            </h1>

            <p className="mt-2 text-slate-400">
              Segnali e accumulazioni rilevati dai wallet smart
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="text-sm text-slate-400">
              Ultimo aggiornamento:{" "}
              {lastUpdated
                ? lastUpdated.toLocaleTimeString("it-IT")
                : "-"}
            </div>

            <button
              type="button"
              onClick={() => loadData(true)}
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
              Segnali disponibili
            </p>

            <p className="mt-2 text-3xl font-bold text-yellow-300">
              {dashboard?.stats?.signals ?? 0}
            </p>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Alert disponibili
            </p>

            <p className="mt-2 text-3xl font-bold text-red-300">
              {dashboard?.stats?.alerts ?? 0}
            </p>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Risultati visualizzati
            </p>

            <p className="mt-2 text-3xl font-bold text-blue-300">
              {filteredSignals.length + filteredAlerts.length}
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
              placeholder="Cerca token, wallet leader o tipo..."
              className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-blue-500 md:col-span-2"
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
          </div>
        </section>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <TopSignals signals={filteredSignals} />

          <LatestAlerts alerts={filteredAlerts} />
        </div>
      </main>
    </div>
  );
}

export default Signals; 