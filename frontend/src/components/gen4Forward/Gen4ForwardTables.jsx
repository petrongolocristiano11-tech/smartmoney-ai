import {
  formatGen4Date,
  formatGen4Number,
  formatGen4Percent,
  formatGen4Sol,
  getGen4StatusTone,
  getLaneDefinition,
  shortenGen4Address,
} from "./gen4ForwardFormatters";

const BADGE_CLASSES = {
  positive: "border-emerald-800 bg-emerald-950/50 text-emerald-300",
  warning: "border-amber-800 bg-amber-950/50 text-amber-300",
  danger: "border-red-800 bg-red-950/50 text-red-300",
  neutral: "border-slate-700 bg-slate-900 text-slate-300",
};

function Badge({ value }) {
  const tone = getGen4StatusTone(value);
  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-bold ${
        BADGE_CLASSES[tone] ?? BADGE_CLASSES.neutral
      }`}
    >
      {value || "N/D"}
    </span>
  );
}

export function Gen4FrozenWallets({ campaign }) {
  const wallets = campaign?.frozen_wallets ?? [];
  const metrics = campaign?.frozen_wallet_metrics ?? {};

  return (
    <section className="rounded-3xl border border-slate-700 bg-slate-800/70 p-5 sm:p-6">
      <p className="text-xs font-bold uppercase tracking-[0.2em] text-cyan-400">
        Snapshot immutabile
      </p>
      <h2 className="mt-1 text-2xl font-black text-white">
        Wallet congelati
      </h2>

      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="text-xs uppercase tracking-wider text-slate-500">
            <tr className="border-b border-slate-700">
              <th className="px-3 py-3">Wallet</th>
              <th className="px-3 py-3">Trade training</th>
              <th className="px-3 py-3">Return</th>
              <th className="px-3 py-3">Win rate</th>
              <th className="px-3 py-3">Profit factor</th>
              <th className="px-3 py-3">Drawdown</th>
            </tr>
          </thead>
          <tbody>
            {wallets.map((wallet) => {
              const row = metrics[wallet] ?? {};
              return (
                <tr key={wallet} className="border-b border-slate-800 text-slate-300">
                  <td className="px-3 py-4 font-mono text-xs text-white" title={wallet}>
                    {shortenGen4Address(wallet, 8, 7)}
                  </td>
                  <td className="px-3 py-4">{row.closed_positions ?? 0}</td>
                  <td className="px-3 py-4">{formatGen4Percent(row.return_percent, 4)}</td>
                  <td className="px-3 py-4">{formatGen4Percent(row.win_rate_percent, 2)}</td>
                  <td className="px-3 py-4">{formatGen4Number(row.profit_factor, 4)}</td>
                  <td className="px-3 py-4">{formatGen4Percent(row.max_drawdown_percent, 4)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function Gen4CycleTable({ cycles }) {
  return (
    <section className="rounded-3xl border border-slate-700 bg-slate-800/70 p-5 sm:p-6">
      <p className="text-xs font-bold uppercase tracking-[0.2em] text-cyan-400">
        Watermark forward
      </p>
      <h2 className="mt-1 text-2xl font-black text-white">
        Cicli recenti
      </h2>

      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="text-xs uppercase tracking-wider text-slate-500">
            <tr className="border-b border-slate-700">
              <th className="px-3 py-3">Seq.</th>
              <th className="px-3 py-3">Stato</th>
              <th className="px-3 py-3">Intervallo osservato</th>
              <th className="px-3 py-3">Trade sorgente</th>
              <th className="px-3 py-3">Nuove</th>
              <th className="px-3 py-3">Aggiornate</th>
              <th className="px-3 py-3">Strict</th>
              <th className="px-3 py-3">Chiuse</th>
            </tr>
          </thead>
          <tbody>
            {(cycles ?? []).map((cycle) => (
              <tr key={cycle.cycle_id} className="border-b border-slate-800 text-slate-300">
                <td className="px-3 py-4 font-black text-white">#{cycle.sequence}</td>
                <td className="px-3 py-4"><Badge value={cycle.status} /></td>
                <td className="px-3 py-4 text-xs">
                  {formatGen4Date(cycle.observed_from_at)}<br />
                  <span className="text-slate-500">→ {formatGen4Date(cycle.observed_to_at)}</span>
                </td>
                <td className="px-3 py-4">{cycle.source_trade_count ?? 0}</td>
                <td className="px-3 py-4">{cycle.new_decision_count ?? 0}</td>
                <td className="px-3 py-4">{cycle.updated_decision_count ?? 0}</td>
                <td className="px-3 py-4">{cycle.strict_signal_count ?? 0}</td>
                <td className="px-3 py-4">{cycle.closed_decision_count ?? 0}</td>
              </tr>
            ))}
            {(cycles ?? []).length === 0 && (
              <tr>
                <td colSpan="8" className="px-3 py-8 text-center text-slate-500">
                  Nessun ciclo registrato.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function Gen4DecisionTable({
  decisions,
  laneFilter,
  statusFilter,
  onLaneFilterChange,
  onStatusFilterChange,
}) {
  const filtered = (decisions ?? []).filter((row) => {
    const laneMatches = !laneFilter || row.lane === laneFilter;
    const statusMatches = !statusFilter || row.status === statusFilter;
    return laneMatches && statusMatches;
  });

  return (
    <section className="rounded-3xl border border-slate-700 bg-slate-800/70 p-5 sm:p-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-cyan-400">
            Registro decisionale
          </p>
          <h2 className="mt-1 text-2xl font-black text-white">
            Segnali e trade shadow
          </h2>
          <p className="mt-2 text-sm text-slate-400">
            Sono inclusi anche segnali respinti, in attesa e senza entrata.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-bold uppercase tracking-wider text-slate-500">
            Corsia
            <select
              value={laneFilter}
              onChange={(event) => onLaneFilterChange(event.target.value)}
              className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-3 py-2 text-sm font-normal normal-case tracking-normal text-white"
            >
              <option value="">Tutte</option>
              <option value="STRICT_GEN4_FORWARD">Strict Gen4</option>
              <option value="SIGNAL_ONLY_FORWARD">Proxy</option>
              <option value="SIMPLE_COPY_FORWARD_BASELINE">Baseline</option>
            </select>
          </label>
          <label className="text-xs font-bold uppercase tracking-wider text-slate-500">
            Stato
            <select
              value={statusFilter}
              onChange={(event) => onStatusFilterChange(event.target.value)}
              className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-3 py-2 text-sm font-normal normal-case tracking-normal text-white"
            >
              <option value="">Tutti</option>
              <option value="WAITING_SAFETY">Waiting safety</option>
              <option value="REJECTED">Rejected</option>
              <option value="PENDING_ENTRY">Pending entry</option>
              <option value="OPEN">Open</option>
              <option value="CLOSED">Closed</option>
              <option value="EXPIRED">Expired</option>
            </select>
          </label>
        </div>
      </div>

      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[1180px] text-left text-sm">
          <thead className="text-xs uppercase tracking-wider text-slate-500">
            <tr className="border-b border-slate-700">
              <th className="px-3 py-3">Decisione</th>
              <th className="px-3 py-3">Corsia</th>
              <th className="px-3 py-3">Stato</th>
              <th className="px-3 py-3">Token</th>
              <th className="px-3 py-3">Wallet</th>
              <th className="px-3 py-3">Segnale</th>
              <th className="px-3 py-3">Entrata / uscita</th>
              <th className="px-3 py-3">Return</th>
              <th className="px-3 py-3">PnL</th>
              <th className="px-3 py-3">Motivo</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <tr key={row.decision_id} className="border-b border-slate-800 align-top text-slate-300">
                <td className="px-3 py-4 font-mono text-xs" title={row.decision_id}>
                  {shortenGen4Address(row.decision_id, 6, 4)}
                </td>
                <td className="px-3 py-4 font-bold text-white">
                  {getLaneDefinition(row.lane).shortLabel}
                </td>
                <td className="px-3 py-4"><Badge value={row.status} /></td>
                <td className="px-3 py-4 font-mono text-xs" title={row.token_mint}>
                  {shortenGen4Address(row.token_mint, 7, 6)}
                </td>
                <td className="px-3 py-4">
                  <span className="font-bold text-white">{row.wallet_count ?? 0}</span>
                  <span className="block text-xs text-slate-500">
                    {row.independent_cluster_count ?? 0} cluster
                  </span>
                </td>
                <td className="px-3 py-4 text-xs">{formatGen4Date(row.signal_at)}</td>
                <td className="px-3 py-4 text-xs">
                  {formatGen4Date(row.entry_at)}<br />
                  <span className="text-slate-500">{formatGen4Date(row.exit_at)}</span>
                </td>
                <td className="px-3 py-4 font-bold text-white">
                  {formatGen4Percent(row.return_percent, 4)}
                </td>
                <td className="px-3 py-4">{formatGen4Sol(row.pnl_sol, 6)}</td>
                <td className="max-w-[260px] px-3 py-4 text-xs leading-5 text-slate-400">
                  {row.exit_reason || row.rejection_reason || "—"}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan="10" className="px-3 py-10 text-center text-slate-500">
                  Nessuna decisione corrisponde ai filtri attuali.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
