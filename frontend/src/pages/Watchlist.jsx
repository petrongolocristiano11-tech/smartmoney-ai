import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getWalletRanking } from "../services/api";

const WATCHLIST_STORAGE_KEY = "smartmoney-wallet-watchlist";

function shortenAddress(address, start = 10, end = 8) {
  if (!address) return "-";

  if (address.length <= start + end + 3) {
    return address;
  }

  return `${address.slice(0, start)}...${address.slice(-end)}`;
}

function loadStoredWatchlist() {
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

function Watchlist() {
  const [watchlist, setWatchlist] = useState(loadStoredWatchlist);
  const [wallets, setWallets] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadWallets() {
    setLoading(true);
    setError("");

    try {
      const response = await getWalletRanking();
      setWallets(response.data.ranking ?? []);
    } catch (requestError) {
      console.error(
        "Errore caricamento watchlist:",
        requestError
      );

      setError(
        "Impossibile caricare i dati dei wallet dal backend."
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadWallets();
  }, []);

  useEffect(() => {
    window.localStorage.setItem(
      WATCHLIST_STORAGE_KEY,
      JSON.stringify(watchlist)
    );
  }, [watchlist]);

  const favoriteWallets = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();

    return wallets.filter((wallet) => {
      const isFavorite = watchlist.includes(wallet.wallet);

      const matchesSearch =
        !normalizedSearch ||
        (wallet.wallet ?? "")
          .toLowerCase()
          .includes(normalizedSearch) ||
        (wallet.classification ?? "")
          .toLowerCase()
          .includes(normalizedSearch);

      return isFavorite && matchesSearch;
    });
  }, [wallets, watchlist, search]);

  function removeWallet(walletAddress) {
    setWatchlist((currentWatchlist) =>
      currentWatchlist.filter(
        (address) => address !== walletAddress
      )
    );
  }

  function clearWatchlist() {
    if (watchlist.length === 0) {
      return;
    }

    const confirmed = window.confirm(
      "Vuoi rimuovere tutti i wallet dalla watchlist?"
    );

    if (confirmed) {
      setWatchlist([]);
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 p-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-3xl font-bold">
              Wallet Watchlist
            </h1>

            <p className="mt-2 text-slate-400">
              Monitora e confronta i wallet salvati
            </p>
          </div>

          <button
            type="button"
            onClick={loadWallets}
            disabled={loading}
            className="w-fit rounded-lg border border-blue-700 bg-blue-900/40 px-4 py-2 text-sm font-semibold text-blue-300 hover:bg-blue-900/70 disabled:opacity-50"
          >
            {loading ? "Aggiornamento..." : "Aggiorna"}
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-7xl p-4 sm:p-8">
        {error && (
          <div className="mb-6 rounded-lg border border-red-700 bg-red-900/30 p-4 text-red-300">
            {error}
          </div>
        )}

        <section className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Wallet salvati
            </p>

            <p className="mt-2 text-3xl font-bold text-yellow-300">
              {watchlist.length}
            </p>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Wallet disponibili
            </p>

            <p className="mt-2 text-3xl font-bold text-blue-300">
              {favoriteWallets.length}
            </p>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Miglior Smart Score
            </p>

            <p className="mt-2 text-3xl font-bold text-green-300">
              {favoriteWallets.length
                ? Math.max(
                    ...favoriteWallets.map(
                      (wallet) =>
                        Number(wallet.smart_score) || 0
                    )
                  )
                : "-"}
            </p>
          </div>
        </section>

        <section className="mb-6 flex flex-col gap-4 rounded-xl border border-slate-700 bg-slate-800 p-5 sm:flex-row sm:items-center sm:justify-between">
          <input
            type="text"
            value={search}
            onChange={(event) =>
              setSearch(event.target.value)
            }
            placeholder="Cerca wallet o classificazione..."
            className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-blue-500 sm:max-w-lg"
          />

          <button
            type="button"
            onClick={clearWatchlist}
            disabled={watchlist.length === 0}
            className="rounded-lg border border-red-700 bg-red-900/30 px-4 py-3 text-sm font-semibold text-red-300 hover:bg-red-900/60 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Svuota watchlist
          </button>
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="border-b border-slate-700 p-5">
            <h2 className="text-xl font-bold">
              Wallet monitorati
            </h2>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px]">
              <thead className="bg-slate-700">
                <tr>
                  <th className="p-4 text-left">Wallet</th>
                  <th className="p-4 text-center">Score</th>
                  <th className="p-4 text-center">DNA</th>
                  <th className="p-4 text-center">ROI</th>
                  <th className="p-4 text-center">
                    Win Rate
                  </th>
                  <th className="p-4 text-center">Profit</th>
                  <th className="p-4 text-center">Azioni</th>
                </tr>
              </thead>

              <tbody>
                {loading ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="p-10 text-center text-slate-400"
                    >
                      Caricamento watchlist...
                    </td>
                  </tr>
                ) : favoriteWallets.length === 0 ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="p-10 text-center text-slate-400"
                    >
                      Nessun wallet presente nella watchlist.
                    </td>
                  </tr>
                ) : (
                  favoriteWallets.map((wallet) => (
                    <tr
                      key={wallet.wallet}
                      className="border-t border-slate-700 hover:bg-slate-700/60"
                    >
                      <td className="p-4 font-mono text-sm">
                        <Link
                          to={`/wallet/${wallet.wallet}`}
                          className="text-blue-400 hover:underline"
                          title={wallet.wallet}
                        >
                          {shortenAddress(wallet.wallet)}
                        </Link>
                      </td>

                      <td className="text-center font-bold text-green-300">
                        {wallet.smart_score ?? 0}
                      </td>

                      <td className="text-center">
                        <span className="rounded-full bg-purple-900/50 px-3 py-1 text-xs text-purple-300">
                          {wallet.classification ?? "NORMAL"}
                        </span>
                      </td>

                      <td
                        className={`text-center ${
                          Number(wallet.roi_percent) >= 0
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
                          Number(wallet.profit_loss_sol) >= 0
                            ? "text-green-300"
                            : "text-red-300"
                        }`}
                      >
                        {wallet.profit_loss_sol ?? 0} SOL
                      </td>

                      <td className="p-4 text-center">
                        <button
                          type="button"
                          onClick={() =>
                            removeWallet(wallet.wallet)
                          }
                          className="rounded-lg border border-red-700 bg-red-900/30 px-3 py-2 text-sm text-red-300 hover:bg-red-900/60"
                        >
                          Rimuovi
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}

export default Watchlist; 