import { useEffect, useMemo, useState } from "react";

import {
  formatGen4Date,
  formatGen4Number,
  shortenGen4Address,
} from "./gen4ForwardFormatters";

const BADGE_CLASSES = {
  good: "border-emerald-800 bg-emerald-950/50 text-emerald-300",
  warn: "border-amber-800 bg-amber-950/50 text-amber-300",
  bad: "border-red-800 bg-red-950/50 text-red-300",
  neutral: "border-slate-700 bg-slate-900 text-slate-300",
};

function Badge({ children, tone = "neutral" }) {
  return (
    <span
      className={`inline-flex rounded-full border px-3 py-1 text-xs font-black ${
        BADGE_CLASSES[tone] ?? BADGE_CLASSES.neutral
      }`}
    >
      {children}
    </span>
  );
}

function Metric({ label, value, subtitle }) {
  return (
    <div className="rounded-2xl border border-slate-700 bg-slate-950/50 p-4">
      <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">
        {label}
      </p>
      <p className="mt-2 text-2xl font-black text-white">{value}</p>
      {subtitle && <p className="mt-1 text-xs text-slate-500">{subtitle}</p>}
    </div>
  );
}

function percent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/D";
  }
  return `${formatGen4Number(value, 2)}%`;
}

function milliseconds(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/D";
  }
  return `${formatGen4Number(value, 0)} ms`;
}

function ProgressLine({ label, current, target }) {
  const safeTarget = Math.max(1, Number(target) || 1);
  const safeCurrent = Math.max(0, Number(current) || 0);
  const width = Math.min(100, (safeCurrent / safeTarget) * 100);
  return (
    <div>
      <div className="flex items-center justify-between gap-4 text-xs">
        <span className="font-bold text-slate-300">{label}</span>
        <span className="text-slate-500">
          {formatGen4Number(safeCurrent, 2)} / {formatGen4Number(safeTarget, 0)}
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800">
        <div
          className="h-full rounded-full bg-violet-500 transition-all"
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

function PositionRows({ positions }) {
  if (!positions?.length) {
    return <p className="py-6 text-sm text-slate-500">Nessuna simulazione real-time ancora registrata.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[920px] text-left text-xs">
        <thead className="text-slate-500">
          <tr className="border-b border-slate-800">
            <th className="px-3 py-3">Stato</th>
            <th className="px-3 py-3">Wallet</th>
            <th className="px-3 py-3">Token</th>
            <th className="px-3 py-3">Ricezione</th>
            <th className="px-3 py-3">Età segnale</th>
            <th className="px-3 py-3">Quote</th>
            <th className="px-3 py-3">Peggioramento</th>
            <th className="px-3 py-3">Rendimento</th>
            <th className="px-3 py-3">Esito</th>
          </tr>
        </thead>
        <tbody>
          {positions.slice(0, 20).map((position) => (
            <tr key={position.position_id} className="border-b border-slate-800/70 text-slate-300">
              <td className="px-3 py-3 font-bold">{position.status}</td>
              <td className="px-3 py-3 font-mono">{shortenGen4Address(position.wallet_address, 5, 4)}</td>
              <td className="px-3 py-3 font-mono">{shortenGen4Address(position.token_mint, 5, 4)}</td>
              <td className="px-3 py-3">{formatGen4Date(position.entry_received_at)}</td>
              <td className="px-3 py-3">{milliseconds(position.chain_age_ms)}</td>
              <td className="px-3 py-3">{milliseconds(position.entry_quote_latency_ms)}</td>
              <td className="px-3 py-3">{position.entry_price_deterioration_bps == null ? "N/D" : `${formatGen4Number(position.entry_price_deterioration_bps, 0)} bps`}</td>
              <td className={`px-3 py-3 font-black ${Number(position.return_percent) >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                {position.return_percent == null ? "Aperto" : percent(position.return_percent)}
              </td>
              <td className="px-3 py-3">{position.entry_rejection_reason || position.close_reason || (position.entry_copyable ? "COPYABLE" : "IN ATTESA")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReceiptRows({ receipts }) {
  if (!receipts?.length) {
    return <p className="py-6 text-sm text-slate-500">Nessuna consegna webhook o recovery registrata.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-left text-xs">
        <thead className="text-slate-500">
          <tr className="border-b border-slate-800">
            <th className="px-3 py-3">Fonte</th>
            <th className="px-3 py-3">Stato</th>
            <th className="px-3 py-3">Firma</th>
            <th className="px-3 py-3">Ricevuto</th>
            <th className="px-3 py-3">Lato</th>
            <th className="px-3 py-3">Queue</th>
            <th className="px-3 py-3">Consegne</th>
          </tr>
        </thead>
        <tbody>
          {receipts.slice(0, 20).map((receipt) => (
            <tr key={receipt.receipt_id} className="border-b border-slate-800/70 text-slate-300">
              <td className={`px-3 py-3 font-black ${receipt.source === "WEBHOOK" ? "text-violet-300" : "text-amber-300"}`}>{receipt.source}</td>
              <td className="px-3 py-3">{receipt.status}</td>
              <td className="px-3 py-3 font-mono">{shortenGen4Address(receipt.signature, 8, 6)}</td>
              <td className="px-3 py-3">{formatGen4Date(receipt.received_at)}</td>
              <td className="px-3 py-3">{receipt.parsed_summary?.side || "N/D"}</td>
              <td className="px-3 py-3">{milliseconds(receipt.parsed_summary?.queue_latency_ms)}</td>
              <td className="px-3 py-3">{receipt.delivery_count ?? 1}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Gen4CopyabilityPanel({ status }) {
  const campaigns = useMemo(
    () => status?.active_campaigns ?? (status?.campaign ? [status.campaign] : []),
    [status]
  );
  const primaryCampaign = campaigns.find(
    (item) => item.campaign_role === "PRIMARY_FORWARD"
  );
  const [selectedCampaignId, setSelectedCampaignId] = useState(null);

  useEffect(() => {
    const stillExists = campaigns.some(
      (item) => item.campaign_id === selectedCampaignId
    );
    if (!stillExists) {
      setSelectedCampaignId(
        primaryCampaign?.campaign_id ?? campaigns[0]?.campaign_id ?? null
      );
    }
  }, [campaigns, primaryCampaign, selectedCampaignId]);

  const campaign = campaigns.find(
    (item) => item.campaign_id === selectedCampaignId
  ) ?? primaryCampaign ?? campaigns[0] ?? null;
  const metrics = campaign?.metrics ?? {};
  const counts = campaign?.counts ?? {};
  const webhook = campaign?.webhook ?? {};
  const worker = status?.worker_state ?? campaign?.worker_state ?? {};

  if (!status) {
    return (
      <section className="rounded-3xl border border-violet-900/70 bg-violet-950/15 p-5 sm:p-6">
        <p className="text-sm text-slate-400">Stato Real-Time Copyability in caricamento…</p>
      </section>
    );
  }

  return (
    <section className="overflow-hidden rounded-3xl border border-violet-800/70 bg-violet-950/15">
      <div className="border-b border-violet-900/70 p-5 sm:p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.22em] text-violet-400">
              M58–M61 · campagne isolate
            </p>
            <h2 className="mt-2 text-2xl font-black text-white">Real-Time Copyability Multi-Campaign</h2>
            <p className="mt-2 max-w-4xl leading-7 text-slate-400">
              Ogni campagna conserva wallet, anchor, ricevute, posizioni e PnL separati. Un unico Raw Webhook Helius monitora l’unione dei wallet; il routing interno impedisce che una campagna contamini l’altra. <code className="text-amber-300">RECOVERY_ONLY</code> resta escluso dalla prova.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone={status.runtime_enabled ? "good" : "bad"}>Runtime {status.runtime_enabled ? "ON" : "OFF"}</Badge>
            <Badge tone={status.worker_running ? "good" : "warn"}>Worker {status.worker_running ? "RUNNING" : "STOPPED"}</Badge>
            <Badge tone={webhook.status === "ACTIVE" ? "good" : "warn"}>Webhook {webhook.status || "NOT CONFIGURED"}</Badge>
            <Badge tone={campaign?.verdict === "PROFITABLE_EVIDENCE" ? "good" : "neutral"}>{campaign?.verdict || "WAITING"}</Badge>
            <Badge tone="neutral">Campagne {status.active_campaign_count ?? campaigns.length}</Badge>
          </div>
        </div>

        {campaigns.length > 1 && (
          <div className="mt-5 flex flex-wrap gap-2">
            {campaigns.map((item) => (
              <button
                key={item.campaign_id}
                type="button"
                onClick={() => setSelectedCampaignId(item.campaign_id)}
                className={`rounded-xl border px-4 py-2 text-xs font-black transition ${
                  item.campaign_id === campaign?.campaign_id
                    ? "border-violet-500 bg-violet-950 text-violet-200"
                    : "border-slate-700 bg-slate-950 text-slate-400 hover:border-slate-500"
                }`}
              >
                {item.campaign_role === "PRIMARY_FORWARD" ? "Primaria" : "Candidata"}
                {" · "}
                {(item.frozen_wallets ?? []).map((wallet) => shortenGen4Address(wallet, 4, 4)).join(", ")}
              </button>
            ))}
          </div>
        )}

        {!campaign ? (
          <div className="mt-5 rounded-2xl border border-amber-800 bg-amber-950/30 p-4 text-sm text-amber-200">
            La campagna real-time non è ancora stata creata. Con autostart attivo verrà collegata alla campagna forward congelata.
          </div>
        ) : (
          <>
            <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-9">
              <Metric label="Campagna" value={campaign.campaign_role === "PRIMARY_FORWARD" ? "Primaria" : "Candidata"} subtitle={`${campaign.frozen_wallets?.length ?? 0} wallet congelati`} />
              <Metric label="Età real-time" value={`${formatGen4Number(metrics.elapsed_days ?? 0, 2)} gg`} subtitle={`Anchor ${formatGen4Date(campaign.anchor_at)}`} />
              <Metric label="Chiusi copiabili" value={`${metrics.closed_copyable_trades ?? 0}/${campaign.minimum_closed_trades ?? 30}`} subtitle={`Proof ${campaign.proof_closed_trades ?? 100}`} />
              <Metric label="Rendimento netto" value={percent(metrics.net_return_percent)} subtitle={`${formatGen4Number(metrics.net_pnl_lamports ?? 0, 0)} lamport`} />
              <Metric label="Profit factor" value={formatGen4Number(metrics.profit_factor ?? 0, 2)} subtitle={`Minimo ${campaign.policy_snapshot?.minimum_profit_factor ?? 1.2}`} />
              <Metric label="Coverage webhook" value={percent(metrics.webhook_coverage_percent)} subtitle={`${metrics.webhook_reconciliation_sample ?? 0} swap riconciliati`} />
              <Metric label="Build unsigned" value={percent(metrics.unsigned_transaction_build_coverage_percent)} subtitle={`${metrics.unsigned_transaction_build_sample ?? 0} quote tentate`} />
              <Metric label="Queue mediana" value={milliseconds(metrics.median_queue_latency_ms)} subtitle={`P95 ${milliseconds(metrics.p95_queue_latency_ms)}`} />
              <Metric label="End-to-quote" value={milliseconds(metrics.p95_entry_quote_latency_ms)} subtitle="P95 sola chiamata Jupiter" />
            </div>

            <div className="mt-5 grid gap-5 rounded-2xl border border-slate-800 bg-slate-950/40 p-4 lg:grid-cols-2">
              <ProgressLine label="Giorni real-time" current={metrics.elapsed_days ?? 0} target={campaign.minimum_observation_days ?? 21} />
              <ProgressLine label="Trade chiusi copiabili" current={metrics.closed_copyable_trades ?? 0} target={campaign.minimum_closed_trades ?? 30} />
            </div>

            <div className="mt-5 flex flex-wrap gap-2">
              {(campaign.evidence_gaps ?? []).length ? campaign.evidence_gaps.map((gap) => (
                <span key={gap} className="rounded-full border border-amber-800 bg-amber-950/50 px-3 py-1.5 text-xs font-bold text-amber-200">{gap}</span>
              )) : <span className="text-sm font-bold text-emerald-300">Tutti i gate real-time risultano soddisfatti.</span>}
            </div>

            <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
              <Metric label="Webhook ricevuti" value={counts.receipt_count ?? 0} subtitle={`${counts.duplicate_receipt_count ?? 0} duplicati deduplicati`} />
              <Metric label="Recovery esclusi" value={counts.recovery_receipt_count ?? 0} subtitle="Mai conteggiati real-time" />
              <Metric label="Entrate eseguibili" value={counts.executable_entry_count ?? 0} subtitle={`${counts.rejected_entry_count ?? 0} respinte`} />
              <Metric label="Posizioni aperte" value={counts.open_position_count ?? 0} subtitle="Uscita sul SELL del wallet" />
              <Metric label="Worker iterations" value={worker.total_iterations ?? 0} subtitle={`${worker.total_failures ?? 0} fallimenti`} />
            </div>
          </>
        )}
      </div>

      {campaign && (
        <div className="grid gap-0 2xl:grid-cols-2">
          <div className="border-b border-slate-800 p-5 sm:p-6 2xl:border-b-0 2xl:border-r">
            <div className="flex items-center justify-between gap-4">
              <h3 className="font-black text-white">Simulazioni recenti</h3>
              <span className="font-mono text-xs text-slate-600">{shortenGen4Address(campaign.campaign_id, 8, 6)}</span>
            </div>
            <PositionRows positions={campaign.recent_positions} />
          </div>
          <div className="p-5 sm:p-6">
            <h3 className="font-black text-white">Webhook e riconciliazione</h3>
            <ReceiptRows receipts={campaign.recent_receipts} />
          </div>
        </div>
      )}

      <div className="border-t border-violet-900/70 bg-slate-950/50 px-5 py-4 text-xs leading-6 text-slate-500 sm:px-6">
        Signer: assente · transazioni firmate: 0 · transazioni inviate: 0 · paper: 0 · LIVE: 0 · attivazione automatica LIVE: disabilitata.
      </div>
    </section>
  );
}

export default Gen4CopyabilityPanel;
