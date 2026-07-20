import { useCallback, useEffect, useState } from "react";
import {
  getLiveTradingOperationsOverview,
  reconcileLiveTradingOrders,
  resetLiveTradingRiskCooldown,
  runLiveTradingOperationsOnce,
} from "../../services/liveTradingApi";
import {
  formatLiveDate,
  formatLiveNumber,
  parseLiveApiError,
  shortenLiveAddress,
} from "./liveTradingFormatters";
import LiveTradingMetric from "./LiveTradingMetric";
import LiveTradingSection from "./LiveTradingSection";


function StatusCard({ label, value, detail, tone = "text-white" }) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/70 p-4">
      <p className="text-sm text-slate-400">{label}</p>
      <p className={`mt-2 text-lg font-bold ${tone}`}>{value}</p>
      {detail && <p className="mt-1 text-xs leading-5 text-slate-500">{detail}</p>}
    </div>
  );
}


function valueTone(value) {
  const number = Number(value ?? 0);
  if (number > 0) return "text-green-300";
  if (number < 0) return "text-red-300";
  return "text-slate-400";
}


function LiveTradingOperations({ accessKey }) {
  const [overview, setOverview] = useState(null);
  const [lastCycle, setLastCycle] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const response = await getLiveTradingOperationsOverview(accessKey);
      setOverview(response.data);
    } catch (requestError) {
      setError(parseLiveApiError(requestError));
    } finally {
      setLoading(false);
    }
  }, [accessKey]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      load();
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, [load]);

  async function runAction(name, action, success) {
    setBusy(name);
    setError("");
    setMessage("");
    try {
      const response = await action();
      if (name === "run") {
        setLastCycle(response.data);
      }
      setMessage(success);
      await load();
    } catch (requestError) {
      setError(parseLiveApiError(requestError));
    } finally {
      setBusy("");
    }
  }

  if (loading && !overview) {
    return <div className="rounded-2xl border border-slate-700 bg-slate-800/70 p-8 text-slate-400">Caricamento automazione e rischio...</div>;
  }

  const risk = overview?.risk;
  const monitor = overview?.monitor;
  const cooldownActive = Boolean(
    risk?.cooldown_until
    && new Date(risk.cooldown_until) > new Date()
  );

  return (
    <div className="space-y-6">
      {error && <div className="rounded-xl border border-red-700 bg-red-950/50 px-4 py-3 text-red-300">{error}</div>}
      {message && <div className="rounded-xl border border-green-700 bg-green-950/50 px-4 py-3 text-green-300">{message}</div>}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <LiveTradingMetric
          label="Uscite automatiche"
          value={overview?.automatic_exits_enabled ? "ATTIVE" : "SPENTE"}
          tone={overview?.automatic_exits_enabled ? "positive" : "warning"}
          subtitle={`Monitor runtime ${overview?.monitor_runtime_enabled ? "abilitato" : "disabilitato"}`}
        />
        <LiveTradingMetric
          label="Equity operativa"
          value={risk ? `${formatLiveNumber(risk.current_equity_sol, 6)} SOL` : "N/D"}
          subtitle={risk ? `Picco ${formatLiveNumber(risk.peak_equity_sol, 6)} SOL` : "Policy disabilitata"}
        />
        <LiveTradingMetric
          label="Drawdown"
          value={risk ? `${formatLiveNumber(risk.drawdown_percent, 2)}%` : "N/D"}
          tone={risk && Number(risk.drawdown_percent) > 0 ? "danger" : "default"}
          subtitle={risk ? `${risk.loss_streak} perdite consecutive` : "Nessuno stato rischio"}
        />
        <LiveTradingMetric
          label="Uscite completate"
          value={String(monitor?.exits_completed ?? 0)}
          subtitle={`${monitor?.exits_failed ?? 0} fallite · ${monitor?.exits_triggered ?? 0} attivate`}
        />
      </div>

      <LiveTradingSection
        title="Monitor posizioni e riconciliazione"
        description="Quota periodicamente le posizioni aperte, aggiorna PnL non realizzato, valuta le regole di uscita e riconcilia le firme LIVE con Solana."
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatusCard
            label="Stato monitor"
            value={monitor?.status ?? "N/D"}
            tone={monitor?.status === "ERROR" ? "text-red-300" : monitor?.status === "DEGRADED" ? "text-amber-300" : "text-green-300"}
            detail={monitor?.heartbeat_at ? `Heartbeat ${formatLiveDate(monitor.heartbeat_at)}` : "Nessun heartbeat"}
          />
          <StatusCard label="Posizioni aperte" value={overview?.open_positions ?? 0} detail={`${overview?.exit_pending_positions ?? 0} con uscita pendente`} />
          <StatusCard label="Quote monitor" value={monitor?.quotes_succeeded ?? 0} detail={`${monitor?.quotes_failed ?? 0} fallite`} />
          <StatusCard label="Riconciliazione LIVE" value={overview?.reconciliation_pending_orders ?? 0} detail={`${monitor?.orders_reconciled ?? 0} confermate · ${monitor?.reconciliation_failed ?? 0} fallite`} />
        </div>

        <div className="mt-5 flex flex-wrap gap-3">
          <button
            type="button"
            disabled={busy === "run"}
            onClick={() => runAction("run", () => runLiveTradingOperationsOnce(accessKey, { position_limit: 100, reconcile_limit: 50 }), "Ciclo operativo completato.")}
            className="rounded-xl bg-blue-600 px-5 py-3 font-bold text-white transition hover:bg-blue-500 disabled:opacity-50"
          >
            {busy === "run" ? "Esecuzione..." : "Esegui un ciclo ora"}
          </button>
          <button
            type="button"
            disabled={busy === "reconcile"}
            onClick={() => runAction("reconcile", () => reconcileLiveTradingOrders(accessKey, 50), "Riconciliazione completata.")}
            className="rounded-xl border border-indigo-700 bg-indigo-950/50 px-5 py-3 font-bold text-indigo-300 transition hover:bg-indigo-900/60 disabled:opacity-50"
          >
            Riconcilia ordini LIVE
          </button>
          <button
            type="button"
            onClick={load}
            className="rounded-xl border border-slate-600 bg-slate-800 px-5 py-3 font-bold text-slate-300 transition hover:bg-slate-700"
          >
            Aggiorna stato
          </button>
        </div>
      </LiveTradingSection>

      <LiveTradingSection
        title="Stato rischio portafoglio"
        description="La serie di perdite viene ricostruita dagli ordini SELL completati, comprese le chiusure manuali. I nuovi BUY vengono bloccati durante il cooldown o al superamento del drawdown massimo."
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatusCard label="PnL realizzato" value={risk ? `${formatLiveNumber(risk.realized_pnl_sol, 6)} SOL` : "N/D"} />
          <StatusCard
            label="Serie perdite"
            value={risk?.loss_streak ?? 0}
            detail={risk?.last_loss_at ? `Ultima ${formatLiveDate(risk.last_loss_at)}` : "Nessuna perdita dopo l'ultimo reset"}
          />
          <StatusCard
            label="Cooldown"
            value={cooldownActive ? "ATTIVO" : "Libero"}
            tone={cooldownActive ? "text-amber-300" : "text-green-300"}
            detail={risk?.cooldown_until ? `Fino a ${formatLiveDate(risk.cooldown_until)}` : "Nessuna sospensione attiva"}
          />
          <StatusCard
            label="Storico rischio"
            value={risk?.loss_streak_reset_at ? "Dal reset" : "Completo"}
            detail={risk?.loss_streak_reset_at ? `Reset ${formatLiveDate(risk.loss_streak_reset_at)}` : "Include SELL manuali, automatici e sorgente"}
          />
        </div>

        {risk?.blocked_reason && (
          <div className="mt-4 rounded-xl border border-amber-700 bg-amber-950/40 px-4 py-3 text-sm text-amber-300">
            Motivo blocco: <strong>{risk.blocked_reason}</strong>
          </div>
        )}

        {(cooldownActive || Number(risk?.loss_streak ?? 0) > 0) && (
          <button
            type="button"
            disabled={busy === "reset-risk"}
            onClick={() => {
              if (window.confirm("Azzerare manualmente cooldown e serie di perdite? Le chiusure precedenti resteranno nello storico PnL ma non verranno ricontate nella serie.")) {
                runAction("reset-risk", () => resetLiveTradingRiskCooldown(accessKey), "Cooldown rischio azzerato.");
              }
            }}
            className="mt-5 rounded-xl border border-amber-700 bg-amber-950/50 px-5 py-3 font-bold text-amber-300 transition hover:bg-amber-900/60 disabled:opacity-50"
          >
            Azzera serie e cooldown
          </button>
        )}
      </LiveTradingSection>

      {lastCycle && (
        <LiveTradingSection title="Ultimo ciclo manuale" description="Riepilogo e dettaglio delle quotazioni eseguite dalla dashboard. Con uscite automatiche spente, il ciclo aggiorna soltanto valori, PnL e trigger potenziali.">
          <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
            <StatusCard label="Posizioni" value={lastCycle.positions_scanned} />
            <StatusCard label="Quote riuscite" value={lastCycle.quotes_succeeded} />
            <StatusCard label="Quote fallite" value={lastCycle.quotes_failed} />
            <StatusCard label="Uscite attivate" value={lastCycle.exits_triggered} />
            <StatusCard label="Uscite completate" value={lastCycle.exits_completed} />
            <StatusCard label="Uscite fallite" value={lastCycle.exits_failed} />
          </div>

          {lastCycle.items?.length > 0 && (
            <div className="mt-5 overflow-x-auto rounded-xl border border-slate-700">
              <table className="min-w-[1050px] w-full text-left text-sm">
                <thead className="bg-slate-950/80 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Posizione</th>
                    <th className="px-4 py-3">Token</th>
                    <th className="px-4 py-3 text-right">Cost basis</th>
                    <th className="px-4 py-3 text-right">Valore</th>
                    <th className="px-4 py-3 text-right">PnL</th>
                    <th className="px-4 py-3 text-right">ROI</th>
                    <th className="px-4 py-3">Trigger</th>
                    <th className="px-4 py-3">Esito</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 bg-slate-900/50">
                  {lastCycle.items.map((item) => (
                    <tr key={`${item.position_id}-${item.token_mint}`}>
                      <td className="px-4 py-3 font-mono text-xs text-slate-300">#{item.position_id}</td>
                      <td className="px-4 py-3 font-mono text-xs text-blue-300" title={item.token_mint}>
                        {shortenLiveAddress(item.token_mint, 9, 8)}
                      </td>
                      <td className="px-4 py-3 text-right text-slate-300">
                        {formatLiveNumber(item.cost_basis_sol, 6)} SOL
                      </td>
                      <td className="px-4 py-3 text-right text-slate-300">
                        {item.current_value_sol === undefined
                          ? "N/D"
                          : `${formatLiveNumber(item.current_value_sol, 6)} SOL`}
                      </td>
                      <td className={`px-4 py-3 text-right font-bold ${valueTone(item.unrealized_pnl_sol)}`}>
                        {item.unrealized_pnl_sol === undefined
                          ? "N/D"
                          : `${formatLiveNumber(item.unrealized_pnl_sol, 6)} SOL`}
                      </td>
                      <td className={`px-4 py-3 text-right font-bold ${valueTone(item.unrealized_roi_percent)}`}>
                        {item.unrealized_roi_percent === undefined
                          ? "N/D"
                          : `${formatLiveNumber(item.unrealized_roi_percent, 2)}%`}
                      </td>
                      <td className="px-4 py-3 font-bold text-amber-300">
                        {item.exit_reason ?? "Nessuno"}
                      </td>
                      <td className={item.status === "ERROR" || item.status === "EXIT_FAILED" ? "px-4 py-3 font-bold text-red-300" : "px-4 py-3 font-bold text-green-300"}>
                        {item.status}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </LiveTradingSection>
      )}
    </div>
  );
}


export default LiveTradingOperations;
