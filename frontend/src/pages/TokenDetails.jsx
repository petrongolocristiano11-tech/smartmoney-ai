import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  Link,
  useParams,
} from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getTokenIntelligence } from "../services/api";

function shortenAddress(
  address,
  start = 10,
  end = 8
) {
  if (!address) {
    return "-";
  }

  if (address.length <= start + end + 3) {
    return address;
  }

  return `${address.slice(0, start)}...${address.slice(
    -end
  )}`;
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

function formatTimestamp(value) {
  if (!value) {
    return "-";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("it-IT");
}

function formatShortTimestamp(value) {
  if (!value) {
    return "";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toLocaleDateString("it-IT", {
    day: "2-digit",
    month: "2-digit",
  });
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

function MetricCard({
  label,
  value,
  valueClassName = "",
  subtitle = "",
}) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
      <p className="text-sm text-slate-400">
        {label}
      </p>

      <p
        className={`mt-2 text-2xl font-bold ${valueClassName}`}
      >
        {value}
      </p>

      {subtitle && (
        <p className="mt-2 text-xs text-slate-500">
          {subtitle}
        </p>
      )}
    </div>
  );
}

function FlowTooltip({
  active,
  payload,
}) {
  if (!active || !payload?.length) {
    return null;
  }

  const point = payload[0].payload;

  return (
    <div className="rounded-lg border border-slate-600 bg-slate-950 p-3 shadow-xl">
      <p className="text-xs text-slate-400">
        {formatTimestamp(point.timestamp)}
      </p>

      <p className="mt-2 font-semibold text-blue-300">
        Net buy:{" "}
        {formatNumber(
          point.cumulative_net_buy_sol,
          4
        )}{" "}
        SOL
      </p>

      <p className="mt-1 text-xs text-slate-300">
        {point.side} ·{" "}
        {formatNumber(point.sol_amount, 4)} SOL
      </p>
    </div>
  );
}

function TokenDetails() {
  const { tokenMint } = useParams();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] =
    useState(false);
  const [error, setError] = useState("");

  const [walletSearch, setWalletSearch] =
    useState("");
  const [smartOnly, setSmartOnly] =
    useState(false);

  const loadToken = useCallback(
    async (manualRefresh = false) => {
      if (manualRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }

      setError("");

      try {
        const response =
          await getTokenIntelligence(tokenMint);

        setData(response.data);
      } catch (requestError) {
        console.error(
          "Errore caricamento token:",
          requestError
        );

        const backendMessage =
          requestError.response?.data?.detail;

        setError(
          typeof backendMessage === "string"
            ? backendMessage
            : "Impossibile caricare il token."
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [tokenMint]
  );

  useEffect(() => {
    loadToken();
  }, [loadToken]);

  const wallets = data?.wallets ?? [];
  const recentTrades =
    data?.recent_trades ?? [];
  const timeline = data?.timeline ?? [];

  const filteredWallets = useMemo(() => {
    const normalizedSearch = walletSearch
      .trim()
      .toLowerCase();

    return wallets.filter((wallet) => {
      const matchesSmart =
        !smartOnly || wallet.is_smart;

      const matchesSearch =
        !normalizedSearch ||
        [
          wallet.wallet,
          wallet.classification,
          ...(wallet.traits ?? []),
        ].some((value) =>
          String(value ?? "")
            .toLowerCase()
            .includes(normalizedSearch)
        );

      return matchesSmart && matchesSearch;
    });
  }, [
    wallets,
    walletSearch,
    smartOnly,
  ]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-900 text-white">
        <div className="text-center">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-slate-700 border-t-blue-500" />

          <p className="mt-4 text-slate-400">
            Caricamento Token Intelligence...
          </p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-slate-900 p-6 text-white">
        <div className="mx-auto max-w-4xl">
          <Link
            to="/signals"
            className="text-blue-400 hover:underline"
          >
            ← Torna ai segnali
          </Link>

          <div className="mt-8 rounded-xl border border-red-700 bg-red-900/30 p-6 text-red-300">
            {error || "Token non trovato."}
          </div>
        </div>
      </div>
    );
  }

  const token = data.token ?? {};
  const score = data.score ?? {};
  const stats = data.stats ?? {};

  const netBuyPositive =
    Number(stats.net_buy_volume_sol) >= 0;

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 p-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <Link
              to="/signals"
              className="text-sm text-blue-400 hover:underline"
            >
              ← Torna ai segnali
            </Link>

            <h1 className="mt-3 text-3xl font-bold">
              {token.name ||
                token.symbol ||
                "Token Intelligence"}
            </h1>

            {token.symbol && (
              <p className="mt-1 text-lg font-semibold text-purple-300">
                {token.symbol}
              </p>
            )}

            <p
              className="mt-2 break-all font-mono text-sm text-slate-400"
              title={token.mint}
            >
              {token.mint}
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => loadToken(true)}
              disabled={refreshing}
              className="rounded-lg border border-slate-600 bg-slate-800 px-4 py-2 font-semibold hover:bg-slate-700 disabled:opacity-50"
            >
              {refreshing
                ? "Aggiornamento..."
                : "Aggiorna"}
            </button>

            <a
              href={`https://solscan.io/token/${token.mint}`}
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
          <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-sm uppercase tracking-wide text-slate-400">
                Token Score
              </p>

              <p className="mt-2 text-6xl font-bold text-blue-300">
                {formatNumber(
                  score.token_score,
                  2
                )}
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <span
                className={`rounded-full border px-5 py-2 font-bold ${getConfidenceClasses(
                  score.confidence
                )}`}
              >
                {score.confidence ?? "LOW"}
              </span>

              <span className="rounded-full border border-purple-700 bg-purple-900/40 px-5 py-2 font-bold text-purple-300">
                {stats.smart_wallets ?? 0} Smart Wallet
              </span>
            </div>
          </div>

          <div className="mt-6 grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
            <div>
              <span className="text-slate-500">
                Prima attività:{" "}
              </span>

              <span>
                {formatTimestamp(
                  stats.first_trade_at
                )}
              </span>
            </div>

            <div>
              <span className="text-slate-500">
                Ultima attività:{" "}
              </span>

              <span>
                {formatTimestamp(
                  stats.last_trade_at
                )}
              </span>
            </div>
          </div>
        </section>

        <section className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <MetricCard
            label="Smart Wallet"
            value={stats.smart_wallets ?? 0}
            valueClassName="text-purple-300"
            subtitle={`${stats.unique_wallets ?? 0} wallet totali`}
          />

          <MetricCard
            label="Trades"
            value={stats.total_trades ?? 0}
            subtitle={`${stats.buy_trades ?? 0} buy / ${
              stats.sell_trades ?? 0
            } sell`}
          />

          <MetricCard
            label="Volume"
            value={`${formatNumber(
              stats.total_volume_sol,
              4
            )} SOL`}
            valueClassName="text-blue-300"
          />

          <MetricCard
            label="Net Buy"
            value={`${formatNumber(
              stats.net_buy_volume_sol,
              4
            )} SOL`}
            valueClassName={
              netBuyPositive
                ? "text-green-300"
                : "text-red-300"
            }
          />

          <MetricCard
            label="Buy Pressure"
            value={`${formatNumber(
              score.buy_pressure_percent,
              2
            )}%`}
            valueClassName="text-green-300"
          />

          <MetricCard
            label="Score medio wallet"
            value={formatNumber(
              score.average_smart_score,
              2
            )}
          />

          <MetricCard
            label="ROI medio wallet"
            value={`${formatNumber(
              score.average_smart_roi,
              2
            )}%`}
          />

          <MetricCard
            label="Buyer unici"
            value={stats.unique_buyers ?? 0}
            subtitle={`${stats.unique_sellers ?? 0} seller unici`}
          />
        </section>

        <section className="mb-8 rounded-xl border border-slate-700 bg-slate-800 p-5">
          <div className="mb-5">
            <h2 className="text-xl font-bold">
              Smart Money Flow
            </h2>

            <p className="mt-1 text-sm text-slate-400">
              Flusso cumulativo: acquisti positivi,
              vendite negative
            </p>
          </div>

          {timeline.length === 0 ? (
            <div className="flex h-72 items-center justify-center text-slate-400">
              Nessun dato disponibile.
            </div>
          ) : (
            <div className="h-80 w-full">
              <ResponsiveContainer
                width="100%"
                height="100%"
              >
                <AreaChart
                  data={timeline}
                  margin={{
                    top: 10,
                    right: 10,
                    left: 0,
                    bottom: 0,
                  }}
                >
                  <defs>
                    <linearGradient
                      id="tokenFlowGradient"
                      x1="0"
                      y1="0"
                      x2="0"
                      y2="1"
                    >
                      <stop
                        offset="5%"
                        stopColor="#60a5fa"
                        stopOpacity={0.45}
                      />

                      <stop
                        offset="95%"
                        stopColor="#60a5fa"
                        stopOpacity={0}
                      />
                    </linearGradient>
                  </defs>

                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="#334155"
                  />

                  <XAxis
                    dataKey="timestamp"
                    tickFormatter={
                      formatShortTimestamp
                    }
                    stroke="#94a3b8"
                    tickLine={false}
                    axisLine={false}
                    minTickGap={30}
                  />

                  <YAxis
                    stroke="#94a3b8"
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(value) =>
                      formatNumber(value, 2)
                    }
                  />

                  <Tooltip
                    content={<FlowTooltip />}
                  />

                  <ReferenceLine
                    y={0}
                    stroke="#64748b"
                    strokeDasharray="4 4"
                  />

                  <Area
                    type="monotone"
                    dataKey="cumulative_net_buy_sol"
                    stroke="#60a5fa"
                    strokeWidth={2}
                    fill="url(#tokenFlowGradient)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        <section className="mb-8 overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="border-b border-slate-700 p-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h2 className="text-xl font-bold">
                  Wallet sul token
                </h2>

                <p className="mt-1 text-sm text-slate-400">
                  {filteredWallets.length} di{" "}
                  {wallets.length} wallet
                </p>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row">
                <input
                  type="text"
                  value={walletSearch}
                  onChange={(event) =>
                    setWalletSearch(
                      event.target.value
                    )
                  }
                  placeholder="Cerca wallet o classificazione..."
                  className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-2 outline-none focus:border-blue-500"
                />

                <label className="flex items-center gap-2 rounded-lg border border-slate-600 bg-slate-900 px-4 py-2 text-sm">
                  <input
                    type="checkbox"
                    checked={smartOnly}
                    onChange={(event) =>
                      setSmartOnly(
                        event.target.checked
                      )
                    }
                    className="h-4 w-4 accent-purple-600"
                  />

                  Solo smart
                </label>
              </div>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[1150px]">
              <thead className="bg-slate-700">
                <tr>
                  <th className="p-4 text-left">
                    Wallet
                  </th>
                  <th className="p-4">Smart</th>
                  <th className="p-4">Score</th>
                  <th className="p-4">DNA</th>
                  <th className="p-4">ROI</th>
                  <th className="p-4">
                    Buy / Sell
                  </th>
                  <th className="p-4">
                    Buy Volume
                  </th>
                  <th className="p-4">
                    Sell Volume
                  </th>
                  <th className="p-4">
                    Net Buy
                  </th>
                </tr>
              </thead>

              <tbody>
                {filteredWallets.length === 0 ? (
                  <tr>
                    <td
                      colSpan={9}
                      className="p-10 text-center text-slate-400"
                    >
                      Nessun wallet trovato.
                    </td>
                  </tr>
                ) : (
                  filteredWallets.map(
                    (wallet) => (
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
                            {shortenAddress(
                              wallet.wallet
                            )}
                          </Link>
                        </td>

                        <td className="text-center">
                          {wallet.is_smart ? (
                            <span className="rounded-full bg-purple-900/50 px-3 py-1 text-xs font-bold text-purple-300">
                              SMART
                            </span>
                          ) : (
                            <span className="text-slate-500">
                              -
                            </span>
                          )}
                        </td>

                        <td className="text-center font-bold text-blue-300">
                          {formatNumber(
                            wallet.smart_score,
                            2
                          )}
                        </td>

                        <td className="text-center text-purple-300">
                          {wallet.classification ??
                            "UNRANKED"}
                        </td>

                        <td
                          className={`text-center ${
                            Number(
                              wallet.roi_percent
                            ) >= 0
                              ? "text-green-300"
                              : "text-red-300"
                          }`}
                        >
                          {formatNumber(
                            wallet.roi_percent,
                            2
                          )}
                          %
                        </td>

                        <td className="text-center">
                          {wallet.buys ?? 0} /{" "}
                          {wallet.sells ?? 0}
                        </td>

                        <td className="text-center text-green-300">
                          {formatNumber(
                            wallet.buy_volume_sol,
                            4
                          )}{" "}
                          SOL
                        </td>

                        <td className="text-center text-red-300">
                          {formatNumber(
                            wallet.sell_volume_sol,
                            4
                          )}{" "}
                          SOL
                        </td>

                        <td
                          className={`text-center font-bold ${
                            Number(
                              wallet.net_buy_volume_sol
                            ) >= 0
                              ? "text-green-300"
                              : "text-red-300"
                          }`}
                        >
                          {formatNumber(
                            wallet.net_buy_volume_sol,
                            4
                          )}{" "}
                          SOL
                        </td>
                      </tr>
                    )
                  )
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="border-b border-slate-700 p-5">
            <h2 className="text-xl font-bold">
              Ultime transazioni
            </h2>

            <p className="mt-1 text-sm text-slate-400">
              Ultimi {recentTrades.length} trade
              registrati
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[1000px]">
              <thead className="bg-slate-700">
                <tr>
                  <th className="p-4 text-left">
                    Data
                  </th>
                  <th className="p-4 text-left">
                    Side
                  </th>
                  <th className="p-4 text-left">
                    Wallet
                  </th>
                  <th className="p-4 text-right">
                    Token
                  </th>
                  <th className="p-4 text-right">
                    SOL
                  </th>
                  <th className="p-4">
                    Source
                  </th>
                  <th className="p-4">Tx</th>
                </tr>
              </thead>

              <tbody>
                {recentTrades.length === 0 ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="p-10 text-center text-slate-400"
                    >
                      Nessuna transazione trovata.
                    </td>
                  </tr>
                ) : (
                  recentTrades.map((trade) => (
                    <tr
                      key={trade.id}
                      className="border-t border-slate-700 hover:bg-slate-700/60"
                    >
                      <td className="p-4 text-sm text-slate-400">
                        {formatTimestamp(
                          trade.timestamp
                        )}
                      </td>

                      <td className="p-4">
                        <span
                          className={`rounded-full px-3 py-1 text-xs font-bold ${
                            trade.side === "BUY"
                              ? "bg-green-900/50 text-green-300"
                              : "bg-red-900/50 text-red-300"
                          }`}
                        >
                          {trade.side ?? "-"}
                        </span>
                      </td>

                      <td className="p-4 font-mono text-sm">
                        <Link
                          to={`/wallet/${trade.wallet}`}
                          className="text-blue-400 hover:underline"
                          title={trade.wallet}
                        >
                          {shortenAddress(
                            trade.wallet
                          )}
                        </Link>
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

                      <td className="p-4 text-center">
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

export default TokenDetails; 