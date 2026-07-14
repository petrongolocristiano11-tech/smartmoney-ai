import { useCallback, useEffect, useState } from "react";

import DashboardStats from "./components/DashboardStats";
import DiscoveryPanel from "./components/DiscoveryPanel";
import LatestAlerts from "./components/LatestAlerts";
import TopSignals from "./components/TopSignals";
import WalletTable from "./components/WalletTable";

import {
  getDashboard,
  getWalletRanking,
  runDiscovery,
} from "./services/api";

function App() {
  const [wallets, setWallets] = useState([]);
  const [dashboard, setDashboard] = useState(null);

  const [walletAddress, setWalletAddress] = useState("");
  const [maxTokens, setMaxTokens] = useState(3);
  const [maxWalletsPerToken, setMaxWalletsPerToken] = useState(3);

  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("smart_score");

  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const [message, setMessage] = useState("");
  const [lastDiscovery, setLastDiscovery] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [loadError, setLoadError] = useState("");

  const refreshData = useCallback(async (showIndicator = false) => {
    if (showIndicator) {
      setRefreshing(true);
    }

    setLoadError("");

    try {
      const [rankingResult, dashboardResult] =
        await Promise.allSettled([
          getWalletRanking(),
          getDashboard(),
        ]);

      if (rankingResult.status === "fulfilled") {
        setWallets(rankingResult.value.data.ranking ?? []);
      } else {
        console.error(
          "Errore caricamento ranking:",
          rankingResult.reason
        );
      }

      if (dashboardResult.status === "fulfilled") {
        setDashboard(dashboardResult.value.data);
      } else {
        console.error(
          "Errore caricamento dashboard:",
          dashboardResult.reason
        );
      }

      if (
        rankingResult.status === "rejected" &&
        dashboardResult.status === "rejected"
      ) {
        setLoadError(
          "Impossibile collegarsi al backend. Controlla che FastAPI sia avviato."
        );

        return;
      }

      setLastUpdated(new Date());
    } finally {
      if (showIndicator) {
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    refreshData();

    if (!autoRefresh) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      refreshData();
    }, 15000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [autoRefresh, refreshData]);

  const averageScore =
    wallets.length > 0
      ? (
          wallets.reduce(
            (sum, wallet) =>
              sum + (wallet.smart_score ?? 0),
            0
          ) / wallets.length
        ).toFixed(2)
      : "-";

  const filteredWallets = [...wallets]
    .filter((wallet) =>
      (wallet.wallet ?? "")
        .toLowerCase()
        .includes(search.toLowerCase())
    )
    .sort((a, b) => {
      switch (sortBy) {
        case "roi":
          return (
            (b.roi_percent ?? 0) -
            (a.roi_percent ?? 0)
          );

        case "winrate":
          return (
            (b.win_rate_percent ?? 0) -
            (a.win_rate_percent ?? 0)
          );

        case "profit":
          return (
            (b.profit_loss_sol ?? 0) -
            (a.profit_loss_sol ?? 0)
          );

        default:
          return (
            (b.smart_score ?? 0) -
            (a.smart_score ?? 0)
          );
      }
    });

  const topSignals = dashboard?.top_signals ?? [];
  const latestAlerts = dashboard?.latest_alerts ?? [];

  async function handleDiscover() {
    const normalizedWallet = walletAddress.trim();

    if (!normalizedWallet) {
      alert("Inserisci un wallet");
      return;
    }

    setLoading(true);
    setMessage("");
    setLastDiscovery(null);

    try {
      const response = await runDiscovery(
        normalizedWallet,
        maxTokens,
        maxWalletsPerToken
      );

      setWalletAddress("");
      setLastDiscovery(response.data);

      setMessage(
        `Discovery completata: ${
          response.data.wallets_discovered ?? 0
        } wallet trovati`
      );

      await refreshData();
    } catch (error) {
      console.error(
        "Errore durante la discovery:",
        error
      );

      alert("Errore durante la discovery");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700 p-6">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-4xl font-bold">
              🚀 SmartMoney AI
            </h1>

            <p className="mt-2 text-slate-400">
              Smart Score v4.0 Wallet Intelligence
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() =>
                setAutoRefresh((current) => !current)
              }
              className={`rounded-full border px-4 py-2 text-sm ${
                autoRefresh
                  ? "border-green-700 bg-green-900/40 text-green-300"
                  : "border-slate-600 bg-slate-800 text-slate-300"
              }`}
            >
              {autoRefresh
                ? "Live refresh ON"
                : "Live refresh OFF"}
            </button>

            <button
              type="button"
              onClick={() => refreshData(true)}
              disabled={refreshing}
              className="rounded-full border border-blue-700 bg-blue-900/40 px-4 py-2 text-sm text-blue-300 hover:bg-blue-900/70 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {refreshing
                ? "Aggiornamento..."
                : "Aggiorna ora"}
            </button>

            <div className="rounded-full border border-green-700 bg-green-900/40 px-4 py-2 text-sm text-green-300">
              Engine v3.0 Online
            </div>
          </div>
        </div>

        <div className="mx-auto mt-3 max-w-7xl text-right text-xs text-slate-500">
          Ultimo aggiornamento:{" "}
          {lastUpdated
            ? lastUpdated.toLocaleTimeString("it-IT")
            : "in attesa"}
        </div>
      </header>

      <main className="mx-auto max-w-7xl p-4 sm:p-8">
        {loadError && (
          <div className="mb-6 rounded-lg border border-red-700 bg-red-900/40 px-4 py-3 text-red-300">
            {loadError}
          </div>
        )}

        <DiscoveryPanel
          walletAddress={walletAddress}
          setWalletAddress={setWalletAddress}
          maxTokens={maxTokens}
          setMaxTokens={setMaxTokens}
          maxWalletsPerToken={maxWalletsPerToken}
          setMaxWalletsPerToken={setMaxWalletsPerToken}
          search={search}
          setSearch={setSearch}
          sortBy={sortBy}
          setSortBy={setSortBy}
          loading={loading}
          message={message}
          lastDiscovery={lastDiscovery}
          onDiscover={handleDiscover}
        />

        <DashboardStats
          wallets={wallets}
          dashboard={dashboard}
          averageScore={averageScore}
          filteredWallets={filteredWallets}
        />

        <div className="mb-8 grid grid-cols-1 gap-6 xl:grid-cols-2">
          <TopSignals signals={topSignals} />

          <LatestAlerts alerts={latestAlerts} />
        </div>

        <WalletTable wallets={filteredWallets} />
      </main>
    </div>
  );
}

export default App; 