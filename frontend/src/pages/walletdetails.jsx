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

import WalletActivityChart from "../components/WalletActivityChart";
import WalletNetworkGraph from "../components/WalletNetworkGraph";

import {
  getWalletNetwork,
  getWalletProfile,
  getWalletSmartScore,
  getWalletTrades,
} from "../services/api";

const SCORE_COMPONENTS = [
  {
    key: "performance_score",
    weightKey: "performance",
    label: "Performance",
    description:
      "ROI, profitto e operazioni vincenti",
  },
  {
    key: "timing_score",
    weightKey: "timing",
    label: "Timing",
    description:
      "Capacità di entrare prima degli altri",
  },
  {
    key: "leadership_score",
    weightKey: "leadership",
    label: "Leadership",
    description:
      "Influenza esercitata su altri wallet",
  },
  {
    key: "conviction_score",
    weightKey: "conviction",
    label: "Conviction",
    description:
      "Forza e concentrazione delle posizioni",
  },
  {
    key: "holding_score",
    weightKey: "holding",
    label: "Holding",
    description:
      "Qualità dei tempi di mantenimento",
  },
  {
    key: "prediction_score",
    weightKey: "prediction",
    label: "Prediction",
    description:
      "Qualità storica della selezione token",
  },
  {
    key: "risk_score",
    weightKey: "risk",
    label: "Risk Control",
    description:
      "Controllo del rischio operativo",
  },
  {
    key: "consistency_score",
    weightKey: "consistency",
    label: "Consistency",
    description:
      "Regolarità dei risultati ottenuti",
  },
  {
    key: "data_quality_score",
    weightKey: "data_quality",
    label: "Data Quality",
    description:
      "Profondità e affidabilità del campione",
  },
];

const PENALTY_LABELS = {
  LOW_TRADE_SAMPLE:
    "Campione di trade insufficiente",
  NO_RELIABLE_POSITIONS:
    "Nessuna posizione affidabile",
  LOW_TOKEN_DIVERSITY:
    "Diversificazione token limitata",
  NO_SELL_HISTORY:
    "Storico delle vendite assente",
  HIGH_RISK_PROFILE:
    "Profilo con rischio elevato",
};

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

  return `${address.slice(
    0,
    start
  )}...${address.slice(-end)}`;
}

function formatNumber(
  value,
  maximumFractionDigits = 4
) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "0";
  }

  return number.toLocaleString("it-IT", {
    maximumFractionDigits,
  });
}

function getClassificationClasses(
  classification
) {
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

function getEvidenceClasses(evidenceLevel) {
  switch (evidenceLevel) {
    case "HIGH":
      return "border-green-700 bg-green-900/40 text-green-300";

    case "MEDIUM":
      return "border-yellow-700 bg-yellow-900/40 text-yellow-300";

    default:
      return "border-red-700 bg-red-900/40 text-red-300";
  }
}

function getScoreClasses(value) {
  const score = Number(value) || 0;

  if (score >= 70) {
    return "text-green-300";
  }

  if (score >= 45) {
    return "text-yellow-300";
  }

  return "text-red-300";
}

function getBarClasses(value) {
  const score = Number(value) || 0;

  if (score >= 70) {
    return "bg-green-500";
  }

  if (score >= 45) {
    return "bg-yellow-500";
  }

  return "bg-red-500";
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

function ScoreComponent({
  label,
  description,
  value,
  weight,
}) {
  const normalizedValue = Math.max(
    0,
    Math.min(100, Number(value) || 0)
  );

  const normalizedWeight =
    Number(weight) || 0;

  return (
    <article className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-semibold">
            {label}
          </h3>

          <p className="mt-1 text-xs text-slate-500">
            {description}
          </p>
        </div>

        <p
          className={`text-xl font-bold ${getScoreClasses(
            normalizedValue
          )}`}
        >
          {formatNumber(normalizedValue, 2)}
        </p>
      </div>

      <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-700">
        <div
          className={`h-full rounded-full ${getBarClasses(
            normalizedValue
          )}`}
          style={{
            width: `${normalizedValue}%`,
          }}
        />
      </div>

      <p className="mt-2 text-xs text-slate-500">
        Peso nello score:{" "}
        {formatNumber(
          normalizedWeight * 100,
          1
        )}
        %
      </p>
    </article>
  );
}

function WalletDetails() {
  const { walletAddress } = useParams();

  const [wallet, setWallet] = useState(null);
  const [smartScore, setSmartScore] =
    useState(null);
  const [trades, setTrades] = useState([]);
  const [network, setNetwork] = useState([]);

  const [loading, setLoading] =
    useState(true);
  const [refreshing, setRefreshing] =
    useState(false);

  const [error, setError] = useState("");
  const [warning, setWarning] =
    useState("");

  const [tradeSearch, setTradeSearch] =
    useState("");
  const [sideFilter, setSideFilter] =
    useState("ALL");

  const loadWalletData = useCallback(
    async (showRefreshing = false) => {
      if (showRefreshing) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }

      setError("");
      setWarning("");

      try {
        const [
          profileResult,
          smartScoreResult,
          tradesResult,
          networkResult,
        ] = await Promise.allSettled([
          getWalletProfile(walletAddress),
          getWalletSmartScore(walletAddress),
          getWalletTrades(walletAddress),
          getWalletNetwork(walletAddress),
        ]);

        if (
          profileResult.status ===
          "fulfilled"
        ) {
          setWallet(
            profileResult.value.data
          );
        } else {
          console.error(
            "Errore caricamento profilo:",
            profileResult.reason
          );

          setWallet(null);
          setError(
            "Impossibile caricare questo wallet."
          );
        }

        if (
          smartScoreResult.status ===
          "fulfilled"
        ) {
          setSmartScore(
            smartScoreResult.value.data
          );
        } else {
          console.error(
            "Errore Smart Score:",
            smartScoreResult.reason
          );

          setSmartScore(null);

          setWarning(
            "Profilo caricato, ma i dettagli dello Smart Score v4 non sono disponibili."
          );
        }

        if (
          tradesResult.status ===
          "fulfilled"
        ) {
          const tradesData =
            tradesResult.value.data;

          setTrades(
            Array.isArray(tradesData)
              ? tradesData
              : tradesData?.trades ?? []
          );
        } else {
          console.error(
            "Errore caricamento trade:",
            tradesResult.reason
          );

          setTrades([]);
        }

        if (
          networkResult.status ===
          "fulfilled"
        ) {
          setNetwork(
            networkResult.value.data
              ?.connected_wallets ?? []
          );
        } else {
          console.error(
            "Errore caricamento network:",
            networkResult.reason
          );

          setNetwork([]);
        }
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [walletAddress]
  );

  useEffect(() => {
    loadWalletData();
  }, [loadWalletData]);

  const filteredTrades = useMemo(() => {
    const normalizedSearch = tradeSearch
      .trim()
      .toLowerCase();

    return trades.filter((trade) => {
      const matchesSide =
        sideFilter === "ALL" ||
        trade.side === sideFilter;

      const matchesSearch =
        !normalizedSearch ||
        String(
          trade.token_mint ?? ""
        )
          .toLowerCase()
          .includes(normalizedSearch) ||
        String(
          trade.signature ?? ""
        )
          .toLowerCase()
          .includes(normalizedSearch);

      return matchesSide && matchesSearch;
    });
  }, [
    trades,
    tradeSearch,
    sideFilter,
  ]);

  const tradeStats = useMemo(() => {
    return trades.reduce(
      (stats, trade) => {
        const solAmount =
          Number(trade.sol_amount) || 0;

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
            Caricamento Wallet Intelligence...
          </p>
        </div>
      </div>
    );
  }

  if (error || !wallet) {
    return (
      <div className="min-h-screen bg-slate-900 p-6 text-white">
        <div className="mx-auto max-w-5xl">
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

  const roiPositive =
    Number(wallet.roi_percent) >= 0;

  const profitPositive =
    Number(wallet.profit_loss_sol) >= 0;

  const finalScore = Number(
    smartScore?.smart_score ??
      wallet.smart_score ??
      0
  );

  const rawScore = Number(
    smartScore?.raw_score ?? finalScore
  );

  const confidence = Number(
    smartScore?.confidence ?? 0
  );

  const evidenceLevel =
    smartScore?.evidence_level ?? "LOW";

  const penaltyPoints = Number(
    smartScore?.penalty_points ?? 0
  );

  const components =
    smartScore?.components ?? {};

  const weights = smartScore?.weights ?? {};

  const reasons =
    smartScore?.reasons ?? [];

  const penalties =
    smartScore?.penalties ?? [];

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

            <p className="mt-2 break-all font-mono text-sm text-slate-400">
              {wallet.wallet}
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() =>
                loadWalletData(true)
              }
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
        {warning && (
          <div className="mb-6 rounded-lg border border-yellow-700 bg-yellow-900/30 p-4 text-yellow-300">
            {warning}
          </div>
        )}

        <section className="mb-8 rounded-xl border border-slate-700 bg-slate-800 p-6">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-sm text-slate-400">
                Wallet
              </p>

              <p
                className="mt-2 font-mono text-lg font-semibold"
                title={wallet.wallet}
              >
                {shortenAddress(
                  wallet.wallet,
                  14,
                  12
                )}
              </p>

              <div className="mt-4 flex flex-wrap gap-2">
                <span
                  className={`rounded-full border px-4 py-2 text-sm font-bold ${getClassificationClasses(
                    wallet.classification
                  )}`}
                >
                  {wallet.classification ??
                    "NORMAL"}
                </span>

                {smartScore && (
                  <span
                    className={`rounded-full border px-4 py-2 text-sm font-bold ${getEvidenceClasses(
                      evidenceLevel
                    )}`}
                  >
                    Evidenza {evidenceLevel}
                  </span>
                )}

                <span className="rounded-full border border-blue-700 bg-blue-900/40 px-4 py-2 text-sm font-bold text-blue-300">
                  Score v
                  {smartScore?.version ??
                    wallet.version ??
                    "4.0"}
                </span>
              </div>
            </div>

            <div className="text-left lg:text-right">
              <p className="text-sm uppercase tracking-wide text-slate-400">
                Smart Score
              </p>

              <p
                className={`mt-2 text-6xl font-bold ${getScoreClasses(
                  finalScore
                )}`}
              >
                {formatNumber(finalScore, 2)}
              </p>

              {smartScore && (
                <p className="mt-2 text-sm text-slate-400">
                  Confidenza{" "}
                  {formatNumber(
                    confidence,
                    2
                  )}
                  %
                </p>
              )}
            </div>
          </div>

          {wallet.traits?.length > 0 && (
            <div className="mt-6 flex flex-wrap gap-2">
              {wallet.traits.map((trait) => (
                <span
                  key={trait}
                  className="rounded-full border border-purple-700 bg-purple-900/40 px-3 py-1 text-xs font-semibold text-purple-300"
                >
                  {trait}
                </span>
              ))}
            </div>
          )}
        </section>

        <section className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <MetricCard
            label="ROI"
            value={`${formatNumber(
              wallet.roi_percent,
              2
            )}%`}
            valueClassName={
              roiPositive
                ? "text-green-300"
                : "text-red-300"
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
                ? "text-green-300"
                : "text-red-300"
            }
          />

          <MetricCard
            label="Trade"
            value={tradeStats.total}
            subtitle={`${tradeStats.buys} buy / ${tradeStats.sells} sell`}
            valueClassName="text-blue-300"
          />

          <MetricCard
            label="Volume"
            value={`${formatNumber(
              tradeStats.volume,
              4
            )} SOL`}
          />

          <MetricCard
            label="Posizioni affidabili"
            value={wallet.activity ?? 0}
            valueClassName="text-yellow-300"
          />

          <MetricCard
            label="Rischio"
            value={wallet.risk ?? "MEDIUM"}
            valueClassName={
              wallet.risk === "LOW"
                ? "text-green-300"
                : wallet.risk === "HIGH"
                  ? "text-red-300"
                  : "text-yellow-300"
            }
          />

          <MetricCard
            label="Wallet collegati"
            value={network.length}
          />
        </section>

        {smartScore && (
          <section className="mb-8 rounded-xl border border-slate-700 bg-slate-800 p-5 sm:p-6">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h2 className="text-2xl font-bold">
                  Smart Score Explainability
                </h2>

                <p className="mt-2 text-sm text-slate-400">
                  Come è stato calcolato il punteggio
                  finale del wallet
                </p>
              </div>

              <span
                className={`w-fit rounded-full border px-4 py-2 text-sm font-bold ${getEvidenceClasses(
                  evidenceLevel
                )}`}
              >
                Evidenza {evidenceLevel}
              </span>
            </div>

            <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
              <MetricCard
                label="Score grezzo"
                value={formatNumber(
                  rawScore,
                  2
                )}
                subtitle="Prima di confidenza e penalità"
                valueClassName="text-blue-300"
              />

              <MetricCard
                label="Penalità"
                value={`-${formatNumber(
                  penaltyPoints,
                  2
                )}`}
                subtitle={`${penalties.length} penalità applicate`}
                valueClassName={
                  penaltyPoints > 0
                    ? "text-red-300"
                    : "text-green-300"
                }
              />

              <MetricCard
                label="Score finale"
                value={formatNumber(
                  finalScore,
                  2
                )}
                subtitle={`Versione ${
                  smartScore.version ?? "4.0"
                }`}
                valueClassName={getScoreClasses(
                  finalScore
                )}
              />
            </div>

            <div className="mt-6 rounded-xl border border-slate-700 bg-slate-900/60 p-5">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="font-semibold">
                    Confidenza statistica
                  </p>

                  <p className="mt-1 text-xs text-slate-500">
                    Aumenta con trade, token e
                    posizioni affidabili
                  </p>
                </div>

                <p className="text-xl font-bold text-blue-300">
                  {formatNumber(
                    confidence,
                    2
                  )}
                  %
                </p>
              </div>

              <div className="mt-4 h-3 overflow-hidden rounded-full bg-slate-700">
                <div
                  className="h-full rounded-full bg-blue-500"
                  style={{
                    width: `${Math.max(
                      0,
                      Math.min(
                        100,
                        confidence
                      )
                    )}%`,
                  }}
                />
              </div>
            </div>

            <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-2">
              <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-5">
                <h3 className="text-lg font-bold">
                  Motivazioni
                </h3>

                {reasons.length === 0 ? (
                  <p className="mt-4 text-sm text-slate-400">
                    Nessuna motivazione disponibile.
                  </p>
                ) : (
                  <div className="mt-4 space-y-3">
                    {reasons.map(
                      (reason, index) => (
                        <div
                          key={`${reason}-${index}`}
                          className="flex gap-3 rounded-lg border border-slate-700 bg-slate-800 p-3"
                        >
                          <span className="text-green-300">
                            ✓
                          </span>

                          <p className="text-sm text-slate-300">
                            {reason}
                          </p>
                        </div>
                      )
                    )}
                  </div>
                )}
              </div>

              <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-5">
                <h3 className="text-lg font-bold">
                  Penalità applicate
                </h3>

                {penalties.length === 0 ? (
                  <div className="mt-4 rounded-lg border border-green-800 bg-green-950/30 p-4 text-sm text-green-300">
                    Nessuna penalità applicata.
                  </div>
                ) : (
                  <div className="mt-4 space-y-3">
                    {penalties.map(
                      (penalty, index) => (
                        <div
                          key={`${penalty.code}-${index}`}
                          className="flex items-center justify-between gap-4 rounded-lg border border-red-800 bg-red-950/30 p-3"
                        >
                          <div>
                            <p className="text-sm font-semibold text-red-200">
                              {PENALTY_LABELS[
                                penalty.code
                              ] ??
                                penalty.code}
                            </p>

                            <p className="mt-1 text-xs text-red-400">
                              {penalty.code}
                            </p>
                          </div>

                          <p className="font-bold text-red-300">
                            -
                            {formatNumber(
                              penalty.points,
                              2
                            )}
                          </p>
                        </div>
                      )
                    )}
                  </div>
                )}
              </div>
            </div>

            <div className="mt-6">
              <h3 className="text-lg font-bold">
                Componenti dello score
              </h3>

              <p className="mt-1 text-sm text-slate-400">
                Valore di ogni fattore e relativo
                peso nel calcolo
              </p>

              <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {SCORE_COMPONENTS.map(
                  (component) => (
                    <ScoreComponent
                      key={component.key}
                      label={component.label}
                      description={
                        component.description
                      }
                      value={
                        components[
                          component.key
                        ] ?? 0
                      }
                      weight={
                        weights[
                          component.weightKey
                        ] ?? 0
                      }
                    />
                  )
                )}
              </div>
            </div>
          </section>
        )}

        <div className="mb-8">
          <WalletActivityChart
            trades={trades}
          />
        </div>

        <div className="mb-8">
          <WalletNetworkGraph
            walletAddress={walletAddress}
            connectedWallets={network}
          />
        </div>

        <section className="mb-8 overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="border-b border-slate-700 p-5">
            <h2 className="text-xl font-bold">
              Connected Smart Wallets
            </h2>

            <p className="mt-1 text-sm text-slate-400">
              Wallet collegati attraverso token
              condivisi
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[850px]">
              <thead className="bg-slate-700">
                <tr>
                  <th className="p-4 text-left">
                    Wallet
                  </th>
                  <th className="p-4">
                    Shared Tokens
                  </th>
                  <th className="p-4">
                    Connection
                  </th>
                  <th className="p-4">
                    Score
                  </th>
                  <th className="p-4">
                    ROI
                  </th>
                  <th className="p-4">
                    Win Rate
                  </th>
                </tr>
              </thead>

              <tbody>
                {network.length === 0 ? (
                  <tr>
                    <td
                      colSpan={6}
                      className="p-10 text-center text-slate-400"
                    >
                      Nessun wallet collegato
                      trovato.
                    </td>
                  </tr>
                ) : (
                  network.map((item) => (
                    <tr
                      key={item.wallet}
                      className="border-t border-slate-700 hover:bg-slate-700/50"
                    >
                      <td className="p-4 font-mono text-sm">
                        <Link
                          to={`/wallet/${item.wallet}`}
                          className="text-blue-400 hover:underline"
                          title={item.wallet}
                        >
                          {shortenAddress(
                            item.wallet
                          )}
                        </Link>
                      </td>

                      <td className="p-4 text-center">
                        {item.shared_tokens ?? 0}
                      </td>

                      <td className="p-4 text-center">
                        {formatNumber(
                          item.connection_strength,
                          2
                        )}
                      </td>

                      <td className="p-4 text-center font-bold text-blue-300">
                        {formatNumber(
                          item.smart_score,
                          2
                        )}
                      </td>

                      <td
                        className={`p-4 text-center ${
                          Number(
                            item.roi_percent
                          ) >= 0
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

                      <td className="p-4 text-center">
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
                  {filteredTrades.length} di{" "}
                  {trades.length} trade
                </p>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row">
                <input
                  type="text"
                  value={tradeSearch}
                  onChange={(event) =>
                    setTradeSearch(
                      event.target.value
                    )
                  }
                  placeholder="Cerca token o transazione..."
                  className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-2 outline-none focus:border-blue-500"
                />

                <select
                  value={sideFilter}
                  onChange={(event) =>
                    setSideFilter(
                      event.target.value
                    )
                  }
                  className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-2 outline-none focus:border-blue-500"
                >
                  <option value="ALL">
                    Tutti
                  </option>

                  <option value="BUY">
                    Buy
                  </option>

                  <option value="SELL">
                    Sell
                  </option>
                </select>
              </div>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[1050px]">
              <thead className="bg-slate-700">
                <tr>
                  <th className="p-4">
                    Side
                  </th>
                  <th className="p-4 text-left">
                    Token
                  </th>
                  <th className="p-4 text-right">
                    Token Amount
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
                {filteredTrades.length === 0 ? (
                  <tr>
                    <td
                      colSpan={6}
                      className="p-10 text-center text-slate-400"
                    >
                      Nessun trade trovato.
                    </td>
                  </tr>
                ) : (
                  filteredTrades.map(
                    (trade, index) => (
                      <tr
                        key={
                          trade.id ??
                          trade.signature ??
                          index
                        }
                        className="border-t border-slate-700 hover:bg-slate-700/50"
                      >
                        <td className="p-4 text-center">
                          <span
                            className={`rounded-full px-3 py-1 text-xs font-bold ${
                              trade.side ===
                              "BUY"
                                ? "bg-green-900/50 text-green-300"
                                : trade.side ===
                                    "SELL"
                                  ? "bg-red-900/50 text-red-300"
                                  : "bg-slate-700 text-slate-300"
                            }`}
                          >
                            {trade.side ?? "-"}
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
                                trade.token_mint,
                                10,
                                8
                              )}
                            </Link>
                          ) : (
                            "-"
                          )}
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
                    )
                  )
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