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
  useSearchParams,
} from "react-router-dom";
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
  getCopyTradingSimulation,
  getWalletBacktest,
  getWalletRanking,
} from "../services/api";

const OUTCOME_COLORS = {
  Wins: "#22c55e",
  Losses: "#ef4444",
  Other: "#64748b",
};

const CAPITAL_COLORS = [
  "#3b82f6",
  "#22c55e",
];

const SCENARIO_CAPITALS = [
  1,
  5,
  10,
  25,
  50,
  100,
];

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

function getRiskClasses(risk) {
  switch (risk) {
    case "LOW":
      return "border-green-700 bg-green-900/40 text-green-300";

    case "HIGH":
      return "border-red-700 bg-red-900/40 text-red-300";

    default:
      return "border-yellow-700 bg-yellow-900/40 text-yellow-300";
  }
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

function CapitalTooltip({
  active,
  payload,
}) {
  if (!active || !payload?.length) {
    return null;
  }

  const item = payload[0].payload;

  return (
    <div className="rounded-lg border border-slate-600 bg-slate-950 p-3 shadow-xl">
      <p className="text-sm text-slate-400">
        {item.name}
      </p>

      <p className="mt-1 font-bold text-blue-300">
        {formatNumber(item.value, 4)} SOL
      </p>
    </div>
  );
}

function Backtesting() {
  const { walletAddress } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const capitalFromUrl = useMemo(() => {
    const value = Number(
      searchParams.get("capital")
    );

    return Number.isFinite(value) && value > 0
      ? value
      : 10;
  }, [searchParams]);

  const [walletInput, setWalletInput] = useState(
    walletAddress ?? ""
  );

  const [capitalInput, setCapitalInput] = useState(
    capitalFromUrl
  );

  const [backtest, setBacktest] = useState(null);
  const [simulation, setSimulation] =
    useState(null);
  const [ranking, setRanking] = useState([]);

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
    setCapitalInput(capitalFromUrl);
  }, [walletAddress, capitalFromUrl]);

  const loadRanking = useCallback(async () => {
    setRankingLoading(true);

    try {
      const response = await getWalletRanking();

      setRanking(
        response.data?.ranking?.slice(0, 10) ?? []
      );
    } catch (requestError) {
      console.error(
        "Errore caricamento ranking:",
        requestError
      );
    } finally {
      setRankingLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRanking();
  }, [loadRanking]);

  const loadBacktestingData = useCallback(
    async (manualRefresh = false) => {
      if (!walletAddress) {
        setBacktest(null);
        setSimulation(null);
        return;
      }

      if (manualRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }

      setError("");
      setWarning("");

      try {
        const [
          backtestResult,
          simulationResult,
        ] = await Promise.allSettled([
          getWalletBacktest(walletAddress),
          getCopyTradingSimulation(
            walletAddress,
            capitalFromUrl
          ),
        ]);

        if (backtestResult.status === "fulfilled") {
          setBacktest(backtestResult.value.data);
        } else {
          console.error(
            "Errore backtest:",
            backtestResult.reason
          );

          setBacktest(null);
        }

        if (
          simulationResult.status === "fulfilled"
        ) {
          setSimulation(
            simulationResult.value.data
          );
        } else {
          console.error(
            "Errore simulazione:",
            simulationResult.reason
          );

          setSimulation(null);
        }

        if (
          backtestResult.status === "rejected" &&
          simulationResult.status === "rejected"
        ) {
          const backendMessage =
            backtestResult.reason?.response?.data
              ?.detail ??
            simulationResult.reason?.response?.data
              ?.detail;

          setError(
            typeof backendMessage === "string"
              ? backendMessage
              : "Impossibile eseguire il backtest per questo wallet."
          );

          return;
        }

        if (
          backtestResult.status === "rejected" ||
          simulationResult.status === "rejected"
        ) {
          setWarning(
            "Una parte della simulazione non è disponibile, ma gli altri dati sono stati caricati."
          );
        }

        setLastUpdated(new Date());
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [walletAddress, capitalFromUrl]
  );

  useEffect(() => {
    loadBacktestingData();
  }, [loadBacktestingData]);

  const outcomeData = useMemo(() => {
    if (!backtest) {
      return [];
    }

    const positions = Number(
      backtest.positions ?? 0
    );

    const wins = Number(backtest.wins ?? 0);
    const losses = Number(backtest.losses ?? 0);

    const other = Math.max(
      positions - wins - losses,
      0
    );

    return [
      {
        name: "Wins",
        value: wins,
      },
      {
        name: "Losses",
        value: losses,
      },
      {
        name: "Other",
        value: other,
      },
    ].filter((item) => item.value > 0);
  }, [backtest]);

  const capitalChartData = useMemo(() => {
    if (!simulation) {
      return [];
    }

    return [
      {
        name: "Iniziale",
        value: Number(
          simulation.starting_capital ?? 0
        ),
      },
      {
        name: "Finale",
        value: Number(
          simulation.final_capital ?? 0
        ),
      },
    ];
  }, [simulation]);

  const scenarioRows = useMemo(() => {
    if (!backtest) {
      return [];
    }

    const roi = Number(backtest.roi ?? 0);

    return SCENARIO_CAPITALS.map(
      (startingCapital) => {
        const finalCapital =
          startingCapital * (1 + roi / 100);

        return {
          startingCapital,
          finalCapital,
          profit:
            finalCapital - startingCapital,
          roi,
        };
      }
    );
  }, [backtest]);

  function handleSubmit(event) {
    event.preventDefault();

    const normalizedWallet =
      walletInput.trim();

    const normalizedCapital = Number(
      capitalInput
    );

    if (!normalizedWallet) {
      alert("Inserisci un wallet");
      return;
    }

    if (
      !Number.isFinite(normalizedCapital) ||
      normalizedCapital <= 0
    ) {
      alert(
        "Inserisci un capitale iniziale maggiore di zero"
      );
      return;
    }

    navigate(
      `/backtesting/${normalizedWallet}?capital=${normalizedCapital}`
    );
  }

  function selectWallet(address) {
    const normalizedCapital =
      Number(capitalInput) > 0
        ? Number(capitalInput)
        : 10;

    setWalletInput(address);

    navigate(
      `/backtesting/${address}?capital=${normalizedCapital}`
    );
  }

  const roiPositive =
    Number(backtest?.roi ?? 0) >= 0;

  const profitPositive =
    Number(simulation?.profit ?? 0) >= 0;

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 p-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-3xl font-bold">
              Backtesting Center
            </h1>

            <p className="mt-2 text-slate-400">
              Simula il risultato storico ottenuto
              copiando le operazioni di un wallet
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
                onClick={() =>
                  loadBacktestingData(true)
                }
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
          className="mb-8 grid grid-cols-1 gap-4 rounded-xl border border-slate-700 bg-slate-800 p-5 lg:grid-cols-6"
        >
          <input
            type="text"
            value={walletInput}
            onChange={(event) =>
              setWalletInput(event.target.value)
            }
            placeholder="Wallet address..."
            className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 font-mono outline-none focus:border-blue-500 lg:col-span-4"
          />

          <input
            type="number"
            min="0.01"
            step="0.01"
            value={capitalInput}
            onChange={(event) =>
              setCapitalInput(event.target.value)
            }
            placeholder="Capitale SOL"
            className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-blue-500"
          />

          <button
            type="submit"
            className="rounded-lg bg-blue-600 px-6 py-3 font-semibold hover:bg-blue-700"
          >
            Avvia backtest
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
                Inserisci un indirizzo oppure scegli
                uno dei wallet migliori del ranking.
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
                Esecuzione backtest...
              </p>
            </div>
          </div>
        )}

        {!loading &&
          walletAddress &&
          (backtest || simulation) && (
            <>
              <section className="mb-8 rounded-xl border border-slate-700 bg-slate-800 p-6">
                <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <p className="text-sm text-slate-400">
                      Wallet simulato
                    </p>

                    <Link
                      to={`/wallet/${walletAddress}`}
                      className="mt-2 block break-all font-mono text-blue-400 hover:underline"
                    >
                      {walletAddress}
                    </Link>
                  </div>

                  {backtest && (
                    <span
                      className={`w-fit rounded-full border px-5 py-2 font-bold ${getRiskClasses(
                        backtest.risk
                      )}`}
                    >
                      Rischio{" "}
                      {backtest.risk ?? "MEDIUM"}
                    </span>
                  )}
                </div>
              </section>

              <section className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
                <MetricCard
                  label="Posizioni"
                  value={backtest?.positions ?? 0}
                  subtitle="Posizioni considerate affidabili"
                  valueClassName="text-blue-300"
                />

                <MetricCard
                  label="Wins"
                  value={backtest?.wins ?? 0}
                  subtitle={`${
                    backtest?.losses ?? 0
                  } losses`}
                  valueClassName="text-green-300"
                />

                <MetricCard
                  label="Win Rate"
                  value={`${formatNumber(
                    backtest?.win_rate,
                    2
                  )}%`}
                  valueClassName="text-purple-300"
                />

                <MetricCard
                  label="ROI storico"
                  value={`${formatNumber(
                    backtest?.roi,
                    2
                  )}%`}
                  valueClassName={
                    roiPositive
                      ? "text-green-300"
                      : "text-red-300"
                  }
                />

                <MetricCard
                  label="Capitale iniziale"
                  value={`${formatNumber(
                    simulation?.starting_capital ??
                      capitalFromUrl,
                    4
                  )} SOL`}
                />

                <MetricCard
                  label="Capitale finale"
                  value={`${formatNumber(
                    simulation?.final_capital,
                    4
                  )} SOL`}
                  valueClassName={
                    profitPositive
                      ? "text-green-300"
                      : "text-red-300"
                  }
                />

                <MetricCard
                  label="Profitto simulato"
                  value={`${formatNumber(
                    simulation?.profit,
                    4
                  )} SOL`}
                  valueClassName={
                    profitPositive
                      ? "text-green-300"
                      : "text-red-300"
                  }
                />

                <MetricCard
                  label="Profitto medio"
                  value={`${formatNumber(
                    backtest?.average_profit_per_position,
                    6
                  )} SOL`}
                  subtitle="Per posizione affidabile"
                  valueClassName={
                    Number(
                      backtest?.average_profit_per_position ??
                        0
                    ) >= 0
                      ? "text-green-300"
                      : "text-red-300"
                  }
                />
              </section>

              <div className="mb-8 rounded-xl border border-yellow-800 bg-yellow-950/20 p-4 text-sm text-yellow-200">
                Questa è una simulazione basata sui dati
                storici registrati. Non include commissioni,
                slippage, liquidità, ritardi di esecuzione o
                variazioni future del mercato.
              </div>

              <section className="mb-8 grid grid-cols-1 gap-6 xl:grid-cols-2">
                <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
                  <div className="mb-5">
                    <h2 className="text-xl font-bold">
                      Capitale simulato
                    </h2>

                    <p className="mt-1 text-sm text-slate-400">
                      Confronto tra capitale iniziale e
                      capitale finale
                    </p>
                  </div>

                  {capitalChartData.length === 0 ? (
                    <div className="flex h-72 items-center justify-center text-slate-400">
                      Simulazione non disponibile.
                    </div>
                  ) : (
                    <div className="h-72">
                      <ResponsiveContainer
                        width="100%"
                        height="100%"
                      >
                        <BarChart
                          data={capitalChartData}
                        >
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="#334155"
                          />

                          <XAxis
                            dataKey="name"
                            stroke="#94a3b8"
                            tickLine={false}
                            axisLine={false}
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
                              <CapitalTooltip />
                            }
                          />

                          <Bar
                            dataKey="value"
                            radius={[7, 7, 0, 0]}
                          >
                            {capitalChartData.map(
                              (item, index) => (
                                <Cell
                                  key={item.name}
                                  fill={
                                    CAPITAL_COLORS[
                                      index %
                                        CAPITAL_COLORS.length
                                    ]
                                  }
                                />
                              )
                            )}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </div>

                <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
                  <div className="mb-5">
                    <h2 className="text-xl font-bold">
                      Risultati posizioni
                    </h2>

                    <p className="mt-1 text-sm text-slate-400">
                      Distribuzione tra operazioni vincenti
                      e perdenti
                    </p>
                  </div>

                  {outcomeData.length === 0 ? (
                    <div className="flex h-72 items-center justify-center text-slate-400">
                      Nessuna posizione disponibile.
                    </div>
                  ) : (
                    <div className="h-72">
                      <ResponsiveContainer
                        width="100%"
                        height="100%"
                      >
                        <PieChart>
                          <Pie
                            data={outcomeData}
                            dataKey="value"
                            nameKey="name"
                            innerRadius={60}
                            outerRadius={100}
                            paddingAngle={4}
                            label={({ name, value }) =>
                              `${name}: ${value}`
                            }
                          >
                            {outcomeData.map(
                              (item) => (
                                <Cell
                                  key={item.name}
                                  fill={
                                    OUTCOME_COLORS[
                                      item.name
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
              </section>

              <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
                <div className="border-b border-slate-700 p-5">
                  <h2 className="text-xl font-bold">
                    Scenari di capitale
                  </h2>

                  <p className="mt-1 text-sm text-slate-400">
                    Proiezione dello stesso ROI storico su
                    capitali differenti
                  </p>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full min-w-[700px]">
                    <thead className="bg-slate-700">
                      <tr>
                        <th className="p-4 text-left">
                          Capitale iniziale
                        </th>

                        <th className="p-4 text-center">
                          ROI storico
                        </th>

                        <th className="p-4 text-center">
                          Profitto
                        </th>

                        <th className="p-4 text-right">
                          Capitale finale
                        </th>
                      </tr>
                    </thead>

                    <tbody>
                      {scenarioRows.map((scenario) => {
                        const positive =
                          scenario.profit >= 0;

                        return (
                          <tr
                            key={
                              scenario.startingCapital
                            }
                            className="border-t border-slate-700 hover:bg-slate-700/60"
                          >
                            <td className="p-4 font-semibold">
                              {formatNumber(
                                scenario.startingCapital,
                                2
                              )}{" "}
                              SOL
                            </td>

                            <td
                              className={`text-center ${
                                scenario.roi >= 0
                                  ? "text-green-300"
                                  : "text-red-300"
                              }`}
                            >
                              {formatNumber(
                                scenario.roi,
                                2
                              )}
                              %
                            </td>

                            <td
                              className={`text-center font-bold ${
                                positive
                                  ? "text-green-300"
                                  : "text-red-300"
                              }`}
                            >
                              {formatNumber(
                                scenario.profit,
                                4
                              )}{" "}
                              SOL
                            </td>

                            <td className="p-4 text-right font-bold">
                              {formatNumber(
                                scenario.finalCapital,
                                4
                              )}{" "}
                              SOL
                            </td>
                          </tr>
                        );
                      })}
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

export default Backtesting; 