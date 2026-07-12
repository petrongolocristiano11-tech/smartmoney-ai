import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  Link,
  useNavigate,
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

import {
  getWalletPortfolio,
  getWalletProfile,
  getWalletRanking,
  getWalletTrades,
} from "../services/api";

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
    return String(value);
  }

  return date.toLocaleString("it-IT");
}

function formatShortDate(value) {
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

function MetricCard({
  label,
  value,
  subtitle = "",
  valueClassName = "",
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

function CashFlowTooltip({
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

      <p
        className={`mt-2 font-bold ${
          point.netCashFlow >= 0
            ? "text-green-300"
            : "text-red-300"
        }`}
      >
        Flusso netto:{" "}
        {formatNumber(point.netCashFlow, 4)} SOL
      </p>

      <p className="mt-1 text-xs text-slate-300">
        {point.side} ·{" "}
        {formatNumber(point.solAmount, 4)} SOL
      </p>
    </div>
  );
}

function getPositionStatus(position) {
  const holding = Number(
    position.holding_amount ?? 0
  );

  if (holding > 0.00000001) {
    return "OPEN";
  }

  if (holding < -0.00000001) {
    return "INCOMPLETE";
  }

  return "CLOSED";
}

function getPositionStatusClasses(status) {
  switch (status) {
    case "OPEN":
      return "bg-green-900/50 text-green-300";

    case "INCOMPLETE":
      return "bg-yellow-900/50 text-yellow-300";

    default:
      return "bg-slate-700 text-slate-300";
  }
}

function Portfolio() {
  const { walletAddress } = useParams();
  const navigate = useNavigate();

  const [walletInput, setWalletInput] =
    useState(walletAddress ?? "");

  const [portfolio, setPortfolio] =
    useState(null);
  const [profile, setProfile] = useState(null);
  const [trades, setTrades] = useState([]);
  const [ranking, setRanking] = useState([]);

  const [positionSearch, setPositionSearch] =
    useState("");
  const [positionStatus, setPositionStatus] =
    useState("ALL");

  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] =
    useState(false);
  const [rankingLoading, setRankingLoading] =
    useState(true);
  const [error, setError] = useState("");
  const [warning, setWarning] = useState("");
  const [lastUpdated, setLastUpdated] =
    useState(null);

  useEffect(() => {
    setWalletInput(walletAddress ?? "");
  }, [walletAddress]);

  const loadRanking = useCallback(async () => {
    setRankingLoading(true);

    try {
      const response = await getWalletRanking();

      setRanking(
        response.data?.ranking?.slice(0, 10) ?? []
      );
    } catch (requestError) {
      console.error(
        "Errore caricamento wallet suggeriti:",
        requestError
      );
    } finally {
      setRankingLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRanking();
  }, [loadRanking]);

  const loadPortfolio = useCallback(
    async (manualRefresh = false) => {
      if (!walletAddress) {
        setPortfolio(null);
        setProfile(null);
        setTrades([]);
        return;
      }

      if (manualRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }

      setError("");
      setWarning("");
      setPortfolio(null);
      setProfile(null);
      setTrades([]);

      try {
        const [
          portfolioResult,
          profileResult,
          tradesResult,
        ] = await Promise.allSettled([
          getWalletPortfolio(walletAddress),
          getWalletProfile(walletAddress),
          getWalletTrades(walletAddress),
        ]);

        if (portfolioResult.status === "fulfilled") {
          setPortfolio(portfolioResult.value.data);
        } else {
          console.error(
            "Errore caricamento portfolio:",
            portfolioResult.reason
          );

          setError(
            "Impossibile caricare il portfolio del wallet."
          );
        }

        if (profileResult.status === "fulfilled") {
          setProfile(profileResult.value.data);
        } else {
          console.error(
            "Errore caricamento profilo:",
            profileResult.reason
          );

          setWarning(
            "Portfolio caricato, ma il profilo analytics non è disponibile."
          );
        }

        if (tradesResult.status === "fulfilled") {
          const tradeData = tradesResult.value.data;

          setTrades(
            Array.isArray(tradeData)
              ? tradeData
              : tradeData?.trades ?? []
          );
        } else {
          console.error(
            "Errore caricamento trades:",
            tradesResult.reason
          );

          setWarning(
            "Alcuni dati storici del wallet non sono disponibili."
          );
        }

        if (
          portfolioResult.status === "fulfilled" ||
          profileResult.status === "fulfilled" ||
          tradesResult.status === "fulfilled"
        ) {
          setLastUpdated(new Date());
        }
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [walletAddress]
  );

  useEffect(() => {
    loadPortfolio();
  }, [loadPortfolio]);

  const enrichedPositions = useMemo(() => {
    const positions = portfolio?.positions ?? [];

    return positions
      .map((position) => {
        const boughtAmount = Number(
          position.bought_amount ?? 0
        );

        const soldAmount = Number(
          position.sold_amount ?? 0
        );

        const holdingAmount = Number(
          position.holding_amount ?? 0
        );

        const totalSpent = Number(
          position.total_sol_spent ?? 0
        );

        const totalReceived = Number(
          position.total_sol_received ?? 0
        );

        return {
          ...position,
          boughtAmount,
          soldAmount,
          holdingAmount,
          totalSpent,
          totalReceived,
          netCashFlow:
            totalReceived - totalSpent,
          averageBuyPrice:
            boughtAmount > 0
              ? totalSpent / boughtAmount
              : 0,
          averageSellPrice:
            soldAmount > 0
              ? totalReceived / soldAmount
              : 0,
          status: getPositionStatus(position),
        };
      })
      .sort((first, second) => {
        const statusPriority = {
          OPEN: 3,
          INCOMPLETE: 2,
          CLOSED: 1,
        };

        const statusDifference =
          statusPriority[second.status] -
          statusPriority[first.status];

        if (statusDifference !== 0) {
          return statusDifference;
        }

        return (
          Math.abs(second.netCashFlow) -
          Math.abs(first.netCashFlow)
        );
      });
  }, [portfolio]);

  const filteredPositions = useMemo(() => {
    const normalizedSearch = positionSearch
      .trim()
      .toLowerCase();

    return enrichedPositions.filter(
      (position) => {
        const matchesStatus =
          positionStatus === "ALL" ||
          position.status === positionStatus;

        const matchesSearch =
          !normalizedSearch ||
          String(position.token_mint ?? "")
            .toLowerCase()
            .includes(normalizedSearch);

        return matchesStatus && matchesSearch;
      }
    );
  }, [
    enrichedPositions,
    positionSearch,
    positionStatus,
  ]);

  const summary = useMemo(() => {
    return enrichedPositions.reduce(
      (result, position) => {
        result.totalSpent += position.totalSpent;
        result.totalReceived +=
          position.totalReceived;

        if (position.status === "OPEN") {
          result.openPositions += 1;

          result.openCapital += Math.max(
            position.totalSpent -
              position.totalReceived,
            0
          );
        }

        if (position.status === "CLOSED") {
          result.closedPositions += 1;
          result.closedCashFlow +=
            position.netCashFlow;
        }

        if (position.status === "INCOMPLETE") {
          result.incompletePositions += 1;
        }

        return result;
      },
      {
        totalSpent: 0,
        totalReceived: 0,
        openCapital: 0,
        closedCashFlow: 0,
        openPositions: 0,
        closedPositions: 0,
        incompletePositions: 0,
      }
    );
  }, [enrichedPositions]);

  const netCashFlow =
    summary.totalReceived - summary.totalSpent;

  const cashFlowTimeline = useMemo(() => {
    const orderedTrades = [...trades].sort(
      (first, second) => {
        const firstTimestamp = new Date(
          first.block_time ??
            first.created_at ??
            0
        ).getTime();

        const secondTimestamp = new Date(
          second.block_time ??
            second.created_at ??
            0
        ).getTime();

        return firstTimestamp - secondTimestamp;
      }
    );

    let cumulativeSpent = 0;
    let cumulativeReceived = 0;

    return orderedTrades.map((trade, index) => {
      const solAmount =
        Number(trade.sol_amount) || 0;

      if (trade.side === "BUY") {
        cumulativeSpent += solAmount;
      }

      if (trade.side === "SELL") {
        cumulativeReceived += solAmount;
      }

      const timestamp =
        trade.block_time ?? trade.created_at;

      return {
        id: trade.id ?? index,
        timestamp,
        shortDate: formatShortDate(timestamp),
        side: trade.side ?? "UNKNOWN",
        solAmount,
        spent: Number(
          cumulativeSpent.toFixed(6)
        ),
        received: Number(
          cumulativeReceived.toFixed(6)
        ),
        netCashFlow: Number(
          (
            cumulativeReceived -
            cumulativeSpent
          ).toFixed(6)
        ),
      };
    });
  }, [trades]);

  const recentTrades = useMemo(() => {
    return [...trades]
      .sort((first, second) => {
        const firstTimestamp = new Date(
          first.block_time ??
            first.created_at ??
            0
        ).getTime();

        const secondTimestamp = new Date(
          second.block_time ??
            second.created_at ??
            0
        ).getTime();

        return secondTimestamp - firstTimestamp;
      })
      .slice(0, 30);
  }, [trades]);

  function handleSubmit(event) {
    event.preventDefault();

    const normalizedWallet =
      walletInput.trim();

    if (!normalizedWallet) {
      alert("Inserisci un wallet");
      return;
    }

    navigate(`/portfolio/${normalizedWallet}`);
  }

  function selectWallet(address) {
    setWalletInput(address);
    navigate(`/portfolio/${address}`);
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 p-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-3xl font-bold">
              Portfolio Tracker
            </h1>

            <p className="mt-2 text-slate-400">
              Posizioni, flussi SOL e performance
              storica dei wallet
            </p>
          </div>

          {walletAddress && (
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-sm text-slate-400">
                Ultimo aggiornamento:{" "}
                {lastUpdated
                  ? lastUpdated.toLocaleTimeString(
                      "it-IT"
                    )
                  : "-"}
              </p>

              <button
                type="button"
                onClick={() => loadPortfolio(true)}
                disabled={refreshing}
                className="rounded-lg border border-blue-700 bg-blue-900/40 px-4 py-2 text-sm font-semibold text-blue-300 hover:bg-blue-900/70 disabled:opacity-50"
              >
                {refreshing
                  ? "Aggiornamento..."
                  : "Aggiorna"}
              </button>
            </div>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-7xl p-4 sm:p-8">
        <form
          onSubmit={handleSubmit}
          className="mb-8 flex flex-col gap-3 rounded-xl border border-slate-700 bg-slate-800 p-5 lg:flex-row"
        >
          <input
            type="text"
            value={walletInput}
            onChange={(event) =>
              setWalletInput(event.target.value)
            }
            placeholder="Inserisci wallet address..."
            className="min-w-0 flex-1 rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 font-mono outline-none focus:border-blue-500"
          />

          <button
            type="submit"
            className="rounded-lg bg-blue-600 px-6 py-3 font-semibold hover:bg-blue-700"
          >
            Analizza Portfolio
          </button>
        </form>

        {error && (
          <div className="mb-6 rounded-lg border border-red-700 bg-red-900/30 p-4 text-red-300">
            {error}
          </div>
        )}

        {warning && (
          <div className="mb-6 rounded-lg border border-yellow-700 bg-yellow-900/30 p-4 text-yellow-300">
            {warning}
          </div>
        )}

        {!walletAddress && (
          <>
            <section className="mb-8 rounded-xl border border-blue-800 bg-blue-950/20 p-6">
              <h2 className="text-xl font-bold">
                Seleziona un wallet
              </h2>

              <p className="mt-2 text-slate-400">
                Inserisci un indirizzo oppure scegli uno
                dei wallet migliori del ranking.
              </p>
            </section>

            <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
              <div className="border-b border-slate-700 p-5">
                <h2 className="text-xl font-bold">
                  Wallet suggeriti
                </h2>
              </div>

              <div className="divide-y divide-slate-700">
                {rankingLoading ? (
                  <p className="p-8 text-center text-slate-400">
                    Caricamento wallet...
                  </p>
                ) : (
                  ranking.map((wallet, index) => (
                    <button
                      key={wallet.wallet}
                      type="button"
                      onClick={() =>
                        selectWallet(wallet.wallet)
                      }
                      className="flex w-full items-center justify-between gap-4 p-5 text-left hover:bg-slate-700/50"
                    >
                      <div className="flex min-w-0 items-center gap-4">
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-700 font-bold">
                          {index + 1}
                        </span>

                        <div className="min-w-0">
                          <p
                            className="truncate font-mono text-sm text-blue-400"
                            title={wallet.wallet}
                          >
                            {shortenAddress(
                              wallet.wallet
                            )}
                          </p>

                          <p className="mt-1 text-xs text-purple-300">
                            {wallet.classification ??
                              "NORMAL"}
                          </p>
                        </div>
                      </div>

                      <div className="text-right">
                        <p className="font-bold text-green-300">
                          Score{" "}
                          {formatNumber(
                            wallet.smart_score,
                            2
                          )}
                        </p>

                        <p className="mt-1 text-xs text-slate-400">
                          ROI{" "}
                          {formatNumber(
                            wallet.roi_percent,
                            2
                          )}
                          %
                        </p>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </section>
          </>
        )}

        {loading && walletAddress && (
          <div className="flex h-96 items-center justify-center">
            <div className="text-center">
              <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-slate-700 border-t-blue-500" />

              <p className="mt-4 text-slate-400">
                Caricamento portfolio...
              </p>
            </div>
          </div>
        )}

        {!loading && walletAddress && portfolio && (
          <>
            <section className="mb-8 rounded-xl border border-slate-700 bg-slate-800 p-6">
              <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <p className="text-sm text-slate-400">
                    Wallet analizzato
                  </p>

                  <Link
                    to={`/wallet/${walletAddress}`}
                    className="mt-2 block break-all font-mono text-blue-400 hover:underline"
                  >
                    {walletAddress}
                  </Link>
                </div>

                {profile && (
                  <div className="flex flex-wrap gap-3">
                    <span className="rounded-full border border-purple-700 bg-purple-900/40 px-4 py-2 text-sm font-bold text-purple-300">
                      {profile.classification ??
                        "NORMAL"}
                    </span>

                    <span className="rounded-full border border-blue-700 bg-blue-900/40 px-4 py-2 text-sm font-bold text-blue-300">
                      Score{" "}
                      {formatNumber(
                        profile.smart_score,
                        2
                      )}
                    </span>
                  </div>
                )}
              </div>
            </section>

            <section className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
              <MetricCard
                label="Posizioni aperte"
                value={summary.openPositions}
                subtitle={`${summary.closedPositions} chiuse`}
                valueClassName="text-green-300"
              />

              <MetricCard
                label="Token analizzati"
                value={
                  portfolio.tokens_count ??
                  enrichedPositions.length
                }
                subtitle={`${trades.length} trade`}
                valueClassName="text-blue-300"
              />

              <MetricCard
                label="SOL spesi"
                value={`${formatNumber(
                  summary.totalSpent,
                  4
                )} SOL`}
                valueClassName="text-red-300"
              />

              <MetricCard
                label="SOL ricevuti"
                value={`${formatNumber(
                  summary.totalReceived,
                  4
                )} SOL`}
                valueClassName="text-green-300"
              />

              <MetricCard
                label="Flusso netto"
                value={`${formatNumber(
                  netCashFlow,
                  4
                )} SOL`}
                valueClassName={
                  netCashFlow >= 0
                    ? "text-green-300"
                    : "text-red-300"
                }
                subtitle="Ricevuti meno spesi"
              />

              <MetricCard
                label="Capitale ancora impegnato"
                value={`${formatNumber(
                  summary.openCapital,
                  4
                )} SOL`}
                valueClassName="text-yellow-300"
                subtitle="Stima basata sui flussi"
              />

              <MetricCard
                label="ROI analytics"
                value={
                  profile
                    ? `${formatNumber(
                        profile.roi_percent,
                        2
                      )}%`
                    : "-"
                }
                valueClassName={
                  Number(
                    profile?.roi_percent ?? 0
                  ) >= 0
                    ? "text-green-300"
                    : "text-red-300"
                }
              />

              <MetricCard
                label="Profit / Loss analytics"
                value={
                  profile
                    ? `${formatNumber(
                        profile.profit_loss_sol,
                        4
                      )} SOL`
                    : "-"
                }
                valueClassName={
                  Number(
                    profile?.profit_loss_sol ?? 0
                  ) >= 0
                    ? "text-green-300"
                    : "text-red-300"
                }
              />
            </section>

            <div className="mb-8 rounded-xl border border-yellow-800 bg-yellow-950/20 p-4 text-sm text-yellow-200">
              Il valore corrente delle posizioni non è
              incluso perché il backend non fornisce ancora
              prezzi live. Il flusso netto rappresenta SOL
              ricevuti meno SOL spesi, mentre ROI e PnL
              provengono dal motore analytics.
            </div>

            <section className="mb-8 rounded-xl border border-slate-700 bg-slate-800 p-5">
              <div className="mb-5">
                <h2 className="text-xl font-bold">
                  Portfolio Cash Flow
                </h2>

                <p className="mt-1 text-sm text-slate-400">
                  Flusso SOL cumulativo del wallet
                </p>
              </div>

              {cashFlowTimeline.length === 0 ? (
                <div className="flex h-72 items-center justify-center text-slate-400">
                  Nessun trade disponibile.
                </div>
              ) : (
                <div className="h-80">
                  <ResponsiveContainer
                    width="100%"
                    height="100%"
                  >
                    <AreaChart
                      data={cashFlowTimeline}
                      margin={{
                        top: 10,
                        right: 10,
                        left: 0,
                        bottom: 0,
                      }}
                    >
                      <defs>
                        <linearGradient
                          id="portfolioCashFlow"
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
                        dataKey="shortDate"
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
                        content={
                          <CashFlowTooltip />
                        }
                      />

                      <ReferenceLine
                        y={0}
                        stroke="#64748b"
                        strokeDasharray="4 4"
                      />

                      <Area
                        type="monotone"
                        dataKey="netCashFlow"
                        stroke="#60a5fa"
                        strokeWidth={2}
                        fill="url(#portfolioCashFlow)"
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
                      Posizioni
                    </h2>

                    <p className="mt-1 text-sm text-slate-400">
                      {filteredPositions.length} di{" "}
                      {enrichedPositions.length} token
                    </p>
                  </div>

                  <div className="flex flex-col gap-3 sm:flex-row">
                    <input
                      type="text"
                      value={positionSearch}
                      onChange={(event) =>
                        setPositionSearch(
                          event.target.value
                        )
                      }
                      placeholder="Cerca token..."
                      className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-2 outline-none focus:border-blue-500"
                    />

                    <select
                      value={positionStatus}
                      onChange={(event) =>
                        setPositionStatus(
                          event.target.value
                        )
                      }
                      className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-2 outline-none focus:border-blue-500"
                    >
                      <option value="ALL">
                        Tutte
                      </option>

                      <option value="OPEN">
                        Aperte
                      </option>

                      <option value="CLOSED">
                        Chiuse
                      </option>

                      <option value="INCOMPLETE">
                        Incomplete
                      </option>
                    </select>
                  </div>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full min-w-[1200px]">
                  <thead className="bg-slate-700">
                    <tr>
                      <th className="p-4 text-left">
                        Token
                      </th>
                      <th className="p-4">
                        Stato
                      </th>
                      <th className="p-4">
                        Holding
                      </th>
                      <th className="p-4">
                        Acquistati
                      </th>
                      <th className="p-4">
                        Venduti
                      </th>
                      <th className="p-4">
                        Buy / Sell
                      </th>
                      <th className="p-4">
                        SOL spesi
                      </th>
                      <th className="p-4">
                        SOL ricevuti
                      </th>
                      <th className="p-4">
                        Flusso netto
                      </th>
                    </tr>
                  </thead>

                  <tbody>
                    {filteredPositions.length ===
                    0 ? (
                      <tr>
                        <td
                          colSpan={9}
                          className="p-10 text-center text-slate-400"
                        >
                          Nessuna posizione trovata.
                        </td>
                      </tr>
                    ) : (
                      filteredPositions.map(
                        (position) => (
                          <tr
                            key={
                              position.token_mint
                            }
                            className="border-t border-slate-700 hover:bg-slate-700/60"
                          >
                            <td className="p-4 font-mono text-sm">
                              <div className="flex flex-col gap-1">
                                <Link
                                  to={`/token/${position.token_mint}`}
                                  className="text-blue-400 hover:underline"
                                  title={
                                    position.token_mint
                                  }
                                >
                                  {shortenAddress(
                                    position.token_mint
                                  )}
                                </Link>

                                <a
                                  href={`https://solscan.io/token/${position.token_mint}`}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-xs text-slate-500 hover:text-blue-300"
                                >
                                  Solscan ↗
                                </a>
                              </div>
                            </td>

                            <td className="p-4 text-center">
                              <span
                                className={`rounded-full px-3 py-1 text-xs font-bold ${getPositionStatusClasses(
                                  position.status
                                )}`}
                              >
                                {position.status}
                              </span>
                            </td>

                            <td className="text-center font-semibold">
                              {formatNumber(
                                position.holdingAmount,
                                6
                              )}
                            </td>

                            <td className="text-center">
                              {formatNumber(
                                position.boughtAmount,
                                6
                              )}
                            </td>

                            <td className="text-center">
                              {formatNumber(
                                position.soldAmount,
                                6
                              )}
                            </td>

                            <td className="text-center">
                              {position.buy_trades ??
                                0}{" "}
                              /{" "}
                              {position.sell_trades ??
                                0}
                            </td>

                            <td className="text-center text-red-300">
                              {formatNumber(
                                position.totalSpent,
                                4
                              )}{" "}
                              SOL
                            </td>

                            <td className="text-center text-green-300">
                              {formatNumber(
                                position.totalReceived,
                                4
                              )}{" "}
                              SOL
                            </td>

                            <td
                              className={`text-center font-bold ${
                                position.netCashFlow >=
                                0
                                  ? "text-green-300"
                                  : "text-red-300"
                              }`}
                            >
                              {formatNumber(
                                position.netCashFlow,
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
                  Ultime operazioni
                </h2>

                <p className="mt-1 text-sm text-slate-400">
                  Ultimi {recentTrades.length} trade
                </p>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full min-w-[950px]">
                  <thead className="bg-slate-700">
                    <tr>
                      <th className="p-4 text-left">
                        Data
                      </th>
                      <th className="p-4">
                        Side
                      </th>
                      <th className="p-4 text-left">
                        Token
                      </th>
                      <th className="p-4 text-right">
                        Quantità
                      </th>
                      <th className="p-4 text-right">
                        SOL
                      </th>
                      <th className="p-4">
                        Source
                      </th>
                      <th className="p-4">
                        Tx
                      </th>
                    </tr>
                  </thead>

                  <tbody>
                    {recentTrades.length === 0 ? (
                      <tr>
                        <td
                          colSpan={7}
                          className="p-10 text-center text-slate-400"
                        >
                          Nessun trade trovato.
                        </td>
                      </tr>
                    ) : (
                      recentTrades.map(
                        (trade, index) => (
                          <tr
                            key={
                              trade.id ??
                              trade.signature ??
                              index
                            }
                            className="border-t border-slate-700 hover:bg-slate-700/60"
                          >
                            <td className="p-4 text-sm text-slate-400">
                              {formatTimestamp(
                                trade.block_time ??
                                  trade.created_at
                              )}
                            </td>

                            <td className="p-4 text-center">
                              <span
                                className={`rounded-full px-3 py-1 text-xs font-bold ${
                                  trade.side ===
                                  "BUY"
                                    ? "bg-green-900/50 text-green-300"
                                    : "bg-red-900/50 text-red-300"
                                }`}
                              >
                                {trade.side ??
                                  "UNKNOWN"}
                              </span>
                            </td>

                            <td className="p-4 font-mono text-sm">
                              {trade.token_mint ? (
                                <Link
                                  to={`/token/${trade.token_mint}`}
                                  className="text-blue-400 hover:underline"
                                  title={
                                    trade.token_mint
                                  }
                                >
                                  {shortenAddress(
                                    trade.token_mint
                                  )}
                                </Link>
                              ) : (
                                "-"
                              )}
                            </td>

                            <td className="p-4 text-right">
                              {formatNumber(
                                trade.token_amount,
                                6
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
                        )
                      )
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}

export default Portfolio; 