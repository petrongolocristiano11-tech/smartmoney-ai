import {
  formatGen4Date,
  formatGen4Number,
  shortenGen4Address,
} from "./gen4ForwardFormatters";

function Stat({ label, value, subtitle = "" }) {
  return (
    <div className="rounded-2xl border border-slate-700 bg-slate-950/45 p-4">
      <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">
        {label}
      </p>
      <p className="mt-2 text-xl font-black text-white">{value}</p>
      {subtitle && <p className="mt-1 text-xs text-slate-500">{subtitle}</p>}
    </div>
  );
}

export default function Gen4ForwardFeedPanel({ feed }) {
  const state = feed?.state ?? {};
  const latest = feed?.recent_runs?.[0] ?? null;
  const runtimeReady = feed?.runtime_enabled === true;
  const schedulerRunning = feed?.worker_running === true;
  const enabled = state.enabled === true;

  return (
    <section className="rounded-3xl border border-cyan-900/70 bg-cyan-950/15 p-5 sm:p-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-cyan-400">
            M56–M57 · Feed forward automatico
          </p>
          <h2 className="mt-2 text-2xl font-black text-white">
            Helius → database → ciclo Gen 4
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
            Interroga soltanto i wallet congelati e conserva esclusivamente swap abbastanza recenti da rispettare il limite point-in-time. Un lease nel database impedisce poll concorrenti.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className={`rounded-full border px-3 py-1.5 text-xs font-black ${runtimeReady ? "border-emerald-800 bg-emerald-950/50 text-emerald-300" : "border-red-800 bg-red-950/50 text-red-300"}`}>
            Runtime {runtimeReady ? "ON" : "OFF"}
          </span>
          <span className={`rounded-full border px-3 py-1.5 text-xs font-black ${schedulerRunning ? "border-emerald-800 bg-emerald-950/50 text-emerald-300" : "border-amber-800 bg-amber-950/50 text-amber-300"}`}>
            Scheduler {schedulerRunning ? "RUNNING" : "STOPPED"}
          </span>
          <span className={`rounded-full border px-3 py-1.5 text-xs font-black ${enabled ? "border-cyan-800 bg-cyan-950/50 text-cyan-300" : "border-slate-700 bg-slate-900 text-slate-400"}`}>
            Feed {enabled ? "ENABLED" : "DISABLED"}
          </span>
        </div>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
        <Stat label="Intervallo" value={`${state.interval_seconds ?? 0}s`} subtitle="Default 120 secondi" />
        <Stat label="Wallet" value={feed?.frozen_wallets?.length ?? 0} subtitle={(feed?.frozen_wallets ?? []).map((item) => shortenGen4Address(item, 5, 4)).join(", ")} />
        <Stat label="Poll totali" value={formatGen4Number(state.total_runs ?? 0, 0)} subtitle={`${formatGen4Number(state.successful_runs ?? 0, 0)} riusciti`} />
        <Stat label="Helius oggi" value={`${formatGen4Number(state.daily_helius_requests ?? 0, 0)}/${formatGen4Number(state.daily_request_cap ?? 0, 0)}`} subtitle={`${formatGen4Number(state.total_helius_requests ?? 0, 0)} totali`} />
        <Stat label="Trade importati" value={formatGen4Number(state.total_trades_imported ?? 0, 0)} subtitle={`${formatGen4Number(state.total_trades_updated ?? 0, 0)} aggiornati`} />
        <Stat label="Stale esclusi" value={formatGen4Number(state.total_stale_transactions_filtered ?? 0, 0)} subtitle="Mai evidenza Strict" />
        <Stat label="Ultimo poll" value={state.last_status ?? "N/D"} subtitle={formatGen4Date(state.last_poll_completed_at)} />
        <Stat label="Prossimo poll" value={formatGen4Date(state.next_poll_at)} subtitle={`Lease ${state.lease_owner ? "occupato" : "libero"}`} />
      </div>

      {latest && (
        <div className="mt-5 overflow-x-auto rounded-2xl border border-slate-700 bg-slate-950/45">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-slate-700 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Run</th>
                <th className="px-4 py-3">Stato</th>
                <th className="px-4 py-3">Helius</th>
                <th className="px-4 py-3">Transazioni</th>
                <th className="px-4 py-3">Importati</th>
                <th className="px-4 py-3">Ciclo</th>
                <th className="px-4 py-3">Decisioni</th>
              </tr>
            </thead>
            <tbody>
              <tr className="text-slate-300">
                <td className="px-4 py-3 font-mono text-xs">{shortenGen4Address(latest.run_id, 7, 5)}</td>
                <td className="px-4 py-3 font-bold">{latest.status}</td>
                <td className="px-4 py-3">{latest.helius_requests}</td>
                <td className="px-4 py-3">{latest.transactions_found}</td>
                <td className="px-4 py-3">{latest.trades_imported}</td>
                <td className="px-4 py-3">#{latest.cycle_sequence ?? "—"} {latest.cycle_status ?? ""}</td>
                <td className="px-4 py-3">+{latest.new_decisions ?? 0} / Δ{latest.updated_decisions ?? 0}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {state.last_error_message && (
        <div className="mt-4 rounded-xl border border-red-800 bg-red-950/35 px-4 py-3 text-sm text-red-300">
          {state.last_error_code}: {state.last_error_message}
        </div>
      )}
    </section>
  );
}
