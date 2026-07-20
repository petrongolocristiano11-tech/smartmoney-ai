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
  const cooldownActive = Boolean(risk?.cooldown_until && new Date(risk.cooldown_until) > new Date());

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
        description="I nuovi BUY vengono bloccati al superamento del drawdown massimo o durante il cooldown dopo perdite consecutive. Le posizioni restano visibili e gestibili."
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatusCard label="PnL realizzato" value={risk ? `${formatLiveNumber(risk.realized_pnl_sol, 6)} SOL` : "N/D"} />
          <StatusCard label="Serie perdite" value={risk?.loss_streak ?? 0} detail={risk?.last_loss_at ? `Ultima ${formatLiveDate(risk.last_loss_at)}` : "Nessuna perdita registrata"} />
          <StatusCard label="Cooldown" value={cooldownActive ? "ATTIVO" : "Libero"} tone={cooldownActive ? "text-amber-300" : "text-green-300"} detail={risk?.cooldown_until ? `Fino a ${formatLiveDate(risk.cooldown_until)}` : "Nessuna sospensione"} />
          <StatusCard label="Motivo blocco" value={risk?.blocked_reason ?? "Nessuno"} />
        </div>

        {cooldownActive && (
          <button
            type="button"
            disabled={busy === "reset-risk"}
            onClick={() => {
              if (window.confirm("Azzerare manualmente cooldown e serie di perdite?")) {
                runAction("reset-risk", () => resetLiveTradingRiskCooldown(accessKey), "Cooldown rischio azzerato.");
              }
            }}
            className="mt-5 rounded-xl border border-amber-700 bg-amber-950/50 px-5 py-3 font-bold text-amber-300 transition hover:bg-amber-900/60 disabled:opacity-50"
          >
            Azzera cooldown rischio
          </button>
        )}
      </LiveTradingSection>

      {lastCycle && (
        <LiveTradingSection title="Ultimo ciclo manuale" description="Riepilogo dell'ultima esecuzione richiesta da questa dashboard.">
          <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
            <StatusCard label="Posizioni" value={lastCycle.positions_scanned} />
            <StatusCard label="Quote riuscite" value={lastCycle.quotes_succeeded} />
            <StatusCard label="Quote fallite" value={lastCycle.quotes_failed} />
            <StatusCard label="Uscite attivate" value={lastCycle.exits_triggered} />
            <StatusCard label="Uscite completate" value={lastCycle.exits_completed} />
            <StatusCard label="Uscite fallite" value={lastCycle.exits_failed} />
          </div>
        </LiveTradingSection>
      )}
    </div>
  );
}


export default LiveTradingOperations;
