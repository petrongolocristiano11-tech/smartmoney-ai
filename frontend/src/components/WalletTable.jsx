import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

const WATCHLIST_STORAGE_KEY = "smartmoney-wallet-watchlist";
const PAGE_SIZE_STORAGE_KEY = "smartmoney-ranking-page-size";

function shortenAddress(address, start = 10, end = 8) {
  if (!address) return "-";

  if (address.length <= start + end + 3) {
    return address;
  }

  return `${address.slice(0, start)}...${address.slice(-end)}`;
}

function escapeCsvValue(value) {
  const normalizedValue =
    value === null || value === undefined
      ? ""
      : String(value);

  return `"${normalizedValue.replaceAll('"', '""')}"`;
}

function loadWatchlist() {
  try {
    const storedValue = window.localStorage.getItem(
      WATCHLIST_STORAGE_KEY
    );

    if (!storedValue) {
      return [];
    }

    const parsedValue = JSON.parse(storedValue);

    return Array.isArray(parsedValue) ? parsedValue : [];
  } catch (error) {
    console.error("Errore caricamento watchlist:", error);
    return [];
  }
}

function loadPageSize() {
  try {
    const storedValue = Number(
      window.localStorage.getItem(PAGE_SIZE_STORAGE_KEY)
    );

    if ([10, 25, 50, 100].includes(storedValue)) {
      return storedValue;
    }

    return 10;
  } catch {
    return 10;
  }
}

function formatMetric(value, suffix = "") {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return `0${suffix}`;
  }

  return `${number.toLocaleString("it-IT", {
    maximumFractionDigits: 2,
  })}${suffix}`;
}

function WalletTable({ wallets = [] }) {
  const [watchlist, setWatchlist] = useState(loadWatchlist);
  const [showFavoritesOnly, setShowFavoritesOnly] =
    useState(false);
  const [selectedWallets, setSelectedWallets] = useState([]);

  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(loadPageSize);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        WATCHLIST_STORAGE_KEY,
        JSON.stringify(watchlist)
      );
    } catch (error) {
      console.error("Errore salvataggio watchlist:", error);
    }
  }, [watchlist]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        PAGE_SIZE_STORAGE_KEY,
        String(pageSize)
      );
    } catch (error) {
      console.error(
        "Errore salvataggio dimensione pagina:",
        error
      );
    }
  }, [pageSize]);

  useEffect(() => {
    setSelectedWallets((currentSelection) =>
      currentSelection.filter((address) =>
        wallets.some((wallet) => wallet.wallet === address)
      )
    );
  }, [wallets]);

  const visibleWallets = useMemo(() => {
    if (!showFavoritesOnly) {
      return wallets;
    }

    return wallets.filter((wallet) =>
      watchlist.includes(wallet.wallet)
    );
  }, [wallets, watchlist, showFavoritesOnly]);

  const totalPages = Math.max(
    1,
    Math.ceil(visibleWallets.length / pageSize)
  );

  useEffect(() => {
    setCurrentPage((current) =>
      Math.min(Math.max(current, 1), totalPages)
    );
  }, [totalPages]);

  useEffect(() => {
    setCurrentPage(1);
  }, [showFavoritesOnly, pageSize, wallets.length]);

  const paginatedWallets = useMemo(() => {
    const startIndex = (currentPage - 1) * pageSize;
    const endIndex = startIndex + pageSize;

    return visibleWallets.slice(startIndex, endIndex);
  }, [visibleWallets, currentPage, pageSize]);

  const comparisonWallets = useMemo(
    () =>
      selectedWallets
        .map((address) =>
          wallets.find((wallet) => wallet.wallet === address)
        )
        .filter(Boolean),
    [selectedWallets, wallets]
  );

  const favoritesInRanking = useMemo(
    () =>
      wallets.filter((wallet) =>
        watchlist.includes(wallet.wallet)
      ).length,
    [wallets, watchlist]
  );

  const firstVisibleItem =
    visibleWallets.length === 0
      ? 0
      : (currentPage - 1) * pageSize + 1;

  const lastVisibleItem = Math.min(
    currentPage * pageSize,
    visibleWallets.length
  );

  function toggleFavorite(walletAddress) {
    setWatchlist((currentWatchlist) => {
      if (currentWatchlist.includes(walletAddress)) {
        return currentWatchlist.filter(
          (address) => address !== walletAddress
        );
      }

      return [...currentWatchlist, walletAddress];
    });
  }

  function toggleComparison(walletAddress) {
    setSelectedWallets((currentSelection) => {
      if (currentSelection.includes(walletAddress)) {
        return currentSelection.filter(
          (address) => address !== walletAddress
        );
      }

      if (currentSelection.length >= 3) {
        alert("Puoi confrontare al massimo 3 wallet");
        return currentSelection;
      }

      return [...currentSelection, walletAddress];
    });
  }

  function exportRankingCsv() {
    if (visibleWallets.length === 0) {
      alert("Nessun wallet da esportare");
      return;
    }

    const headers = [
      "Wallet",
      "Favorite",
      "Smart Score",
      "Classification",
      "ROI Percent",
      "Win Rate Percent",
      "Profit Loss SOL",
      "Traits",
    ];

    const rows = visibleWallets.map((wallet) => [
      wallet.wallet,
      watchlist.includes(wallet.wallet) ? "YES" : "NO",
      wallet.smart_score ?? 0,
      wallet.classification ?? "NORMAL",
      wallet.roi_percent ?? 0,
      wallet.win_rate_percent ?? 0,
      wallet.profit_loss_sol ?? 0,
      wallet.traits?.join(" | ") ?? "",
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
    link.download = `smart-wallet-ranking-${new Date()
      .toISOString()
      .slice(0, 10)}.csv`;

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    URL.revokeObjectURL(downloadUrl);
  }

  function goToPreviousPage() {
    setCurrentPage((current) => Math.max(1, current - 1));
  }

  function goToNextPage() {
    setCurrentPage((current) =>
      Math.min(totalPages, current + 1)
    );
  }

  return (
    <div className="space-y-6">
      {comparisonWallets.length > 0 && (
        <section className="overflow-hidden rounded-xl border border-blue-800 bg-slate-800">
          <div className="flex flex-col gap-3 border-b border-slate-700 p-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-xl font-bold">
                Wallet Comparison
              </h2>

              <p className="mt-1 text-sm text-slate-400">
                Confronto di {comparisonWallets.length} wallet su 3
              </p>
            </div>

            <button
              type="button"
              onClick={() => setSelectedWallets([])}
              className="rounded-lg border border-red-700 bg-red-900/30 px-4 py-2 text-sm font-semibold text-red-300 hover:bg-red-900/60"
            >
              Azzera confronto
            </button>
          </div>

          <div className="grid grid-cols-1 gap-4 p-5 lg:grid-cols-3">
            {comparisonWallets.map((wallet) => {
              const roiPositive =
                Number(wallet.roi_percent ?? 0) >= 0;

              const profitPositive =
                Number(wallet.profit_loss_sol ?? 0) >= 0;

              return (
                <article
                  key={wallet.wallet}
                  className="rounded-xl border border-slate-700 bg-slate-900 p-5"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs uppercase tracking-wide text-slate-500">
                        Wallet
                      </p>

                      <Link
                        to={`/wallet/${wallet.wallet}`}
                        className="mt-1 block truncate font-mono text-sm text-blue-400 hover:underline"
                        title={wallet.wallet}
                      >
                        {shortenAddress(wallet.wallet)}
                      </Link>
                    </div>

                    <button
                      type="button"
                      onClick={() =>
                        toggleComparison(wallet.wallet)
                      }
                      className="text-slate-500 hover:text-red-300"
                      title="Rimuovi dal confronto"
                    >
                      ✕
                    </button>
                  </div>

                  <div className="mt-5 grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-xs text-slate-500">
                        Smart Score
                      </p>

                      <p className="mt-1 text-xl font-bold text-blue-300">
                        {formatMetric(wallet.smart_score)}
                      </p>
                    </div>

                    <div>
                      <p className="text-xs text-slate-500">
                        Classificazione
                      </p>

                      <p className="mt-1 font-semibold text-purple-300">
                        {wallet.classification ?? "NORMAL"}
                      </p>
                    </div>

                    <div>
                      <p className="text-xs text-slate-500">
                        ROI
                      </p>

                      <p
                        className={`mt-1 text-lg font-bold ${
                          roiPositive
                            ? "text-green-300"
                            : "text-red-300"
                        }`}
                      >
                        {formatMetric(
                          wallet.roi_percent,
                          "%"
                        )}
                      </p>
                    </div>

                    <div>
                      <p className="text-xs text-slate-500">
                        Win Rate
                      </p>

                      <p className="mt-1 text-lg font-bold">
                        {formatMetric(
                          wallet.win_rate_percent,
                          "%"
                        )}
                      </p>
                    </div>

                    <div className="col-span-2">
                      <p className="text-xs text-slate-500">
                        Profit / Loss
                      </p>

                      <p
                        className={`mt-1 text-lg font-bold ${
                          profitPositive
                            ? "text-green-300"
                            : "text-red-300"
                        }`}
                      >
                        {formatMetric(
                          wallet.profit_loss_sol,
                          " SOL"
                        )}
                      </p>
                    </div>
                  </div>

                  <div className="mt-5 flex flex-wrap gap-2">
                    {wallet.traits?.length > 0 ? (
                      wallet.traits.map((trait) => (
                        <span
                          key={`${wallet.wallet}-${trait}`}
                          className="rounded-full bg-slate-700 px-2 py-1 text-xs text-slate-300"
                        >
                          {trait}
                        </span>
                      ))
                    ) : (
                      <span className="text-sm text-slate-500">
                        Nessun trait
                      </span>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}

      <div className="overflow-hidden rounded-xl bg-slate-800">
        <div className="flex flex-col gap-4 border-b border-slate-700 p-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="text-xl font-bold">
              Smart Wallet Ranking v4 
            </h2>

            <p className="mt-1 text-sm text-slate-400">
              {visibleWallets.length} wallet ·{" "}
              {favoritesInRanking} preferiti ·{" "}
              {selectedWallets.length}/3 in confronto
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-slate-400">
              Per pagina

              <select
                value={pageSize}
                onChange={(event) =>
                  setPageSize(Number(event.target.value))
                }
                className="rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-white outline-none focus:border-blue-500"
              >
                <option value={10}>10</option>
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </label>

            <button
              type="button"
              onClick={() =>
                setShowFavoritesOnly((current) => !current)
              }
              className={`rounded-lg border px-4 py-2 text-sm font-semibold ${
                showFavoritesOnly
                  ? "border-yellow-600 bg-yellow-900/40 text-yellow-300"
                  : "border-slate-600 bg-slate-700 text-slate-300 hover:bg-slate-600"
              }`}
            >
              {showFavoritesOnly
                ? "★ Solo preferiti"
                : "☆ Mostra preferiti"}
            </button>

            <button
              type="button"
              onClick={exportRankingCsv}
              disabled={visibleWallets.length === 0}
              className="rounded-lg border border-green-700 bg-green-900/40 px-4 py-2 text-sm font-semibold text-green-300 hover:bg-green-900/70 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Esporta CSV
            </button>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[1050px]">
            <thead className="bg-slate-700">
              <tr>
                <th className="p-4 text-center">Watch</th>
                <th className="p-4 text-center">Compare</th>
                <th className="p-4 text-left">Wallet</th>
                <th className="p-4">Score</th>
                <th className="p-4">DNA</th>
                <th className="p-4">ROI</th>
                <th className="p-4">Win Rate</th>
                <th className="p-4">Profit</th>
                <th className="p-4">Traits</th>
              </tr>
            </thead>

            <tbody>
              {paginatedWallets.length === 0 ? (
                <tr>
                  <td
                    colSpan={9}
                    className="p-8 text-center text-slate-400"
                  >
                    {showFavoritesOnly
                      ? "Nessun wallet presente nella watchlist."
                      : "Nessun wallet trovato."}
                  </td>
                </tr>
              ) : (
                paginatedWallets.map((wallet) => {
                  const isFavorite = watchlist.includes(
                    wallet.wallet
                  );

                  const isSelected =
                    selectedWallets.includes(wallet.wallet);

                  return (
                    <tr
                      key={wallet.wallet}
                      className={`border-t border-slate-700 hover:bg-slate-700 ${
                        isSelected ? "bg-blue-900/20" : ""
                      }`}
                    >
                      <td className="p-4 text-center">
                        <button
                          type="button"
                          onClick={() =>
                            toggleFavorite(wallet.wallet)
                          }
                          className={`text-2xl transition hover:scale-110 ${
                            isFavorite
                              ? "text-yellow-400"
                              : "text-slate-500 hover:text-yellow-300"
                          }`}
                          title={
                            isFavorite
                              ? "Rimuovi dalla watchlist"
                              : "Aggiungi alla watchlist"
                          }
                        >
                          {isFavorite ? "★" : "☆"}
                        </button>
                      </td>

                      <td className="p-4 text-center">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() =>
                            toggleComparison(wallet.wallet)
                          }
                          className="h-5 w-5 cursor-pointer accent-blue-600"
                          title="Aggiungi al confronto"
                        />
                      </td>

                      <td className="p-4 font-mono text-sm">
                        <Link
                          to={`/wallet/${wallet.wallet}`}
                          className="text-blue-400 hover:underline"
                          title={wallet.wallet}
                        >
                          {shortenAddress(wallet.wallet)}
                        </Link>
                      </td>

                      <td className="text-center font-bold text-green-400">
                        {wallet.smart_score ?? 0}
                      </td>

                      <td className="text-center">
                        <span className="rounded-full bg-purple-900/50 px-3 py-1 text-xs text-purple-300">
                          {wallet.classification ?? "NORMAL"}
                        </span>
                      </td>

                      <td
                        className={`text-center ${
                          (wallet.roi_percent ?? 0) >= 0
                            ? "text-green-300"
                            : "text-red-300"
                        }`}
                      >
                        {wallet.roi_percent ?? 0}%
                      </td>

                      <td className="text-center">
                        {wallet.win_rate_percent ?? 0}%
                      </td>

                      <td
                        className={`text-center ${
                          (wallet.profit_loss_sol ?? 0) >= 0
                            ? "text-green-300"
                            : "text-red-300"
                        }`}
                      >
                        {wallet.profit_loss_sol ?? 0} SOL
                      </td>

                      <td className="p-4">
                        <div className="flex flex-wrap gap-2">
                          {wallet.traits?.length > 0 ? (
                            wallet.traits.map((trait) => (
                              <span
                                key={`${wallet.wallet}-${trait}`}
                                className="rounded-full bg-slate-700 px-2 py-1 text-xs"
                              >
                                {trait}
                              </span>
                            ))
                          ) : (
                            <span className="text-slate-500">
                              -
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <div className="flex flex-col gap-4 border-t border-slate-700 p-5 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-slate-400">
            Visualizzati {firstVisibleItem}-{lastVisibleItem} di{" "}
            {visibleWallets.length}
          </p>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={goToPreviousPage}
              disabled={currentPage === 1}
              className="rounded-lg border border-slate-600 bg-slate-700 px-4 py-2 text-sm font-semibold hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              ← Precedente
            </button>

            <span className="text-sm text-slate-300">
              Pagina {currentPage} di {totalPages}
            </span>

            <button
              type="button"
              onClick={goToNextPage}
              disabled={currentPage === totalPages}
              className="rounded-lg border border-slate-600 bg-slate-700 px-4 py-2 text-sm font-semibold hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Successiva →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default WalletTable; 