import {
  formatGen4Number,
  formatGen4Percent,
  formatGen4Sol,
  getLaneDefinition,
} from "./gen4ForwardFormatters";

const LANE_CLASSES = {
  cyan: "border-cyan-800 bg-cyan-950/25",
  violet: "border-violet-800 bg-violet-950/25",
  amber: "border-amber-800 bg-amber-950/25",
  slate: "border-slate-700 bg-slate-900/60",
};

function Metric({ label, value }) {
  return (
    <div className="rounded-xl border border-white/5 bg-black/15 px-3 py-2">
      <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className="mt-1 font-bold text-white">
        {value}
      </p>
    </div>
  );
}

function Gen4ForwardLaneCard({ lane, metrics = {} }) {
  const definition = getLaneDefinition(lane);

  return (
    <article
      className={`rounded-3xl border p-5 ${
        LANE_CLASSES[definition.tone] ?? LANE_CLASSES.slate
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">
            Corsia
          </p>
          <h3 className="mt-1 text-xl font-black text-white">
            {definition.label}
          </h3>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            {definition.description}
          </p>
        </div>
        <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-xs font-bold text-slate-200">
          {metrics.signals ?? 0} segnali
        </span>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 xl:grid-cols-3">
        <Metric
          label="Trade chiusi"
          value={metrics.closed_trades ?? 0}
        />
        <Metric
          label="Aperti"
          value={metrics.open_positions ?? 0}
        />
        <Metric
          label="Return"
          value={formatGen4Percent(metrics.total_return_percent, 4)}
        />
        <Metric
          label="PnL netto"
          value={formatGen4Sol(metrics.net_pnl_sol, 6)}
        />
        <Metric
          label="Win rate"
          value={formatGen4Percent(metrics.win_rate_percent, 2)}
        />
        <Metric
          label="Profit factor"
          value={formatGen4Number(metrics.profit_factor, 4)}
        />
        <Metric
          label="Drawdown"
          value={formatGen4Percent(metrics.max_drawdown_percent, 4)}
        />
        <Metric
          label="Respinti"
          value={metrics.rejected ?? 0}
        />
        <Metric
          label="In sicurezza"
          value={metrics.waiting_safety ?? 0}
        />
      </div>
    </article>
  );
}

export default Gen4ForwardLaneCard;
