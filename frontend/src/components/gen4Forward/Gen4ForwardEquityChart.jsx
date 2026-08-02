import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatGen4Number } from "./gen4ForwardFormatters";

function EquityTooltip({ active, payload, label }) {
  if (!active || !payload?.length) {
    return null;
  }

  return (
    <div className="rounded-xl border border-slate-600 bg-slate-950/95 p-3 text-xs shadow-xl">
      <p className="font-bold text-white">Trade #{label}</p>
      {payload.map((row) => (
        <p key={row.dataKey} className="mt-1 text-slate-300">
          {row.name}: {formatGen4Number(row.value, 6)} SOL
        </p>
      ))}
    </div>
  );
}

function Gen4ForwardEquityChart({ data }) {
  return (
    <section className="rounded-3xl border border-slate-700 bg-slate-800/70 p-5 sm:p-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-cyan-400">
          Shadow equity
        </p>
        <h2 className="mt-1 text-2xl font-black text-white">
          PnL cumulativo per corsia
        </h2>
        <p className="mt-2 text-sm text-slate-400">
          La curva usa esclusivamente decisioni accettate e chiuse registrate nella campagna forward.
        </p>
      </div>

      <div className="mt-6 h-80">
        {data.length === 0 ? (
          <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-slate-700 bg-slate-900/40 px-6 text-center text-sm text-slate-500">
            La curva apparirà quando almeno una decisione shadow sarà chiusa.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="index" stroke="#94a3b8" tickLine={false} />
              <YAxis stroke="#94a3b8" tickLine={false} width={72} />
              <Tooltip content={<EquityTooltip />} />
              <Legend />
              <Line
                type="monotone"
                dataKey="strict"
                name="Strict Gen4"
                stroke="#22d3ee"
                strokeWidth={3}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="proxy"
                name="Proxy"
                stroke="#a78bfa"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="baseline"
                name="Baseline"
                stroke="#fbbf24"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}

export default Gen4ForwardEquityChart;
