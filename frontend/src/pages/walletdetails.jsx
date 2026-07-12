import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import WalletActivityChart from "../components/WalletActivityChart";
import WalletNetworkGraph from "../components/WalletNetworkGraph";

import {
  getWalletNetwork,
  getWalletProfile,
  getWalletTrades,
} from "../services/api";

function shortenAddress(address, start = 10, end = 8) {
  if (!address) return "-";

  if (address.length <= start + end + 3) {
    return address;
  }

  return `${address.slice(0, start)}...${address.slice(-end)}`;
}

function formatNumber(value, maximumFractionDigits = 4) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "0";
  }

  return number.toLocaleString("it-IT", {
    maximumFractionDigits,
  });
}

function getClassificationClasses(classification) {
  switch (classification) {
    case "SNIPER":
      return "border-purple-700 bg-purple-900/40 text-purple-300";

    case "SMART":
    case "SMART_MONEY":
      return "border-green-700 bg-green-900/40 text-green-300";

    default:
      return "border-slate-600 bg-slate-700 text-slate-300";
  }
}

function MetricCard({ label, value, valueClassName = "" }) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
      <p className="text-sm text-slate-400">{label}</p>

      <p className={`mt-2 text-2xl font-bold ${valueClassName}`}>
        {value}
      </p>
    </div>
  );
}

function WalletDetails() {
  const { walletAddress } = useParams();

  const [wallet, setWallet] = useState(null);
  const [trades, setTrades] = useState([]);
  const [network, setNetwork] = useState([]);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const [tradeSearch, setTradeSearch] = useState("");
  const [sideFilter, setSideFilter] = useState("ALL");

  async function loadWalletData(showRefreshing = false) {
    if (showRefreshing) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    setError("");

    try {
      const [profileResult, tradesResult, networkResult] =
        await Promise.allSettled([
          getWalletProfile(walletAddress),
          getWalletTrades(walletAddress),
          getWalletNetwork(walletAddress),
        ]);

      if (profileResult.status === "fulfilled") {
        setWallet(profileResult.value.data);
      } else {
        console.error(
          "Errore caricamento profilo:",
          profileResult.reason
        );

        setWallet(null);
      }

      if (tradesResult.status === "fulfilled") {
        const tradesData = tradesResult.value.data;

        setTrades(
          Array.isArray(tradesData)
            ? tradesData
            : tradesData?.trades ?? []
        );
      } else {
        console.error(
          "Errore caricamento trades:",
          tradesResult.reason
        );

        setTrades([]);
      }

      if (networkResult.status === "fulfilled") {
        setNetwork(
          networkResult.value.data?.connected_wallets ?? []
        );
      } else {
        console.error(
          "Errore caricamento network:",
          networkResult.reason
        );

        setNetwork([]);
      }

      if (profileResult.status === "rejected") {
        setError(
          "Impossibile caricare questo wallet. Controlla che il backend sia avviato e che l'indirizzo esista."
        );
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    loadWalletData();
  }, [walletAddress]);

  const filteredTrades = useMemo(() => {
    const normalizedSearch = tradeSearch.trim().toLowerCase();

    return trades.filter((trade) => {
      const matchesSide =
        sideFilter === "ALL" || trade.side === sideFilter;

      const matchesSearch =
        !normalizedSearch ||
        (trade.token_mint ?? "")
          .toLowerCase()
          .includes(normalizedSearch) ||
        (trade.signature ?? "")
          .toLowerCase()
          .includes(normalizedSearch);

      return matchesSide && matchesSearch;
    });
  }, [trades, tradeSearch, sideFilter]);

  const tradeStats = useMemo(() => {
    return trades.reduce(
      (stats, trade) => {
        const solAmount = Number(trade.sol_amount) || 0;

        stats.total += 1;
        stats.volume += solAmount;

        if (trade.side === "BUY") {
          stats.buys += 1;
        }

        if (trade.side === "SELL") {
          stats.sells += 1;
        }

        return stats;
      },
      {
        total: 0,
        buys: 0,
        sells: 0,
        volume: 0,
      }
    );
  }, [trades]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-900 text-white">
        <div className="text-center">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-slate-700 border-t-blue-500" />

          <p className="mt-4 text-slate-400">
            Caricamento wallet...
          </p>
        </div>
      </div>
    );
  }

  if (error || !wallet) {
    return (
      <div className="min-h-screen bg-slate-900 p-6 text-white">
        <div className="mx-auto max-w-4xl">
          <Link
            to="/"
            className="text-blue-400 hover:underline"
          >
            ← Torna alla dashboard
          </Link>

          <div className="mt-8 rounded-xl border border-red-700 bg-red-900/30 p-6 text-red-300">
            {error || "Wallet non trovato."}
          </div>
        </div>
      </div>
    );
  }

  const roiPositive = Number(wallet.roi_percent) >= 0;
  const profitPositive =
    Number(wallet.profit_loss_sol) >= 0;

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
              Wallet Intelligence
            </h1>

            <p
              className="mt-2 break-all font-mono text-sm text-slate-400"
              title={wallet.wallet}
            >
              {wallet.wallet}
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => loadWalletData(true)}
              disabled={refreshing}
              className="rounded-lg border border-slate-600 bg-slate-800 px-4 py-2 font-semibold hover:bg-slate-700 disabled:opacity-50"
            >
              {refreshing
                ? "Aggiornamento..."
                : "Aggiorna"}
            </button>

            <a
              href={`https://solscan.io/account/${wallet.wallet}`}
              target="_blank"
              rel="noreferrer"
              className="rounded-lg bg-blue-600 px-4 py-2 font-semibold hover:bg-blue-700"
            >
              Apri su Solscan
            </a>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl p-4 sm:p-8">
        <section className="mb-8 rounded-xl border border-slate-700 bg-slate-800 p-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm text-slate-400">
                Wallet
              </p>

              <p className="mt-1 font-mono text-lg">
                {shortenAddress(wallet.wallet, 14, 12)}
              </p>
            </div>

            <span
              className={`w-fit rounded-full border px-4 py-2 text-sm font-semibold ${getClassificationClasses(
                wallet.classification
              )}`}
            >
              {wallet.classification ?? "NORMAL"}
            </span>
          </div>

          {wallet.traits?.length > 0 && (
            <div className="mt-6 flex flex-wrap gap-2">
              {wallet.traits.map((trait) => (
                <span
                  key={trait}
                  className="rounded-full bg-slate-700 px-3 py-1 text-sm text-slate-300"
                >
                  {trait}
                </span>
              ))}
            </div>
          )}
        </section>

        <section className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <MetricCard
            label="Smart Score"
            value={formatNumber(wallet.smart_score, 2)}
            valueClassName="text-blue-300"
          />

          <MetricCard
            label="ROI"
            value={`${formatNumber(
              wallet.roi_percent,
              2
            )}%`}
            valueClassName={
              roiPositive
                ? "text-green-400"
                : "text-red-400"
            }
          />

          <MetricCard
            label="Win Rate"
            value={`${formatNumber(
              wallet.win_rate_percent,
              2
            )}%`}
            valueClassName="text-purple-300"
          />

          <MetricCard
            label="Profit / Loss"
            value={`${formatNumber(
              wallet.profit_loss_sol,
              4
            )} SOL`}
            valueClassName={
              profitPositive
                ? "text-green-400"
                : "text-red-400"
            }
          />

          <MetricCard
            label="Reliable Positions"
            value={formatNumber(wallet.activity, 0)}
          />

          <MetricCard
            label="Trades"
            value={tradeStats.total}
          />

          <MetricCard
            label="Buy / Sell"
            value={`${tradeStats.buys} / ${tradeStats.sells}`}
          />

          <MetricCard
            label="Volume analizzato"
            value={`${formatNumber(
              tradeStats.volume,
              4
            )} SOL`}
          />
        </section>

        <WalletActivityChart trades={trades} />

        <WalletNetworkGraph
          walletAddress={wallet.wallet}
          connectedWallets={network}
        />

        <section className="mb-8 overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="flex items-center justify-between border-b border-slate-700 p-5">
            <div>
              <h2 className="text-xl font-bold">
                Connected Smart Wallets
              </h2>

              <p className="mt-1 text-sm text-slate-400">
                Wallet collegati attraverso token condivisi
              </p>
            </div>

            <span className="rounded-full bg-purple-900/40 px-3 py-1 text-sm text-purple-300">
              {network.length}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[850px]">
              <thead className="bg-slate-700">
                <tr>
                  <th className="p-4 text-left">Wallet</th>
                  <th className="p-4 text-center">
                    Shared Tokens
                  </th>
                  <th className="p-4 text-center">
                    Connection
                  </th>
                  <th className="p-4 text-center">Score</th>
                  <th className="p-4 text-center">ROI</th>
                  <th className="p-4 text-center">
                    Win Rate
                  </th>
                </tr>
              </thead>

              <tbody>
                {network.length === 0 ? (
                  <tr>
                    <td
                      colSpan={6}
                      className="p-8 text-center text-slate-400"
                    >
                      Nessun wallet collegato trovato.
                    </td>
                  </tr>
                ) : (
                  network.map((item) => (
                    <tr
                      key={item.wallet}
                      className="border-t border-slate-700 hover:bg-slate-700/60"
                    >
                      <td className="p-4 font-mono text-sm">
                        <Link
                          to={`/wallet/${item.wallet}`}
                          className="text-blue-400 hover:underline"
                          title={item.wallet}
                        >
                          {shortenAddress(item.wallet)}
                        </Link>
                      </td>

                      <td className="text-center">
                        {item.shared_tokens ?? 0}
                      </td>

                      <td className="text-center font-bold text-purple-400">
                        {formatNumber(
                          item.connection_strength,
                          2
                        )}
                      </td>

                      <td className="text-center font-bold">
                        {formatNumber(item.smart_score, 2)}
                      </td>

                      <td
                        className={`text-center ${
                          Number(item.roi_percent) >= 0
                            ? "text-green-300"
                            : "text-red-300"
                        }`}
                      >
                        {formatNumber(
                          item.roi_percent,
                          2
                        )}
                        %
                      </td>

                      <td className="text-center">
                        {formatNumber(
                          item.win_rate_percent,
                          2
                        )}
                        %
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="border-b border-slate-700 p-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h2 className="text-xl font-bold">
                  Trade History
                </h2>

                <p className="mt-1 text-sm text-slate-400">
                  {filteredTrades.length} di {trades.length} trade
                </p>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row">
                <input
                  type="text"
                  value={tradeSearch}
                  onChange={(event) =>
                    setTradeSearch(event.target.value)
                  }
                  placeholder="Cerca token o transazione..."
                  className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-2 outline-none focus:border-blue-500"
                />

                <select
                  value={sideFilter}
                  onChange={(event) =>
                    setSideFilter(event.target.value)
                  }
                  className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-2 outline-none focus:border-blue-500"
                >
                  <option value="ALL">Tutti</option>
                  <option value="BUY">Buy</option>
                  <option value="SELL">Sell</option>
                </select>
              </div>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[850px]">
              <thead className="bg-slate-700">
                <tr>
                  <th className="p-4 text-left">Side</th>
                  <th className="p-4 text-left">Token</th>
                  <th className="p-4 text-right">
                    Token Amount
                  </th>
                  <th className="p-4 text-right">SOL</th>
                  <th className="p-4 text-left">Source</th>
                  <th className="p-4 text-center">Tx</th>
                </tr>
              </thead>

              <tbody>
                {filteredTrades.length === 0 ? (
                  <tr>
                    <td
                      colSpan={6}
                      className="p-8 text-center text-slate-400"
                    >
                      Nessun trade trovato.
                    </td>
                  </tr>
                ) : (
                  filteredTrades.map((trade, index) => (
                    <tr
                      key={
                        trade.signature ??
                        trade.id ??
                        index
                      }
                      className="border-t border-slate-700 hover:bg-slate-700/60"
                    >
                      <td className="p-4">
                        <span
                          className={`rounded-full px-3 py-1 text-sm font-semibold ${
                            trade.side === "BUY"
                              ? "bg-green-900/60 text-green-300"
                              : "bg-red-900/60 text-red-300"
                          }`}
                        >
                          {trade.side ?? "-"}
                        </span>
                      </td>

                      <td
                        className="p-4 font-mono text-sm"
                        title={trade.token_mint}
                      >
                        <a
                          href={`https://solscan.io/token/${trade.token_mint}`}
                          target="_blank"
                          rel="noreferrer"
                          className="text-blue-300 hover:underline"
                        >
                          {shortenAddress(
                            trade.token_mint,
                            10,
                            8
                          )}
                        </a>
                      </td>

                      <td className="p-4 text-right">
                        {formatNumber(
                          trade.token_amount,
                          4
                        )}
                      </td>

                      <td className="p-4 text-right font-semibold">
                        {formatNumber(
                          trade.sol_amount,
                          4
                        )}
                      </td>

                      <td className="p-4">
                        {trade.source ?? "-"}
                      </td>

                      <td className="p-4 text-center">
                        {trade.signature ? (
                          <a
                            href={`https://solscan.io/tx/${trade.signature}`}
                            target="_blank"
                            rel="noreferrer"
                            className="text-blue-400 hover:underline"
                          >
                            View
                          </a>
                        ) : (
                          "-"
                        )}
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

export default WalletDetails; 