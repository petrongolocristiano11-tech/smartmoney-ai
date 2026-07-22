import LiveTradingBadge from "./LiveTradingBadge";
import LiveTradingSection from "./LiveTradingSection";
import {
  formatLiveDate,
  formatLiveNumber,
  shortenLiveAddress,
} from "./liveTradingFormatters";


function WorkerValue({
  label,
  value,
  tone = "text-white",
}) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/70 p-4">
      <p className="text-xs font-bold uppercase tracking-wide text-slate-500">
        {label}
      </p>

      <p
        className={`mt-2 break-words font-bold ${tone}`}
      >
        {value}
      </p>
    </div>
  );
}


function LiveTradingWorkerPanel({
  worker,
}) {
  if (!worker) {
    return null;
  }

  const pausedByDailyLimit = String(
    worker.last_error_code ?? ""
  ).startsWith("PAUSED_");

  return (
    <LiveTradingSection
      title="Worker Helius automatico"
      description="Stato in tempo reale del processo che ascolta gli swap dei wallet autorizzati e li invia al motore copy-trading."
      action={
        <div className="flex flex-wrap items-center gap-2">
          <LiveTradingBadge
            value={worker.status}
          />

          <span
            className={`rounded-full px-3 py-1 text-xs font-bold ${
              worker.online
                ? "bg-green-950 text-green-300"
                : "bg-red-950 text-red-300"
            }`}
          >
            {worker.online
              ? "HEARTBEAT ONLINE"
              : "HEARTBEAT OFFLINE"}
          </span>
        </div>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <WorkerValue
          label="Wallet monitorati"
          value={worker.monitored_wallets}
        />

        <WorkerValue
          label="Sottoscrizioni Helius"
          value={worker.active_subscriptions}
          tone={
            worker.active_subscriptions > 0
              ? "text-green-300"
              : "text-slate-300"
          }
        />

        <WorkerValue
          label="Coda"
          value={`${worker.queue_depth} in attesa`}
          tone={
            worker.queue_depth > 0
              ? "text-amber-300"
              : "text-green-300"
          }
        />

        <WorkerValue
          label="Latenza WebSocket"
          value={
            worker.last_latency_ms === null
              ? "-"
              : `${formatLiveNumber(
                  worker.last_latency_ms,
                  1
                )} ms`
          }
        />

        <WorkerValue
          label="Firme ricevute"
          value={worker.signatures_received}
        />

        <WorkerValue
          label="Firme elaborate"
          value={worker.signatures_processed}
          tone="text-green-300"
        />

        <WorkerValue
          label="Errori"
          value={worker.signatures_failed}
          tone={
            worker.signatures_failed > 0
              ? "text-red-300"
              : "text-green-300"
          }
        />

        <WorkerValue
          label="Firme scartate"
          value={worker.signatures_dropped}
          tone={
            worker.signatures_dropped > 0
              ? "text-red-300"
              : "text-green-300"
          }
        />

        <WorkerValue
          label="Riconnessioni"
          value={worker.reconnect_count}
        />

        <WorkerValue
          label="Ultimo heartbeat"
          value={formatLiveDate(
            worker.heartbeat_at
          )}
        />

        <WorkerValue
          label="Ultimo messaggio"
          value={formatLiveDate(
            worker.last_message_at
          )}
        />

        <WorkerValue
          label="Ultimo trade"
          value={formatLiveDate(
            worker.last_trade_at
          )}
        />
      </div>

      {worker.active_wallets.length > 0 && (
        <div className="mt-5 rounded-xl border border-slate-700 bg-slate-900/70 p-4">
          <p className="text-xs font-bold uppercase tracking-wide text-slate-500">
            Allowlist attualmente caricata
          </p>

          <div className="mt-3 flex flex-wrap gap-2">
            {worker.active_wallets.map(
              (wallet) => (
                <span
                  key={wallet}
                  title={wallet}
                  className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-blue-300"
                >
                  {shortenLiveAddress(
                    wallet,
                    9,
                    8
                  )}
                </span>
              )
            )}
          </div>
        </div>
      )}

      {worker.last_error_message && (
        <div
          className={`mt-5 rounded-xl border p-4 ${
            pausedByDailyLimit
              ? "border-amber-800 bg-amber-950/40"
              : "border-red-800 bg-red-950/40"
          }`}
        >
          <p
            className={`font-bold ${
              pausedByDailyLimit
                ? "text-amber-200"
                : "text-red-200"
            }`}
          >
            {worker.last_error_code
              ?? "WORKER_ERROR"}
          </p>

          <p
            className={`mt-2 text-sm leading-6 ${
              pausedByDailyLimit
                ? "text-amber-300"
                : "text-red-300"
            }`}
          >
            {worker.last_error_message}
          </p>

          {worker.last_error_at && (
            <p className="mt-2 text-xs text-red-400/70">
              {formatLiveDate(
                worker.last_error_at
              )}
            </p>
          )}
        </div>
      )}

      <div className="mt-5 grid gap-3 text-xs text-slate-500 sm:grid-cols-2">
        <p>
          Worker ID:{" "}
          <span className="font-mono text-slate-400">
            {worker.worker_id ?? "-"}
          </span>
        </p>

        <p>
          Lease database:{" "}
          <span
            className={
              worker.lease_active
                ? "text-green-300"
                : "text-red-300"
            }
          >
            {worker.lease_active
              ? "attivo"
              : "non attivo"}
          </span>
        </p>
      </div>
    </LiveTradingSection>
  );
}


export default LiveTradingWorkerPanel; 