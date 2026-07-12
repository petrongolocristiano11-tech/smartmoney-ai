import { useMemo } from "react";
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

function formatDate(value) {
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

function formatSol(value) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "0";
  }

  return number.toLocaleString("it-IT", {
    maximumFractionDigits: 3,
  });
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) {
    return null;
  }

  const item = payload[0].payload;

  return (
    <div className="rounded-lg border border-slate-600 bg-slate-900 p-3 shadow-xl">
      <p className="text-xs text-slate-400">
        {item.fullDate}
      </p>

      <p className="mt-1 font-semibold text-blue-300">
        Flusso netto: {formatSol(item.netSol)} SOL
      </p>

      <p className="mt-1 text-xs text-slate-300">
        {item.side} · {formatSol(item.solAmount)} SOL
      </p>
    </div>
  );
}

function WalletActivityChart({ trades = [] }) {
  const chartData = useMemo(() => {
    const orderedTrades = [...trades].sort((a, b) => {
      const firstDate = new Date(
        a.block_time ?? a.created_at ?? 0
      ).getTime();

      const secondDate = new Date(
        b.block_time ?? b.created_at ?? 0
      ).getTime();

      return firstDate - secondDate;
    });

    let cumulativeNetSol = 0;

    return orderedTrades.map((trade, index) => {
      const solAmount = Number(trade.sol_amount) || 0;

      if (trade.side === "SELL") {
        cumulativeNetSol += solAmount;
      } else if (trade.side === "BUY") {
        cumulativeNetSol -= solAmount;
      }

      const dateValue =
        trade.block_time ?? trade.created_at;

      return {
        index: index + 1,
        date: formatDate(dateValue),
        fullDate: dateValue
          ? new Date(dateValue).toLocaleString("it-IT")
          : `Trade ${index + 1}`,
        side: trade.side ?? "UNKNOWN",
        solAmount,
        netSol: Number(cumulativeNetSol.toFixed(4)),
      };
    });
  }, [trades]);

  return (
    <section className="mb-8 rounded-xl border border-slate-700 bg-slate-800 p-5">
      <div className="mb-5">
        <h2 className="text-xl font-bold">
          Wallet Activity
        </h2>

        <p className="mt-1 text-sm text-slate-400">
          Flusso SOL cumulativo: acquisti negativi e vendite positive
        </p>
      </div>

      {chartData.length === 0 ? (
        <div className="flex h-72 items-center justify-center text-slate-400">
          Nessun dato disponibile per il grafico.
        </div>
      ) : (
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={chartData}
              margin={{
                top: 10,
                right: 10,
                left: 0,
                bottom: 0,
              }}
            >
              <defs>
                <linearGradient
                  id="walletNetSol"
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
                dataKey="date"
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
                  `${formatSol(value)}`
                }
              />

              <Tooltip content={<CustomTooltip />} />

              <ReferenceLine
                y={0}
                stroke="#64748b"
                strokeDasharray="4 4"
              />

              <Area
                type="monotone"
                dataKey="netSol"
                stroke="#60a5fa"
                strokeWidth={2}
                fill="url(#walletNetSol)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

export default WalletActivityChart; 