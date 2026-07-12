import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  getDashboard,
  getWalletRanking,
} from "../services/api";

const CLASSIFICATION_COLORS = [
  "#8b5cf6",
  "#3b82f6",
  "#22c55e",
  "#f59e0b",
  "#ef4444",
  "#64748b",
];

function shortenAddress(address, start = 10, end = 8) {
  if (!address) {
    return "-";
  }

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

function MetricCard({
  label,
  value,
  subtitle = "",
  valueClassName = "",
}) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
      <p className="text-sm text-slate-400">{label}</p>

      <p
        className={`mt-2 text-3xl font-bold ${valueClassName}`}
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

function ChartTooltip({
  active,
  payload,
  label,
  suffix = "",
}) {
  if (!active || !payload?.length) {
    return null;
  }

  return (
    <div className="rounded-lg border border-slate-600 bg-slate-950 p-3 shadow-xl">
      <p className="text-sm text-slate-400">{label}</p>

      <p className="mt-1 font-bold text-blue-300">
        {formatNumber(payload[0].value)} {suffix}
      </p>
    </div>
  );
}

function Analytics() {
  const [wallets, setWallets] = useState([]);
  const [dashboard, setDashboard] = useState(null);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);

  const loadAnalytics = useCallback(
    async (manualRefresh = false) => {
      if (manualRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }

      setError("");

      try {
        const [rankingResult, dashboardResult] =
          await Promise.all([
            getWalletRanking(),
            getDashboard(),
          ]);

        setWallets(
          rankingResult.data?.ranking ?? []
        );

        setDashboard(dashboardResult.data);
        setLastUpdated(new Date());
      } catch (requestError) {
        console.error(
          "Errore caricamento analytics:",
          requestError
        );

        setError(
          "Impossibile caricare i dati analytics dal backend."
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    []
  );

  useEffect(() => {
    loadAnalytics();
  }, [loadAnalytics]);

  const analytics = useMemo(() => {
    if (wallets.length === 0) {
      return {
        averageScore: 0,
        averageRoi: 0,
        averageWinRate: 0,
        totalProfit: 0,
        positiveRoiWallets: 0,
        scoreDistribution: [],
        roiDistribution: [],
        classificationDistribution: [],
        topWallets: [],
      };
    }

    const averageScore =
      wallets.reduce(
        (sum, wallet) =>
          sum + Number(wallet.smart_score ?? 0),
        0
      ) / wallets.length;

    const averageRoi =
      wallets.reduce(
        (sum, wallet) =>
          sum + Number(wallet.roi_percent ?? 0),
        0
      ) / wallets.length;

    const averageWinRate =
      wallets.reduce(
        (sum, wallet) =>
          sum +
          Number(wallet.win_rate_percent ?? 0),
        0
      ) / wallets.length;

    const totalProfit = wallets.reduce(
      (sum, wallet) =>
        sum +
        Number(wallet.profit_loss_sol ?? 0),
      0
    );

    const positiveRoiWallets = wallets.filter(
      (wallet) =>
        Number(wallet.roi_percent ?? 0) > 0
    ).length;

    const scoreRanges = [
      {
        label: "0-20",
        minimum: 0,
        maximum: 20,
      },
      {
        label: "20-40",
        minimum: 20,
        maximum: 40,
      },
      {
        label: "40-60",
        minimum: 40,
        maximum: 60,
      },
      {
        label: "60-80",
        minimum: 60,
        maximum: 80,
      },
      {
        label: "80-100",
        minimum: 80,
        maximum: 101,
      },
    ];

    const scoreDistribution = scoreRanges.map(
      (range) => ({
        range: range.label,
        wallets: wallets.filter((wallet) => {
          const score = Number(
            wallet.smart_score ?? 0
          );

          return (
            score >= range.minimum &&
            score < range.maximum
          );
        }).length,
      })
    );

    const roiRanges = [
      {
        label: "< -25%",
        minimum: -Infinity,
        maximum: -25,
      },
      {
        label: "-25 / 0%",
        minimum: -25,
        maximum: 0,
      },
      {
        label: "0 / 25%",
        minimum: 0,
        maximum: 25,
      },
      {
        label: "25 / 50%",
        minimum: 25,
        maximum: 50,
      },
      {
        label: "> 50%",
        minimum: 50,
        maximum: Infinity,
      },
    ];

    const roiDistribution = roiRanges.map(
      (range) => ({
        range: range.label,
        wallets: wallets.filter((wallet) => {
          const roi = Number(
            wallet.roi_percent ?? 0
          );

          return (
            roi >= range.minimum &&
            roi < range.maximum
          );
        }).length,
      })
    );

    const classificationCounts = wallets.reduce(
      (counts, wallet) => {
        const classification =
          wallet.classification ?? "NORMAL";

        counts[classification] =
          (counts[classification] ?? 0) + 1;

        return counts;
      },
      {}
    );

    const classificationDistribution =
      Object.entries(classificationCounts)
        .map(([name, value]) => ({
          name,
          value,
        }))
        .sort(
          (first, second) =>
            second.value - first.value
        );

    const topWallets = [...wallets]
      .sort(
        (first, second) =>
          Number(second.smart_score ?? 0) -
          Number(first.smart_score ?? 0)
      )
      .slice(0, 10);

    return {
      averageScore,
      averageRoi,
      averageWinRate,
      totalProfit,
      positiveRoiWallets,
      scoreDistribution,
      roiDistribution,
      classificationDistribution,
      topWallets,
    };
  }, [wallets]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-900 text-white">
        <div className="text-center">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-slate-700 border-t-blue-500" />

          <p className="mt-4 text-slate-400">
            Caricamento analytics...
          </p>
        </div>
      </div>
    );
  }

  const positiveRoiPercentage =
    wallets.length > 0
      ? (analytics.positiveRoiWallets /
          wallets.length) *
        100
      : 0;

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 p-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-3xl font-bold">
              Analytics Center
            </h1>

            <p className="mt-2 text-slate-400">
              Distribuzione e performance dei wallet
              analizzati
            </p>
          </div>

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
              onClick={() => loadAnalytics(true)}
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

        <section className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <MetricCard
            label="Wallet analizzati"
            value={wallets.length}
            subtitle={`${
              dashboard?.stats?.smart_wallets ?? 0
            } smart wallet`}
            valueClassName="text-blue-300"
          />

          <MetricCard
            label="Smart Score medio"
            value={formatNumber(
              analytics.averageScore,
              2
            )}
            valueClassName="text-purple-300"
          />

          <MetricCard
            label="ROI medio"
            value={`${formatNumber(
              analytics.averageRoi,
              2
            )}%`}
            valueClassName={
              analytics.averageRoi >= 0
                ? "text-green-300"
                : "text-red-300"
            }
          />

          <MetricCard
            label="Win Rate medio"
            value={`${formatNumber(
              analytics.averageWinRate,
              2
            )}%`}
            valueClassName="text-yellow-300"
          />

          <MetricCard
            label="Profit totale"
            value={`${formatNumber(
              analytics.totalProfit,
              4
            )} SOL`}
            valueClassName={
              analytics.totalProfit >= 0
                ? "text-green-300"
                : "text-red-300"
            }
          />

          <MetricCard
            label="Wallet con ROI positivo"
            value={analytics.positiveRoiWallets}
            subtitle={`${formatNumber(
              positiveRoiPercentage,
              1
            )}% del ranking`}
            valueClassName="text-green-300"
          />

          <MetricCard
            label="Trades analizzati"
            value={
              dashboard?.stats?.trades ?? 0
            }
          />

          <MetricCard
            label="Segnali attivi"
            value={
              dashboard?.stats?.signals ?? 0
            }
            subtitle={`${
              dashboard?.stats?.alerts ?? 0
            } alert`}
            valueClassName="text-red-300"
          />
        </section>

        <section className="mb-8 grid grid-cols-1 gap-6 xl:grid-cols-2">
          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <div className="mb-5">
              <h2 className="text-xl font-bold">
                Distribuzione Smart Score
              </h2>

              <p className="mt-1 text-sm text-slate-400">
                Numero di wallet per fascia di score
              </p>
            </div>

            <div className="h-80">
              <ResponsiveContainer
                width="100%"
                height="100%"
              >
                <BarChart
                  data={
                    analytics.scoreDistribution
                  }
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="#334155"
                  />

                  <XAxis
                    dataKey="range"
                    stroke="#94a3b8"
                    tickLine={false}
                    axisLine={false}
                  />

                  <YAxis
                    allowDecimals={false}
                    stroke="#94a3b8"
                    tickLine={false}
                    axisLine={false}
                  />

                  <Tooltip
                    content={
                      <ChartTooltip suffix="wallet" />
                    }
                  />

                  <Bar
                    dataKey="wallets"
                    fill="#8b5cf6"
                    radius={[6, 6, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <div className="mb-5">
              <h2 className="text-xl font-bold">
                Distribuzione ROI
              </h2>

              <p className="mt-1 text-sm text-slate-400">
                Wallet raggruppati per rendimento
              </p>
            </div>

            <div className="h-80">
              <ResponsiveContainer
                width="100%"
                height="100%"
              >
                <BarChart
                  data={
                    analytics.roiDistribution
                  }
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="#334155"
                  />

                  <XAxis
                    dataKey="range"
                    stroke="#94a3b8"
                    tickLine={false}
                    axisLine={false}
                  />

                  <YAxis
                    allowDecimals={false}
                    stroke="#94a3b8"
                    tickLine={false}
                    axisLine={false}
                  />

                  <Tooltip
                    content={
                      <ChartTooltip suffix="wallet" />
                    }
                  />

                  <Bar
                    dataKey="wallets"
                    fill="#22c55e"
                    radius={[6, 6, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>

        <section className="mb-8 grid grid-cols-1 gap-6 xl:grid-cols-2">
          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <div className="mb-5">
              <h2 className="text-xl font-bold">
                Classificazioni
              </h2>

              <p className="mt-1 text-sm text-slate-400">
                Distribuzione del Wallet DNA
              </p>
            </div>

            {analytics.classificationDistribution
              .length === 0 ? (
              <div className="flex h-80 items-center justify-center text-slate-400">
                Nessun dato disponibile.
              </div>
            ) : (
              <div className="h-80">
                <ResponsiveContainer
                  width="100%"
                  height="100%"
                >
                  <PieChart>
                    <Pie
                      data={
                        analytics.classificationDistribution
                      }
                      dataKey="value"
                      nameKey="name"
                      innerRadius={65}
                      outerRadius={105}
                      paddingAngle={3}
                      label={({ name, value }) =>
                        `${name}: ${value}`
                      }
                    >
                      {analytics.classificationDistribution.map(
                        (item, index) => (
                          <Cell
                            key={item.name}
                            fill={
                              CLASSIFICATION_COLORS[
                                index %
                                  CLASSIFICATION_COLORS.length
                              ]
                            }
                          />
                        )
                      )}
                    </Pie>

                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          <div className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
            <div className="border-b border-slate-700 p-5">
              <h2 className="text-xl font-bold">
                Top 10 Wallet
              </h2>

              <p className="mt-1 text-sm text-slate-400">
                Ordinati per Smart Score
              </p>
            </div>

            <div className="divide-y divide-slate-700">
              {analytics.topWallets.map(
                (wallet, index) => (
                  <article
                    key={wallet.wallet}
                    className="flex items-center justify-between gap-4 p-4 hover:bg-slate-700/50"
                  >
                    <div className="flex min-w-0 items-center gap-4">
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-700 font-bold text-slate-300">
                        {index + 1}
                      </span>

                      <div className="min-w-0">
                        <Link
                          to={`/wallet/${wallet.wallet}`}
                          title={wallet.wallet}
                          className="block truncate font-mono text-sm text-blue-400 hover:underline"
                        >
                          {shortenAddress(
                            wallet.wallet
                          )}
                        </Link>

                        <p className="mt-1 text-xs text-purple-300">
                          {wallet.classification ??
                            "NORMAL"}
                        </p>
                      </div>
                    </div>

                    <div className="text-right">
                      <p className="text-lg font-bold text-green-300">
                        {formatNumber(
                          wallet.smart_score,
                          2
                        )}
                      </p>

                      <p
                        className={`text-xs ${
                          Number(
                            wallet.roi_percent
                          ) >= 0
                            ? "text-green-400"
                            : "text-red-400"
                        }`}
                      >
                        ROI{" "}
                        {formatNumber(
                          wallet.roi_percent,
                          2
                        )}
                        %
                      </p>
                    </div>
                  </article>
                )
              )}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

export default Analytics; 