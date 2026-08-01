import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  getDiscoveredWallets,
  refreshDiscoveredWalletActivity,
  refreshDiscoveredWalletQuality,
  runControlledDiscoveryHydration,
  runExtendedCandidateHistoryBackfill,
  runCandidatePromotionBacktest,
  runCandidateReconstructionAudit,
  runCandidatePositionLifecycleAudit,
  runCandidateExitPriceAudit,
  refreshCandidateOpenPositionExitability,
  refreshExitabilityGate,
  refreshCandidateFunnel,
  runDiscovery,
  runSmartDiscovery,
} from "../services/api";


const DISCOVERY_HISTORY_KEY = "smartmoney-discovery-history";
const ACTIVITY_OPTIONS = [
  "ALL",
  "ATTIVO",
  "POCO_ATTIVO",
  "INATTIVO",
  "IPERATTIVO",
  "NON_ANALIZZATO",
];
const QUALITY_OPTIONS = [
  "ALL",
  "COPIABILE",
  "OSSERVAZIONE",
  "SOSPETTO",
  "NON_COPIABILE",
  "NON_ANALIZZATO",
];
const PROMOTION_OPTIONS = [
  "ALL",
  "PROMOSSO",
  "OSSERVAZIONE",
  "BOCCIATO",
  "DATI_INSUFFICIENTI",
  "NON_ANALIZZATO",
];
const EXIT_PRICE_OPTIONS = [
  "ALL",
  "READY",
  "PARTIAL",
  "BLOCKED",
  "NON_ANALIZZATO",
];
const EXITABILITY_GATE_OPTIONS = [
  "ALL",
  "READY",
  "REVIEW",
  "BLOCKED",
  "NON_ANALIZZATO",
];


const DISCOVERY_FUNNEL_OPTIONS = [
  "ALL",
  "READY",
  "REVIEW",
  "BLOCKED",
  "NEEDS_LOCAL_DATA",
  "NEEDS_HISTORY",
];


function shortenAddress(address, start = 9, end = 7) {
  if (!address) return "-";
  if (address.length <= start + end + 3) return address;
  return `${address.slice(0, start)}...${address.slice(-end)}`;
}


function formatNumber(value, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "0";
  return number.toLocaleString("it-IT", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}


function formatDate(value) {
  if (!value) return "Nessuno swap";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}


function formatFrequency(value) {
  const minutes = Number(value);
  if (!Number.isFinite(minutes) || minutes <= 0) return "-";
  if (minutes < 60) return `${formatNumber(minutes, 1)} min`;
  return `${formatNumber(minutes / 60, 1)} h`;
}


function loadDiscoveryHistory() {
  try {
    const stored = window.localStorage.getItem(DISCOVERY_HISTORY_KEY);
    if (!stored) return [];
    const parsed = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    console.error("Errore caricamento cronologia discovery:", error);
    return [];
  }
}


function getResultWalletAddress(wallet) {
  return wallet?.wallet ?? wallet?.wallet_address ?? "";
}


function activityBadge(classification) {
  const normalized = classification || "NON_ANALIZZATO";
  const classes = {
    ATTIVO: "border-green-700 bg-green-950/60 text-green-300",
    POCO_ATTIVO: "border-amber-700 bg-amber-950/60 text-amber-300",
    INATTIVO: "border-slate-600 bg-slate-900 text-slate-400",
    IPERATTIVO: "border-red-700 bg-red-950/60 text-red-300",
    NON_ANALIZZATO: "border-blue-800 bg-blue-950/40 text-blue-300",
  };
  return {
    label: normalized.replace("_", " "),
    className: classes[normalized] ?? classes.NON_ANALIZZATO,
  };
}


function qualityBadge(classification) {
  const normalized = classification || "NON_ANALIZZATO";
  const classes = {
    COPIABILE: "border-green-700 bg-green-950/60 text-green-300",
    OSSERVAZIONE: "border-amber-700 bg-amber-950/60 text-amber-300",
    SOSPETTO: "border-fuchsia-700 bg-fuchsia-950/60 text-fuchsia-300",
    NON_COPIABILE: "border-red-700 bg-red-950/60 text-red-300",
    NON_ANALIZZATO: "border-blue-800 bg-blue-950/40 text-blue-300",
  };
  return {
    label: normalized.replace("_", " "),
    className: classes[normalized] ?? classes.NON_ANALIZZATO,
  };
}


function promotionBadge(status) {
  const normalized = status || "NON_ANALIZZATO";
  const classes = {
    PROMOSSO: "border-green-700 bg-green-950/60 text-green-300",
    OSSERVAZIONE: "border-amber-700 bg-amber-950/60 text-amber-300",
    BOCCIATO: "border-red-700 bg-red-950/60 text-red-300",
    DATI_INSUFFICIENTI: "border-orange-700 bg-orange-950/60 text-orange-300",
    NON_ANALIZZATO: "border-blue-800 bg-blue-950/40 text-blue-300",
  };
  return {
    label: normalized.replace("_", " "),
    className: classes[normalized] ?? classes.NON_ANALIZZATO,
  };
}


function exitPriceBadge(status) {
  const normalized = status || "NON_ANALIZZATO";
  const classes = {
    READY: "border-green-700 bg-green-950/60 text-green-300",
    PARTIAL: "border-amber-700 bg-amber-950/60 text-amber-300",
    BLOCKED: "border-red-700 bg-red-950/60 text-red-300",
    NON_ANALIZZATO: "border-blue-800 bg-blue-950/40 text-blue-300",
  };
  return {
    label: normalized.replace("_", " "),
    className: classes[normalized] ?? classes.NON_ANALIZZATO,
  };
}


function exitabilityGateBadge(status) {
  const normalized = status || "NON_ANALIZZATO";
  const classes = {
    READY: "border-green-700 bg-green-950/60 text-green-300",
    REVIEW: "border-amber-700 bg-amber-950/60 text-amber-300",
    BLOCKED: "border-red-700 bg-red-950/60 text-red-300",
    NON_ANALIZZATO: "border-blue-800 bg-blue-950/40 text-blue-300",
  };
  return {
    label: normalized.replaceAll("_", " "),
    className: classes[normalized] ?? classes.NON_ANALIZZATO,
  };
}


function discoveryFunnelBadge(status) {
  const normalized = status || "NEEDS_LOCAL_DATA";
  const classes = {
    READY: "border-green-700 bg-green-950/60 text-green-300",
    REVIEW: "border-amber-700 bg-amber-950/60 text-amber-300",
    BLOCKED: "border-red-700 bg-red-950/60 text-red-300",
    NEEDS_LOCAL_DATA: "border-blue-700 bg-blue-950/50 text-blue-300",
    NEEDS_HISTORY: "border-cyan-700 bg-cyan-950/50 text-cyan-300",
  };
  return {
    label: normalized.replaceAll("_", " "),
    className: classes[normalized] ?? classes.NEEDS_LOCAL_DATA,
  };
}


function hydrationBadge(status) {
  const normalized = status || "NEVER";
  const classes = {
    COMPLETED: "border-green-700 bg-green-950/60 text-green-300",
    EMPTY: "border-slate-600 bg-slate-900 text-slate-400",
    PARTIAL: "border-amber-700 bg-amber-950/60 text-amber-300",
    FAILED: "border-red-700 bg-red-950/60 text-red-300",
    NEVER: "border-blue-800 bg-blue-950/40 text-blue-300",
  };
  return {
    label: normalized,
    className: classes[normalized] ?? classes.NEVER,
  };
}


function eligibilityBadge(wallet) {
  if (wallet.eligible) {
    return {
      label: "IDONEO",
      className: "border-green-700 bg-green-950/60 text-green-300",
    };
  }
  return {
    label: "ESCLUSO",
    className: "border-red-800 bg-red-950/40 text-red-300",
  };
}


function StatCard({ label, value, tone = "text-white", subtitle }) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
      <p className="text-sm text-slate-400">{label}</p>
      <p className={`mt-2 text-3xl font-bold ${tone}`}>{value}</p>
      {subtitle && <p className="mt-2 text-xs text-slate-500">{subtitle}</p>}
    </div>
  );
}




function LifecycleAuditPanel({ result }) {
  if (!result) return null;

  const baseline =
    result.baseline_metrics ?? {};
  const scenarios =
    result.scenario_results ?? [];
  const details =
    result.position_details ?? [];

  return (
    <section className="mb-8 overflow-hidden rounded-xl border border-teal-800 bg-slate-800">
      <div className="border-b border-slate-700 p-5">
        <p className="font-mono text-xs text-slate-400">
          {result.wallet_address}
        </p>
        <h2 className="mt-1 text-xl font-bold text-teal-300">
          Position Lifecycle &amp; Stale Position Audit
        </h2>
        <p className="mt-2 text-xs text-amber-300">
          Diagnosi: {(result.diagnoses ?? []).join(", ")}
        </p>
        <p className="mt-2 text-xs text-slate-400">
          Solo dati cached. Nessuna richiesta Helius/Jupiter,
          nessuna modifica a LIVE, stream, worker o generazioni.
        </p>
      </div>

      <div className="p-5">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-7">
          <StatCard
            label="Posizioni aperte"
            value={baseline.open_positions ?? 0}
            tone="text-orange-300"
          />
          <StatCard
            label="BUY saltati per slot"
            value={baseline.skipped_max_positions ?? 0}
            tone="text-red-300"
          />
          <StatCard
            label="Chiuse"
            value={baseline.completed_positions ?? 0}
            tone="text-green-300"
          />
          <StatCard
            label="Copertura"
            value={`${formatNumber(
              baseline.execution_coverage_percent
            )}%`}
            tone="text-cyan-300"
          />
          <StatCard
            label="SELL abbinate"
            value={`${formatNumber(
              baseline.matched_sell_ratio_percent
            )}%`}
            tone="text-blue-300"
          />
          <StatCard
            label="Return"
            value={`${formatNumber(
              baseline.total_return_percent
            )}%`}
            tone="text-green-300"
          />
          <StatCard
            label="Max drawdown"
            value={`${formatNumber(
              baseline.max_drawdown_percent
            )}%`}
            tone="text-amber-300"
          />
        </div>

        <div className="mt-5 rounded-lg border border-slate-700 bg-slate-950/60 p-4">
          <h3 className="font-bold text-teal-300">
            Motivi posizioni ancora aperte
          </h3>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(
              result.lifecycle_summary ?? {}
            ).map(([reason, count]) => (
              <span
                key={reason}
                className="rounded-full border border-slate-700 px-2.5 py-1 text-xs text-slate-300"
              >
                {reason}: {count}
              </span>
            ))}
            {Object.keys(
              result.lifecycle_summary ?? {}
            ).length === 0 && (
              <span className="text-xs text-slate-500">
                Nessuna posizione aperta da classificare.
              </span>
            )}
          </div>
        </div>

        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[1300px] text-xs">
            <thead className="bg-slate-950 text-slate-400">
              <tr>
                <th className="p-3">Max holding</th>
                <th className="p-3">Return</th>
                <th className="p-3">Senza best</th>
                <th className="p-3">PnL</th>
                <th className="p-3">Chiuse</th>
                <th className="p-3">Forzate</th>
                <th className="p-3">Forzate bloccate</th>
                <th className="p-3">Slot liberati</th>
                <th className="p-3">Aperte</th>
                <th className="p-3">BUY eseguiti</th>
                <th className="p-3">BUY saltati slot</th>
                <th className="p-3">Copertura</th>
                <th className="p-3">DD</th>
                <th className="p-3">Delta bootstrap</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {scenarios.map((scenario) => {
                const row =
                  scenario.with_bootstrap ?? {};

                return (
                  <tr key={scenario.scenario_key}>
                    <td className="p-3 text-center">
                      {scenario.holding_period_hours == null
                        ? "Nessuna scadenza"
                        : `${scenario.holding_period_hours} h`}
                    </td>
                    <td className="p-3 text-center text-green-300">
                      {formatNumber(
                        row.total_return_percent
                      )}%
                    </td>
                    <td className="p-3 text-center text-amber-300">
                      {formatNumber(
                        row.return_without_best_trade_percent
                      )}%
                    </td>
                    <td className="p-3 text-center">
                      {formatNumber(
                        row.net_pnl_sol,
                        4
                      )} SOL
                    </td>
                    <td className="p-3 text-center">
                      {row.completed_positions ?? 0}
                    </td>
                    <td className="p-3 text-center">
                      {row.forced_closes ?? 0}
                    </td>
                    <td className="p-3 text-center text-orange-300">
                      {row.forced_close_skipped_unquotable ?? 0}
                    </td>
                    <td className="p-3 text-center text-teal-300">
                      {row.positions_freed_by_expiry ?? 0}
                    </td>
                    <td className="p-3 text-center">
                      {row.open_positions ?? 0}
                    </td>
                    <td className="p-3 text-center">
                      {row.executed_buys ?? 0}
                    </td>
                    <td className="p-3 text-center text-red-300">
                      {row.skipped_max_positions ?? 0}
                    </td>
                    <td className="p-3 text-center">
                      {formatNumber(
                        row.execution_coverage_percent
                      )}%
                    </td>
                    <td className="p-3 text-center">
                      {formatNumber(
                        row.max_drawdown_percent
                      )}%
                    </td>
                    <td className="p-3 text-center">
                      {formatNumber(
                        scenario.bootstrap_delta
                          ?.return_percent
                      )}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="mt-5 overflow-x-auto">
          <h3 className="mb-3 font-bold text-teal-300">
            Dettaglio lifecycle delle posizioni aperte
          </h3>
          <table className="w-full min-w-[1500px] text-xs">
            <thead className="bg-slate-950 text-slate-400">
              <tr>
                <th className="p-3">Token</th>
                <th className="p-3">Bootstrap</th>
                <th className="p-3">Motivo</th>
                <th className="p-3">Eta fine</th>
                <th className="p-3">BUY sorgente</th>
                <th className="p-3">SELL sorgente</th>
                <th className="p-3">Uscita abbinata</th>
                <th className="p-3">Residuo</th>
                <th className="p-3">Costo residuo</th>
                <th className="p-3">Ultima attivita</th>
                <th className="p-3">Cache Jupiter</th>
                <th className="p-3">Ultimo prezzo cached</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {details.map((item) => (
                <tr key={`${item.token_mint}-${item.entry_at}`}>
                  <td className="p-3 font-mono">
                    {shortenAddress(
                      item.token_mint,
                      7,
                      5
                    )}
                  </td>
                  <td className="p-3 text-center">
                    {item.bootstrap ? "SI" : "NO"}
                  </td>
                  <td className="p-3 text-center text-orange-300">
                    {item.reason_still_open}
                  </td>
                  <td className="p-3 text-center">
                    {formatNumber(
                      item.age_at_analysis_end_hours,
                      1
                    )} h
                  </td>
                  <td className="p-3 text-center">
                    {item.source_buys_total ?? 0}
                  </td>
                  <td className="p-3 text-center">
                    {item.source_sells_total ?? 0}
                  </td>
                  <td className="p-3 text-center">
                    {formatNumber(
                      item.matched_exit_fraction_percent
                    )}%
                  </td>
                  <td className="p-3 text-center">
                    {formatNumber(
                      item.remaining_fraction_percent
                    )}%
                  </td>
                  <td className="p-3 text-center">
                    {formatNumber(
                      item.remaining_cost_basis_sol,
                      4
                    )} SOL
                  </td>
                  <td className="p-3 text-center">
                    {formatDate(
                      item.last_source_activity_at
                    )}
                  </td>
                  <td className="p-3 text-center">
                    {item.cached_jupiter_compatible
                      ? "COMPATIBILE"
                      : item.cached_jupiter_status}
                  </td>
                  <td className="p-3 text-center">
                    {formatNumber(
                      item.last_executable_price_sol,
                      8
                    )}
                  </td>
                </tr>
              ))}
              {details.length === 0 && (
                <tr>
                  <td
                    colSpan="12"
                    className="p-6 text-center text-slate-500"
                  >
                    Nessuna posizione aperta nel baseline.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}


function ExitPriceAuditPanel({ result }) {
  if (!result) return null;

  const summary = result.summary ?? {};
  const readiness = exitPriceBadge(result.readiness_status);

  return (
    <section className="mb-8 overflow-hidden rounded-xl border border-rose-900 bg-slate-800">
      <div className="border-b border-slate-700 p-5">
        <p className="font-mono text-xs text-slate-400">{result.wallet_address}</p>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-rose-300">
            Exit Price Provenance &amp; Cached Coverage Audit
          </h2>
          <span className={`rounded-full border px-2.5 py-1 text-xs font-bold ${readiness.className}`}>
            {readiness.label} · {formatNumber(result.readiness_score)}%
          </span>
        </div>
        <p className="mt-2 text-xs text-amber-300">
          Diagnosi: {(result.diagnoses ?? []).join(", ")}
        </p>
        <p className="mt-2 text-xs text-slate-400">
          Separa prezzo osservabile, route cached attuale e prova temporale storica.
          Nessun look-ahead, nessuna richiesta Helius/Jupiter e nessuna modifica operativa.
        </p>
        <p className="mt-2 font-mono text-xs text-cyan-300">
          Lifecycle sorgente: {result.parameters?.source_lifecycle_run_id ?? "-"}
          {" · "}aperte {summary.source_lifecycle_open_positions ?? summary.positions_analyzed ?? 0}
          {" · "}analizzate {summary.positions_analyzed ?? 0}
          {" · "}max slot {result.parameters?.source_lifecycle_max_open_positions ?? "-"}
        </p>
        {summary.position_count_matches_lifecycle === false && (
          <p className="mt-2 text-xs font-bold text-red-300">
            Audit non allineato: il numero di posizioni non coincide con il lifecycle sorgente.
          </p>
        )}
      </div>

      <div className="p-5">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-7">
          <StatCard label="Posizioni" value={summary.positions_analyzed ?? 0} tone="text-orange-300" />
          <StatCard label="Prezzo locale fresco" value={`${formatNumber(summary.local_observable_percent)}%`} tone="text-cyan-300" />
          <StatCard label="Route cached attuale" value={`${formatNumber(summary.current_route_supported_percent)}%`} tone="text-green-300" />
          <StatCard label="Prova temporale" value={`${formatNumber(summary.temporal_execution_percent)}%`} tone="text-indigo-300" />
          <StatCard label="Cache mancanti" value={summary.cache_missing ?? 0} tone="text-red-300" />
          <StatCard label="Prezzi stale" value={summary.stale_local_prices ?? 0} tone="text-amber-300" />
          <StatCard label="Copertura valutazione" value={`${formatNumber(summary.valuation_coverage_percent)}%`} tone="text-fuchsia-300" />
        </div>

        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[1250px] text-xs">
            <thead className="bg-slate-950 text-slate-400">
              <tr>
                <th className="p-3">Scenario</th>
                <th className="p-3">Dovute</th>
                <th className="p-3">Non dovute</th>
                <th className="p-3">Prezzo fresco</th>
                <th className="p-3">Route attuale</th>
                <th className="p-3">Prova temporale</th>
                <th className="p-3">Cache presente</th>
                <th className="p-3">Stale</th>
                <th className="p-3">Mancanti</th>
                <th className="p-3">Valore osservabile</th>
                <th className="p-3">PnL osservabile</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {(result.scenario_results ?? []).map((row) => (
                <tr key={row.scenario_key}>
                  <td className="p-3 font-bold text-rose-300">
                    {row.holding_period_hours == null ? "Fine analisi" : `${row.holding_period_hours} h`}
                  </td>
                  <td className="p-3 text-center">{row.positions_due}</td>
                  <td className="p-3 text-center">{row.positions_not_due}</td>
                  <td className="p-3 text-center text-cyan-300">{formatNumber(row.local_observable_percent)}%</td>
                  <td className="p-3 text-center text-green-300">{formatNumber(row.current_route_supported_percent)}%</td>
                  <td className="p-3 text-center text-indigo-300">{formatNumber(row.temporal_execution_percent)}%</td>
                  <td className="p-3 text-center">{formatNumber(row.cache_present_percent)}%</td>
                  <td className="p-3 text-center">{row.stale_local_prices}</td>
                  <td className="p-3 text-center">{row.missing_local_prices}</td>
                  <td className="p-3 text-center">{formatNumber(row.observable_value_sol, 4)} SOL</td>
                  <td className="p-3 text-center">{formatNumber(row.observable_pnl_sol, 4)} SOL</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-5 overflow-x-auto">
          <h3 className="mb-3 font-bold text-rose-300">Provenienza prezzi alla fine dell’analisi</h3>
          <table className="w-full min-w-[1400px] text-xs">
            <thead className="bg-slate-950 text-slate-400">
              <tr>
                <th className="p-3">Token</th>
                <th className="p-3">Bootstrap</th>
                <th className="p-3">Stato evidenza</th>
                <th className="p-3">Prezzo</th>
                <th className="p-3">Età prezzo</th>
                <th className="p-3">Side / fonte</th>
                <th className="p-3">Cache</th>
                <th className="p-3">Route attuale</th>
                <th className="p-3">Temporale</th>
                <th className="p-3">PnL osservabile</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {(result.position_results ?? []).map((position) => {
                const evidence = position.scenario_evidence?.[0] ?? {};
                return (
                  <tr key={position.token_mint}>
                    <td className="p-3 font-mono text-slate-300">{shortenAddress(position.token_mint, 7, 5)}</td>
                    <td className="p-3 text-center">{position.bootstrap ? "SI" : "NO"}</td>
                    <td className="p-3 text-center text-amber-300">{evidence.evidence_status ?? "-"}</td>
                    <td className="p-3 text-center">{evidence.local_price_sol == null ? "-" : formatNumber(evidence.local_price_sol, 8)}</td>
                    <td className="p-3 text-center">{evidence.local_price_age_hours == null ? "-" : `${formatNumber(evidence.local_price_age_hours, 1)} h`}</td>
                    <td className="p-3 text-center">{evidence.local_price_side ?? "-"} / {evidence.local_price_source ?? "-"}</td>
                    <td className="p-3 text-center">{evidence.cache?.status ?? "CACHE_MISSING"}</td>
                    <td className="p-3 text-center">{evidence.current_route_supported ? "SI" : "NO"}</td>
                    <td className="p-3 text-center">{evidence.temporal_executable ? "SI" : "NO"}</td>
                    <td className="p-3 text-center">{evidence.observable_pnl_sol == null ? "-" : `${formatNumber(evidence.observable_pnl_sol, 4)} SOL`}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}


function ExitabilityRefreshPanel({ result }) {
  if (!result) return null;

  const summary = result.summary ?? {};
  const rows = result.results ?? [];

  return (
    <section className="mb-8 overflow-hidden rounded-xl border border-violet-900 bg-slate-800">
      <div className="border-b border-slate-700 p-5">
        <p className="font-mono text-xs text-slate-400">{result.wallet_address}</p>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-bold text-violet-300">
            Open Position Jupiter Exitability Refresh
          </h2>
          <span className="rounded-full border border-violet-700 bg-violet-950/60 px-2.5 py-1 text-xs font-bold text-violet-200">
            {result.status}
          </span>
        </div>
        <p className="mt-2 text-xs text-slate-400">
          Aggiorna solo le quote Jupiter cached per i token ancora aperti nello
          snapshot lifecycle selezionato. Nessuna firma, invio, modifica LIVE,
          stream o worker.
        </p>
        <p className="mt-2 font-mono text-xs text-cyan-300">
          Lifecycle: {result.lifecycle_run_id} · profilo: {result.parameters?.quote_profile}
        </p>
      </div>

      <div className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-8">
        {[
          ["Posizioni", summary.source_open_positions],
          ["Token controllati", summary.tokens_checked],
          ["Route trovate", summary.route_found],
          ["No route", summary.no_route],
          ["Errori quote", summary.quote_errors],
          ["Route riusate", summary.reused_current_routes],
          ["Retry", summary.retry_attempts],
          ["Richieste Jupiter", summary.requests],
        ].map(([label, value]) => (
          <div key={label} className="rounded-lg border border-slate-700 bg-slate-950/60 p-3">
            <p className="text-xs text-slate-500">{label}</p>
            <p className="mt-1 text-xl font-bold text-white">{value ?? 0}</p>
          </div>
        ))}
      </div>

      <div className="overflow-x-auto px-5 pb-5">
        <table className="min-w-full text-xs">
          <thead className="bg-slate-950 text-slate-400">
            <tr>
              <th className="p-3 text-left">Token</th>
              <th className="p-3 text-center">Esito</th>
              <th className="p-3 text-center">BUY quote</th>
              <th className="p-3 text-center">SELL quote</th>
              <th className="p-3 text-center">Fonte</th>
              <th className="p-3 text-left">Errore</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item, index) => (
              <tr key={`${item.token_mint}-${index}`} className="border-t border-slate-700">
                <td className="p-3 font-mono text-slate-300">
                  {shortenAddress(item.token_mint, 9, 7)}
                </td>
                <td className="p-3 text-center font-bold text-violet-200">
                  {item.result_status}
                </td>
                <td className="p-3 text-center">{item.buy_quote ? "SI" : "NO"}</td>
                <td className="p-3 text-center">{item.sell_quote ? "SI" : "NO"}</td>
                <td className="p-3 text-center">{item.source ?? "-"}</td>
                <td className="p-3 text-slate-400">
                  {item.error_code
                    ? `${item.error_code}: ${item.error_message ?? ""}`
                    : "-"}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan="6" className="p-6 text-center text-slate-500">
                  Nessuna posizione aperta da verificare.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}


function Discovery() {
  const [mode, setMode] = useState("FULL");
  const [seedWallet, setSeedWallet] = useState("");
  const [maxTokens, setMaxTokens] = useState(3);
  const [maxWalletsPerToken, setMaxWalletsPerToken] = useState(3);
  const [maxDepth, setMaxDepth] = useState(2);
  const [maxTokensPerWallet, setMaxTokensPerWallet] = useState(5);
  const [smartMaxWalletsPerToken, setSmartMaxWalletsPerToken] = useState(5);
  const [minSmartScore, setMinSmartScore] = useState(60);

  const [hydrationMaxWallets, setHydrationMaxWallets] = useState(3);
  const [hydrationRequestBudget, setHydrationRequestBudget] = useState(3);
  const [hydrationLookbackDays, setHydrationLookbackDays] = useState(7);
  const [hydrationTransactionLimit, setHydrationTransactionLimit] = useState(100);
  const [hydrationMinimumScore, setHydrationMinimumScore] = useState(0);
  const [hydrationResult, setHydrationResult] = useState(null);

  const [candidateWallet, setCandidateWallet] = useState("");
  const [historyLookbackDays, setHistoryLookbackDays] = useState(30);
  const [historyRequestBudget, setHistoryRequestBudget] = useState(5);
  const [historyPageSize, setHistoryPageSize] = useState(100);
  const [extendedHistoryResult, setExtendedHistoryResult] = useState(null);
  const [backtestLookbackDays, setBacktestLookbackDays] = useState(30);
  const [backtestWarmupDays, setBacktestWarmupDays] = useState(14);
  const [backtestStartingCapital, setBacktestStartingCapital] = useState(1);
  const [backtestBuySize, setBacktestBuySize] = useState(0.05);
  const [backtestSlippageBps, setBacktestSlippageBps] = useState(100);
  const [backtestFeeBps, setBacktestFeeBps] = useState(10);
  const [backtestDelaySeconds, setBacktestDelaySeconds] = useState(8);
  const [backtestMaxOpenPositions, setBacktestMaxOpenPositions] = useState(5);
  const [backtestCheckJupiter, setBacktestCheckJupiter] = useState(true);
  const [backtestJupiterCacheTtlHours, setBacktestJupiterCacheTtlHours] = useState(6);
  const [backtestForceJupiterRefresh, setBacktestForceJupiterRefresh] = useState(false);
  const [promotionResult, setPromotionResult] = useState(null);
  const [reconstructionAuditResult, setReconstructionAuditResult] = useState(null);
  const [lifecycleAuditResult, setLifecycleAuditResult] = useState(null);
  const [exitPriceAuditResult, setExitPriceAuditResult] = useState(null);
  const [exitabilityRefreshResult, setExitabilityRefreshResult] = useState(null);
  const [maxLocalPriceAgeHours, setMaxLocalPriceAgeHours] = useState(24);

  const [discoveredWallets, setDiscoveredWallets] = useState([]);
  const [result, setResult] = useState(null);
  const [historyItems, setHistoryItems] = useState(loadDiscoveryHistory);

  const [search, setSearch] = useState("");
  const [minimumScore, setMinimumScore] = useState(0);
  const [activityFilter, setActivityFilter] = useState("ALL");
  const [qualityFilter, setQualityFilter] = useState("ALL");
  const [promotionFilter, setPromotionFilter] = useState("ALL");
  const [exitPriceFilter, setExitPriceFilter] = useState("ALL");
  const [exitabilityGateFilter, setExitabilityGateFilter] = useState("ALL");
  const [discoveryFunnelFilter, setDiscoveryFunnelFilter] = useState("ALL");
  const [eligibleOnly, setEligibleOnly] = useState(false);
  const [sortBy, setSortBy] = useState("ranking_score");

  const [loadingWallets, setLoadingWallets] = useState(true);
  const [running, setRunning] = useState(false);
  const [hydrating, setHydrating] = useState(false);
  const [refreshingActivity, setRefreshingActivity] = useState(false);
  const [refreshingQuality, setRefreshingQuality] = useState(false);
  const [refreshingExitabilityGate, setRefreshingExitabilityGate] = useState(false);
  const [exitabilityGateResult, setExitabilityGateResult] = useState(null);
  const [refreshingCandidateFunnel, setRefreshingCandidateFunnel] = useState(false);
  const [candidateFunnelResult, setCandidateFunnelResult] = useState(null);
  const [funnelHistoryBudget, setFunnelHistoryBudget] = useState(10);
  const [funnelMaxHistoryWallets, setFunnelMaxHistoryWallets] = useState(5);
  const [funnelTargetHistoryDays, setFunnelTargetHistoryDays] = useState(30);
  const [runningBackfill, setRunningBackfill] = useState(false);
  const [runningBacktest, setRunningBacktest] = useState(false);
  const [runningReconstructionAudit, setRunningReconstructionAudit] = useState(false);
  const [runningLifecycleAudit, setRunningLifecycleAudit] = useState(false);
  const [runningExitPriceAudit, setRunningExitPriceAudit] = useState(false);
  const [runningExitabilityRefresh, setRunningExitabilityRefresh] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadDiscoveredWallets = useCallback(async (preferredWallet = "") => {
    setLoadingWallets(true);
    try {
      const response = await getDiscoveredWallets(0, 500);
      const rows = Array.isArray(response.data) ? response.data : [];
      const requestedWallet =
        typeof preferredWallet === "string"
          ? preferredWallet.trim()
          : "";

      setDiscoveredWallets(rows);
      setCandidateWallet((current) => {
        const candidate = requestedWallet || current;

        if (
          candidate &&
          rows.some(
            (wallet) =>
              wallet.wallet_address === candidate
          )
        ) {
          return candidate;
        }

        return "";
      });
    } catch (requestError) {
      console.error("Errore caricamento wallet scoperti:", requestError);
      setError("Impossibile caricare i wallet scoperti dal backend.");
    } finally {
      setLoadingWallets(false);
    }
  }, []);


  useEffect(() => {
    loadDiscoveredWallets();
  }, [loadDiscoveredWallets]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        DISCOVERY_HISTORY_KEY,
        JSON.stringify(historyItems)
      );
    } catch (storageError) {
      console.error("Errore salvataggio cronologia:", storageError);
    }
  }, [historyItems]);

  const filteredWallets = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    return [...discoveredWallets]
      .filter((wallet) => {
        const matchesSearch =
          !normalizedSearch ||
          String(wallet.wallet_address ?? "").toLowerCase().includes(normalizedSearch) ||
          String(wallet.discovered_from_token ?? "").toLowerCase().includes(normalizedSearch) ||
          String(wallet.activity_classification ?? "").toLowerCase().includes(normalizedSearch) ||
          String(wallet.quality_classification ?? "").toLowerCase().includes(normalizedSearch) ||
          String(wallet.promotion_status ?? "").toLowerCase().includes(normalizedSearch) ||
          String(wallet.hydration_status ?? "").toLowerCase().includes(normalizedSearch) ||
          String(wallet.extended_history_status ?? "").toLowerCase().includes(normalizedSearch) ||
          String(wallet.exit_price_coverage_status ?? "").toLowerCase().includes(normalizedSearch) ||
          String(wallet.exitability_gate_status ?? "").toLowerCase().includes(normalizedSearch) ||
          String(wallet.discovery_funnel_status ?? "").toLowerCase().includes(normalizedSearch) ||
          String(wallet.discovery_funnel_action ?? "").toLowerCase().includes(normalizedSearch);
        const matchesScore = Number(wallet.smart_score ?? 0) >= Number(minimumScore || 0);
        const matchesActivity =
          activityFilter === "ALL" || wallet.activity_classification === activityFilter;
        const matchesQuality =
          qualityFilter === "ALL" || wallet.quality_classification === qualityFilter;
        const matchesPromotion =
          promotionFilter === "ALL" || wallet.promotion_status === promotionFilter;
        const matchesExitPrice =
          exitPriceFilter === "ALL" ||
          wallet.exit_price_coverage_status === exitPriceFilter;
        const matchesExitabilityGate =
          exitabilityGateFilter === "ALL" ||
          wallet.exitability_gate_status === exitabilityGateFilter;
        const matchesDiscoveryFunnel =
          discoveryFunnelFilter === "ALL" ||
          wallet.discovery_funnel_status === discoveryFunnelFilter;
        const matchesEligibility = !eligibleOnly || Boolean(wallet.eligible);
        return matchesSearch && matchesScore && matchesActivity && matchesQuality && matchesPromotion && matchesExitPrice && matchesExitabilityGate && matchesDiscoveryFunnel && matchesEligibility;
      })
      .sort((first, second) => {
        if (sortBy === "last_swap_at") {
          return new Date(second.last_swap_at ?? 0) - new Date(first.last_swap_at ?? 0);
        }
        if (sortBy === "discovery_funnel_priority") {
          const firstPriority = Number(first.discovery_funnel_priority ?? 0);
          const secondPriority = Number(second.discovery_funnel_priority ?? 0);
          const normalizedFirst = firstPriority > 0 ? firstPriority : Number.MAX_SAFE_INTEGER;
          const normalizedSecond = secondPriority > 0 ? secondPriority : Number.MAX_SAFE_INTEGER;
          return normalizedFirst - normalizedSecond;
        }
        return Number(second[sortBy] ?? 0) - Number(first[sortBy] ?? 0);
      });
  }, [
    discoveredWallets,
    search,
    minimumScore,
    activityFilter,
    qualityFilter,
    promotionFilter,
    exitPriceFilter,
    exitabilityGateFilter,
    discoveryFunnelFilter,
    eligibleOnly,
    sortBy,
  ]);

  const resultRanking = useMemo(
    () => (Array.isArray(result?.ranking) ? result.ranking : []),
    [result]
  );


  const selectedCandidate = useMemo(
    () =>
      discoveredWallets.find(
        (wallet) =>
          wallet.wallet_address === candidateWallet
      ) ?? null,
    [discoveredWallets, candidateWallet]
  );

  const summary = useMemo(() => {
    const activityCount = (classification) =>
      discoveredWallets.filter(
        (wallet) => wallet.activity_classification === classification
      ).length;
    const qualityCount = (classification) =>
      discoveredWallets.filter(
        (wallet) => wallet.quality_classification === classification
      ).length;
    const promotionCount = (status) =>
      discoveredWallets.filter((wallet) => wallet.promotion_status === status).length;
    return {
      total: discoveredWallets.length,
      eligible: discoveredWallets.filter((wallet) => wallet.eligible).length,
      active: activityCount("ATTIVO"),
      low: activityCount("POCO_ATTIVO"),
      inactive: activityCount("INATTIVO"),
      hyperactive: activityCount("IPERATTIVO"),
      copyable: qualityCount("COPIABILE"),
      observation: qualityCount("OSSERVAZIONE"),
      suspicious: qualityCount("SOSPETTO"),
      notCopyable: qualityCount("NON_COPIABILE"),
      promoted: promotionCount("PROMOSSO"),
      promotionObservation: promotionCount("OSSERVAZIONE"),
      rejected: promotionCount("BOCCIATO"),
      insufficient: promotionCount("DATI_INSUFFICIENTI"),
      promotionNotAnalyzed: promotionCount("NON_ANALIZZATO"),
    };
  }, [discoveredWallets]);

  function addHistoryItem(responseData) {
    const newItem = {
      id: globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`,
      mode,
      seed_wallet: seedWallet.trim(),
      created_at: new Date().toISOString(),
      wallets_found:
        mode === "SMART"
          ? responseData.smart_wallets_found ?? 0
          : responseData.wallets_discovered ?? 0,
      wallets_analyzed: responseData.wallets_analyzed ?? responseData.ranking?.length ?? 0,
      wallets_eligible: responseData.wallets_eligible ?? 0,
    };
    setHistoryItems((items) => [newItem, ...items].slice(0, 20));
  }

  function handleCandidateWalletSelection(
    walletAddress,
    scrollToAnalysis = false
  ) {
    const wallet = String(
      walletAddress || ""
    ).trim();

    setCandidateWallet(wallet);
    setExtendedHistoryResult(null);
    setPromotionResult(null);
    setReconstructionAuditResult(null);
    setLifecycleAuditResult(null);
    setExitPriceAuditResult(null);
    setExitabilityRefreshResult(null);
    setError("");
    setMessage(
      wallet
        ? `Wallet selezionato: ${wallet}`
        : ""
    );

    if (
      scrollToAnalysis &&
      typeof document !== "undefined"
    ) {
      globalThis.requestAnimationFrame?.(() => {
        document
          .getElementById("candidate-analysis")
          ?.scrollIntoView({
            behavior: "smooth",
            block: "start",
          });
      });
    }
  }


  function handleSelectFunnelWallet(row) {
    handleCandidateWalletSelection(
      row?.wallet_address,
      true
    );

    const suggestedBudget = Number(
      row?.allocated_requests ??
        row?.recommended_requests ??
        0
    );

    if (
      Number.isFinite(suggestedBudget) &&
      suggestedBudget > 0
    ) {
      setHistoryRequestBudget(
        Math.min(
          20,
          Math.max(1, suggestedBudget)
        )
      );
    }
  }


  async function handleRunDiscovery() {
    const normalizedWallet = seedWallet.trim();
    if (!normalizedWallet) {
      setError("Inserisci un seed wallet.");
      return;
    }

    setRunning(true);
    setError("");
    setMessage("");
    setResult(null);

    try {
      const response =
        mode === "SMART"
          ? await runSmartDiscovery(
              normalizedWallet,
              maxDepth,
              maxTokensPerWallet,
              smartMaxWalletsPerToken,
              minSmartScore
            )
          : await runDiscovery(
              normalizedWallet,
              maxTokens,
              maxWalletsPerToken
            );
      setResult(response.data);
      addHistoryItem(response.data);
      setMessage(
        `Discovery completata: ${response.data.wallets_analyzed ?? 0} wallet analizzati, ${response.data.wallets_eligible ?? 0} idonei.`
      );
      await loadDiscoveredWallets();
    } catch (requestError) {
      console.error("Errore durante la discovery:", requestError);
      const backendMessage = requestError.response?.data?.detail;
      setError(
        typeof backendMessage === "string"
          ? backendMessage
          : "Discovery non completata. Controlla backend, seed wallet e limiti Helius."
      );
    } finally {
      setRunning(false);
    }
  }

  async function handleHydration() {
    setHydrating(true);
    setError("");
    setMessage("");
    setHydrationResult(null);

    try {
      const response = await runControlledDiscoveryHydration({
        maxWallets: hydrationMaxWallets,
        maxHeliusRequests: hydrationRequestBudget,
        lookbackDays: hydrationLookbackDays,
        transactionLimit: hydrationTransactionLimit,
        minimumSmartScore: hydrationMinimumScore,
        force: false,
      });
      setHydrationResult(response.data);
      setMessage(
        `Hydration ${response.data.status}: ${response.data.wallets_attempted} wallet, ${response.data.helius_requests} richieste Helius, ${response.data.swaps_found} swap trovati e ${response.data.trades_imported} trade importati.`
      );
      await loadDiscoveredWallets();
    } catch (requestError) {
      console.error("Errore Discovery Hydration:", requestError);
      const backendMessage = requestError.response?.data?.detail;
      setError(
        typeof backendMessage === "string"
          ? backendMessage
          : "Discovery Hydration non completata. Nessun worker o stream è stato avviato."
      );
    } finally {
      setHydrating(false);
    }
  }


  async function handleRefreshActivity() {
    setRefreshingActivity(true);
    setError("");
    setMessage("");
    try {
      const response = await refreshDiscoveredWalletActivity(500);
      setMessage(
        `${response.data.wallets_refreshed} wallet ricalcolati dal database. Richieste Helius: ${response.data.helius_requests}.`
      );
      await loadDiscoveredWallets();
    } catch (requestError) {
      console.error("Errore ricalcolo attività:", requestError);
      setError("Impossibile ricalcolare il ranking attività dal database.");
    } finally {
      setRefreshingActivity(false);
    }
  }

  async function handleRefreshQuality() {
    setRefreshingQuality(true);
    setError("");
    setMessage("");
    try {
      const response = await refreshDiscoveredWalletQuality(500);
      setMessage(
        `Qualità ricalcolata su ${response.data.wallets_refreshed} wallet: ${response.data.copyable} copiabili, ${response.data.observation} in osservazione, ${response.data.suspicious} sospetti e ${response.data.not_copyable} non copiabili. Helius: ${response.data.helius_requests}.`
      );
      await loadDiscoveredWallets();
    } catch (requestError) {
      console.error("Errore ricalcolo qualità:", requestError);
      setError("Impossibile ricalcolare la qualità di esecuzione dal database.");
    } finally {
      setRefreshingQuality(false);
    }
  }


  async function handleRefreshExitabilityGate() {
    setRefreshingExitabilityGate(true);
    setError("");
    setMessage("");
    setExitabilityGateResult(null);
    try {
      const response = await refreshExitabilityGate(500);
      setExitabilityGateResult(response.data);
      const summary = response.data?.summary ?? {};
      setMessage(
        `Exitability gate: ${summary.wallets_ready ?? 0} ready, ` +
        `${summary.wallets_review ?? 0} review, ` +
        `${summary.wallets_blocked ?? 0} blocked, ` +
        `${summary.wallets_not_analyzed ?? 0} non analizzati.`
      );
      await loadDiscoveredWallets();
    } catch (requestError) {
      console.error("Errore exitability gate:", requestError);
      setError("Impossibile aggiornare il safety gate di exitability.");
    } finally {
      setRefreshingExitabilityGate(false);
    }
  }


  async function handleRefreshCandidateFunnel() {
    setRefreshingCandidateFunnel(true);
    setError("");
    setMessage("");
    setCandidateFunnelResult(null);
    try {
      const response = await refreshCandidateFunnel({
        limit: 500,
        historyRequestBudget: Number(funnelHistoryBudget),
        maxHistoryWallets: Number(funnelMaxHistoryWallets),
        targetHistoryDays: Number(funnelTargetHistoryDays),
      });
      setCandidateFunnelResult(response.data);
      const funnelSummary = response.data?.summary ?? {};
      setMessage(
        `Candidate funnel: ${funnelSummary.wallets_ready ?? 0} ready, ` +
        `${funnelSummary.wallets_review ?? 0} review, ` +
        `${funnelSummary.wallets_blocked ?? 0} blocked, ` +
        `${funnelSummary.wallets_needs_local_data ?? 0} con dati locali insufficienti, ` +
        `${funnelSummary.wallets_needs_history ?? 0} da approfondire. ` +
        `Budget storico allocato: ${funnelSummary.history_budget_allocated ?? 0}.`
      );
      await loadDiscoveredWallets();
    } catch (requestError) {
      console.error("Errore candidate funnel:", requestError);
      setError("Impossibile calcolare il candidate funnel.");
    } finally {
      setRefreshingCandidateFunnel(false);
    }
  }


  async function handleExtendedHistoryBackfill(walletAddress = candidateWallet) {
    const wallet = String(walletAddress || "").trim();
    if (!wallet) {
      setError("Seleziona un wallet candidato per lo storico esteso.");
      return;
    }
    setRunningBackfill(true);
    setError("");
    setMessage("");
    setExtendedHistoryResult(null);
    try {
      const response = await runExtendedCandidateHistoryBackfill({
        walletAddress: wallet,
        lookbackDays: historyLookbackDays,
        maxHeliusRequests: historyRequestBudget,
        pageSize: historyPageSize,
      });
      setExtendedHistoryResult(response.data);
      setCandidateWallet(wallet);

      const resumed = Boolean(
        response.data.parameters?.resumed
      );

      setMessage(
        `Storico ${resumed ? "ripreso dal cursore salvato" : "esteso"} ${response.data.status}: ${response.data.trades_imported} nuovi swap, ${response.data.trades_updated} aggiornati, ${response.data.helius_requests}/${response.data.request_budget} richieste Helius.`
      );
      await loadDiscoveredWallets(wallet);
    } catch (requestError) {
      console.error("Errore Extended Candidate History:", requestError);
      const backendMessage = requestError.response?.data?.detail;
      setError(
        typeof backendMessage === "string"
          ? backendMessage
          : "Storico esteso non completato. LIVE, stream e worker non sono stati modificati."
      );
    } finally {
      setRunningBackfill(false);
    }
  }


  async function handlePromotionBacktest(walletAddress = candidateWallet) {
    const wallet = String(walletAddress || "").trim();
    if (!wallet) {
      setError("Seleziona un wallet candidato per il backtest.");
      return;
    }
    setRunningBacktest(true);
    setError("");
    setMessage("");
    setPromotionResult(null);
    setReconstructionAuditResult(null);
    setLifecycleAuditResult(null);
    setExitPriceAuditResult(null);
    setExitabilityRefreshResult(null);
    try {
      const response = await runCandidatePromotionBacktest({
        walletAddress: wallet,
        lookbackDays: backtestLookbackDays,
        warmupDays: backtestWarmupDays,
        startingCapitalSol: backtestStartingCapital,
        fixedBuySizeSol: backtestBuySize,
        slippageBps: backtestSlippageBps,
        feeBps: backtestFeeBps,
        copyDelaySeconds: backtestDelaySeconds,
        maxOpenPositions: backtestMaxOpenPositions,
        checkJupiter: backtestCheckJupiter,
        jupiterTokenLimit: 10,
        jupiterCacheTtlHours: backtestJupiterCacheTtlHours,
        forceJupiterRefresh: backtestForceJupiterRefresh,
      });
      setPromotionResult(response.data);
      setCandidateWallet(wallet);
      setMessage(
        `Backtest ${response.data.decision}: score ${formatNumber(response.data.score)}, rendimento ${formatNumber(response.data.total_return_percent)}%, drawdown ${formatNumber(response.data.max_drawdown_percent)}%.`
      );
      await loadDiscoveredWallets(wallet);
    } catch (requestError) {
      console.error("Errore Candidate Backtest:", requestError);
      const backendMessage = requestError.response?.data?.detail;
      setError(
        typeof backendMessage === "string"
          ? backendMessage
          : "Backtest candidato non completato. Nessuna transazione è stata firmata o inviata."
      );
    } finally {
      setRunningBacktest(false);
    }
  }


async function handleReconstructionAudit(
  walletAddress = candidateWallet
) {
  const wallet = String(
    walletAddress || ""
  ).trim();

  if (!wallet) {
    setError(
      "Seleziona un wallet candidato per l'audit."
    );
    return;
  }

  setRunningReconstructionAudit(true);
  setError("");
  setMessage("");
  setReconstructionAuditResult(null);

  try {
    const response =
      await runCandidateReconstructionAudit({
        walletAddress: wallet,
        lookbackDays: backtestLookbackDays,
        warmupDays: backtestWarmupDays,
        fixedBuySizeSol: backtestBuySize,
        slippageBps: backtestSlippageBps,
        feeBps: backtestFeeBps,
        copyDelaySeconds: backtestDelaySeconds,
        baselineStartingCapitalSol:
          backtestStartingCapital,
        baselineMaxOpenPositions:
          backtestMaxOpenPositions,
        maxExcludedTrades: 500,
      });

    setReconstructionAuditResult(
      response.data
    );
    setCandidateWallet(wallet);

    setMessage(
      `Audit completato: ${
        response.data.scenario_results?.length ?? 0
      } scenari e ${
        response.data.excluded_trades?.length ?? 0
      } eventi dettagliati.`
    );
  } catch (requestError) {
    console.error(
      "Errore Trade Reconstruction Audit:",
      requestError
    );

    const backendMessage =
      requestError.response?.data?.detail;

    setError(
      typeof backendMessage === "string"
        ? backendMessage
        : "Audit non completato. Nessuna funzione LIVE e stata modificata."
    );
  } finally {
    setRunningReconstructionAudit(false);
  }
}


async function handleLifecycleAudit(
  walletAddress = candidateWallet
) {
  const wallet = String(
    walletAddress || ""
  ).trim();

  if (!wallet) {
    setError(
      "Seleziona un wallet per il lifecycle audit."
    );
    return;
  }

  setRunningLifecycleAudit(true);
  setError("");
  setMessage("");
  setLifecycleAuditResult(null);
  setExitPriceAuditResult(null);
  setExitabilityRefreshResult(null);

  try {
    const response =
      await runCandidatePositionLifecycleAudit({
        walletAddress: wallet,
        lookbackDays: backtestLookbackDays,
        warmupDays: backtestWarmupDays,
        startingCapitalSol:
          backtestStartingCapital,
        fixedBuySizeSol: backtestBuySize,
        slippageBps: backtestSlippageBps,
        feeBps: backtestFeeBps,
        copyDelaySeconds:
          backtestDelaySeconds,
        maxOpenPositions:
          backtestMaxOpenPositions,
        maxPositionDetails: 200,
      });

    setLifecycleAuditResult(
      response.data
    );
    setCandidateWallet(wallet);

    setMessage(
      `Lifecycle audit completato: ${
        response.data.position_details
          ?.length ?? 0
      } posizioni aperte e ${
        response.data.scenario_results
          ?.length ?? 0
      } scenari cached-only.`
    );
  } catch (requestError) {
    console.error(
      "Errore Position Lifecycle Audit:",
      requestError
    );

    const backendMessage =
      requestError.response?.data?.detail;

    setError(
      typeof backendMessage === "string"
        ? backendMessage
        : "Lifecycle audit non completato. Generation #4 e funzioni LIVE non sono state modificate."
    );
  } finally {
    setRunningLifecycleAudit(false);
  }
}


async function handleExitabilityRefresh(
  walletAddress = candidateWallet
) {
  const wallet = String(walletAddress || "").trim();

  if (!wallet) {
    setError("Seleziona un wallet per il refresh exitability.");
    return;
  }

  if (
    !lifecycleAuditResult
    || lifecycleAuditResult.wallet_address !== wallet
    || !lifecycleAuditResult.run_id
  ) {
    setError(
      "Esegui prima il Position Lifecycle Audit sul wallet selezionato."
    );
    return;
  }

  setRunningExitabilityRefresh(true);
  setError("");
  setMessage("");
  setExitabilityRefreshResult(null);
  setExitPriceAuditResult(null);

  try {
    const response = await refreshCandidateOpenPositionExitability({
      walletAddress: wallet,
      lifecycleRunId: lifecycleAuditResult.run_id,
      cacheTtlHours: backtestJupiterCacheTtlHours,
      maxLocalPriceAgeHours,
      maxTokens: 20,
      forceRefresh: false,
    });

    setExitabilityRefreshResult(response.data);
    setExitPriceAuditResult(response.data.exit_price_audit);
    setCandidateWallet(wallet);
    setMessage(
      `Refresh exitability ${response.data.status}: `
      + `${response.data.summary?.route_found ?? 0} route trovate, `
      + `${response.data.summary?.no_route ?? 0} senza route, `
      + `${response.data.summary?.quote_errors ?? 0} errori quote.`
    );
    await loadDiscoveredWallets();
  } catch (requestError) {
    console.error("Errore Open Position Exitability Refresh:", requestError);
    const backendMessage = requestError.response?.data?.detail;
    setError(
      typeof backendMessage === "string"
        ? backendMessage
        : "Refresh exitability non completato. Nessuna funzione LIVE e stata modificata."
    );
  } finally {
    setRunningExitabilityRefresh(false);
  }
}


async function handleExitPriceAudit(
  walletAddress = candidateWallet
) {
  const wallet = String(walletAddress || "").trim();

  if (!wallet) {
    setError("Seleziona un wallet per l'audit prezzi di uscita.");
    return;
  }

  setRunningExitPriceAudit(true);
  setError("");
  setMessage("");
  setExitPriceAuditResult(null);

  try {
    const boundLifecycleRunId =
      lifecycleAuditResult?.wallet_address === wallet
        ? lifecycleAuditResult.run_id
        : null;

    const response = await runCandidateExitPriceAudit({
      walletAddress: wallet,
      maxLocalPriceAgeHours,
      lifecycleRunId: boundLifecycleRunId,
    });

    setExitPriceAuditResult(response.data);
    setCandidateWallet(wallet);
    setMessage(
      `Exit price audit ${response.data.readiness_status}: ` +
      `score ${formatNumber(response.data.readiness_score)}%, ` +
      `prezzo locale ${formatNumber(response.data.summary?.local_observable_percent)}%, ` +
      `route cached ${formatNumber(response.data.summary?.current_route_supported_percent)}%.`
    );
    await loadDiscoveredWallets();
  } catch (requestError) {
    console.error("Errore Exit Price Provenance Audit:", requestError);
    const backendMessage = requestError.response?.data?.detail;
    setError(
      typeof backendMessage === "string"
        ? backendMessage
        : "Audit prezzi di uscita non completato. Nessuna funzione LIVE e stata modificata."
    );
  } finally {
    setRunningExitPriceAudit(false);
  }
}


  function clearHistory() {
    if (!historyItems.length) return;
    if (window.confirm("Vuoi cancellare la cronologia locale delle discovery?")) {
      setHistoryItems([]);
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700">
        <div className="mx-auto flex max-w-[1500px] flex-col gap-4 p-6 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <h1 className="text-3xl font-bold">Backtest Data Sufficiency & Extended Candidate History</h1>
            <p className="mt-2 max-w-3xl text-slate-400">
              Estende lo storico dei soli candidati copiabili, ricostruisce le posizioni
              precedenti alla finestra e impedisce decisioni definitive con dati insufficienti.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={handleHydration}
              disabled={hydrating}
              className="rounded-lg border border-cyan-700 bg-cyan-950/50 px-4 py-2 text-sm font-semibold text-cyan-300 disabled:opacity-50"
            >
              {hydrating ? "Idratazione..." : `Idrata ${hydrationMaxWallets} wallet`}
            </button>
            <button
              type="button"
              onClick={handleRefreshQuality}
              disabled={refreshingQuality}
              className="rounded-lg border border-purple-700 bg-purple-950/50 px-4 py-2 text-sm font-semibold text-purple-300 disabled:opacity-50"
            >
              {refreshingQuality ? "Analisi qualità..." : "Ricalcola qualità DB"}
            </button>
            <button
              type="button"
              onClick={handleRefreshExitabilityGate}
              disabled={refreshingExitabilityGate}
              className="rounded-lg border border-amber-700 bg-amber-950/50 px-4 py-2 text-sm font-semibold text-amber-300 disabled:opacity-50"
            >
              {refreshingExitabilityGate ? "Gate exitability..." : "Aggiorna exitability gate"}
            </button>
            <button
              type="button"
              onClick={handleRefreshCandidateFunnel}
              disabled={refreshingCandidateFunnel}
              className="rounded-lg border border-cyan-700 bg-cyan-950/50 px-4 py-2 text-sm font-semibold text-cyan-300 disabled:opacity-50"
            >
              {refreshingCandidateFunnel ? "Funnel in corso..." : "Calcola candidate funnel"}
            </button>
            <button
              type="button"
              onClick={handleRefreshActivity}
              disabled={refreshingActivity}
              className="rounded-lg border border-emerald-700 bg-emerald-950/50 px-4 py-2 text-sm font-semibold text-emerald-300 disabled:opacity-50"
            >
              {refreshingActivity ? "Ricalcolo..." : "Ricalcola attività DB"}
            </button>
            <button
              type="button"
              onClick={loadDiscoveredWallets}
              disabled={loadingWallets}
              className="rounded-lg border border-blue-700 bg-blue-950/50 px-4 py-2 text-sm font-semibold text-blue-300 disabled:opacity-50"
            >
              {loadingWallets ? "Aggiornamento..." : "Aggiorna elenco"}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] p-4 sm:p-8">
        <div className="mb-6 rounded-xl border border-amber-800 bg-amber-950/30 p-4 text-sm text-amber-200">
          Il backfill storico è manuale e limitato dal budget Helius. Il backtest usa poi
          soltanto trade salvati e quote Jupiter SOL→token→SOL di sola lettura. Nessuna
          funzione firma transazioni, abilita LIVE o stream, avvia worker, applica wallet
          oppure crea o resetta generazioni.
        </div>

        {error && (
          <div className="mb-6 rounded-lg border border-red-700 bg-red-950/40 p-4 text-red-300">
            {error}
          </div>
        )}
        {message && (
          <div className="mb-6 rounded-lg border border-green-700 bg-green-950/40 p-4 text-green-300">
            {message}
          </div>
        )}

        <section className="mb-6 rounded-xl border border-cyan-900 bg-cyan-950/20 p-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <h2 className="text-lg font-bold text-cyan-200">Discovery Candidate Funnel + Budgeted History Queue</h2>
              <p className="mt-2 max-w-4xl text-sm text-cyan-100/80">
                Pre-screen locale di tutti i wallet. Il budget crea soltanto una coda consigliata:
                non avvia backfill e non effettua richieste Helius.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="text-xs text-slate-400">
                Budget richieste storico
                <input
                  type="number"
                  min="0"
                  max="50"
                  value={funnelHistoryBudget}
                  onChange={(event) => setFunnelHistoryBudget(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-white"
                />
              </label>
              <label className="text-xs text-slate-400">
                Wallet massimi in coda
                <input
                  type="number"
                  min="1"
                  max="20"
                  value={funnelMaxHistoryWallets}
                  onChange={(event) => setFunnelMaxHistoryWallets(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-white"
                />
              </label>
              <label className="text-xs text-slate-400">
                Storico obiettivo (giorni)
                <input
                  type="number"
                  min="7"
                  max="90"
                  value={funnelTargetHistoryDays}
                  onChange={(event) => setFunnelTargetHistoryDays(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-white"
                />
              </label>
            </div>
          </div>
        </section>

        {candidateFunnelResult && (
          <section className="mb-6 overflow-hidden rounded-xl border border-cyan-800 bg-slate-800">
            <div className="border-b border-slate-700 p-5">
              <h2 className="text-lg font-bold text-cyan-200">Candidate Funnel Result</h2>
              <p className="mt-2 text-sm text-slate-300">
                Valutati {candidateFunnelResult.summary?.wallets_evaluated ?? 0} wallet ·
                {" "}{candidateFunnelResult.summary?.wallets_ready ?? 0} READY ·
                {" "}{candidateFunnelResult.summary?.wallets_review ?? 0} REVIEW ·
                {" "}{candidateFunnelResult.summary?.wallets_blocked ?? 0} BLOCKED ·
                {" "}{candidateFunnelResult.summary?.wallets_needs_local_data ?? 0} NEEDS LOCAL DATA ·
                {" "}{candidateFunnelResult.summary?.wallets_needs_history ?? 0} NEEDS HISTORY.
              </p>
            </div>
            <div className="p-5">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <StatCard label="Wallet in coda" value={candidateFunnelResult.summary?.history_queue_wallets ?? 0} tone="text-cyan-300" />
                <StatCard label="Budget richiesto" value={candidateFunnelResult.summary?.history_budget_requested ?? 0} tone="text-blue-300" />
                <StatCard label="Budget allocato" value={candidateFunnelResult.summary?.history_budget_allocated ?? 0} tone="text-green-300" />
                <StatCard label="Budget residuo" value={candidateFunnelResult.summary?.history_budget_unallocated ?? 0} tone="text-amber-300" />
              </div>
              <div className="mt-5 overflow-x-auto">
                <table className="w-full min-w-[900px] text-sm">
                  <thead className="bg-slate-900 text-slate-400">
                    <tr>
                      <th className="p-3">Priorità</th>
                      <th className="p-3 text-left">Wallet</th>
                      <th className="p-3">Funnel score</th>
                      <th className="p-3">Storico attuale</th>
                      <th className="p-3">Richieste consigliate</th>
                      <th className="p-3">Budget allocato</th>
                      <th className="p-3 text-left">Azione</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700">
                    {(candidateFunnelResult.history_queue ?? []).map((row) => (
                      <tr key={row.wallet_address}>
                        <td className="p-3 text-center font-bold text-cyan-300">#{row.priority}</td>
                        <td className="p-3 font-mono text-xs text-blue-300">{shortenAddress(row.wallet_address, 12, 10)}</td>
                        <td className="p-3 text-center">{formatNumber(row.funnel_score)}%</td>
                        <td className="p-3 text-center">{formatNumber(row.current_history_span_days, 1)} g</td>
                        <td className="p-3 text-center">{row.recommended_requests}</td>
                        <td className="p-3 text-center font-bold text-green-300">{row.allocated_requests}</td>
                        <td className="p-3 text-left">
                          <button
                            type="button"
                            onClick={() =>
                              handleSelectFunnelWallet(row)
                            }
                            className="rounded-lg border border-cyan-700 bg-cyan-950/50 px-3 py-2 text-xs font-bold text-cyan-300"
                          >
                            {candidateWallet ===
                            row.wallet_address
                              ? "Selezionato"
                              : "Seleziona"}
                          </button>
                        </td>
                      </tr>
                    ))}
                    {!(candidateFunnelResult.history_queue ?? []).length && (
                      <tr>
                        <td colSpan="7" className="p-6 text-center text-slate-500">
                          Nessun wallet promettente richiede storico aggiuntivo con i dati attuali.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        )}

        {exitabilityGateResult && (
          <section className="mb-6 rounded-xl border border-amber-800 bg-amber-950/30 p-4">
            <h2 className="text-lg font-bold text-amber-200">Batch Exitability Safety Gate</h2>
            <p className="mt-2 text-sm text-amber-100">
              Valutati {exitabilityGateResult.summary?.wallets_evaluated ?? 0} wallet:
              {" "}{exitabilityGateResult.summary?.wallets_ready ?? 0} READY,
              {" "}{exitabilityGateResult.summary?.wallets_review ?? 0} REVIEW,
              {" "}{exitabilityGateResult.summary?.wallets_blocked ?? 0} BLOCKED.
            </p>
          </section>
        )}

        <section className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-7">
          <StatCard label="Wallet scoperti" value={summary.total} tone="text-blue-300" />
          <StatCard label="Idonei finali" value={summary.eligible} tone="text-green-300" />
          <StatCard label="Promossi" value={summary.promoted} tone="text-emerald-300" />
          <StatCard label="Gate osservazione" value={summary.promotionObservation} tone="text-amber-300" />
          <StatCard label="Dati insufficienti" value={summary.insufficient} tone="text-orange-300" />
          <StatCard label="Bocciati" value={summary.rejected} tone="text-red-300" />
          <StatCard label="Gate non analizzati" value={summary.promotionNotAnalyzed} tone="text-blue-300" />
        </section>


        <section
          id="candidate-analysis"
          className="mb-8 scroll-mt-6 overflow-hidden rounded-xl border border-emerald-900 bg-slate-800"
        >
          <div className="border-b border-slate-700 p-5">
            <h2 className="text-xl font-bold text-emerald-300">
              Backtest Data Sufficiency & Extended Candidate History
            </h2>
            <p className="mt-1 text-sm text-slate-400">
              Prima estende lo storico con paginazione controllata; poi usa una finestra di
              warmup per ricostruire le posizioni già aperte e valuta se il campione è sufficiente.
            </p>
          </div>
          <div className="p-5">
            <label className="block text-sm text-slate-400">
              Wallet scoperto da analizzare
              <select
                value={candidateWallet}
                onChange={(event) =>
                  handleCandidateWalletSelection(
                    event.target.value
                  )
                }
                className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3 font-mono text-xs"
              >
                <option value="">
                  Seleziona esplicitamente un wallet
                </option>
                {discoveredWallets
                  .map((wallet) => (
                    <option key={wallet.wallet_address} value={wallet.wallet_address}>
                      {shortenAddress(wallet.wallet_address, 12, 10)} · Q {formatNumber(wallet.quality_score)} · {wallet.promotion_status}
                    </option>
                  ))}
              </select>

              {candidateWallet ? (
                <div className="mt-3 rounded-lg border border-blue-800 bg-blue-950/30 p-3">
                  <p className="text-xs text-blue-300">
                    Wallet selezionato:
                  </p>
                  <p className="mt-1 break-all font-mono text-sm text-white">
                    {candidateWallet}
                  </p>
                  <p className="mt-2 text-xs text-slate-400">
                    Qualit? attuale:{" "}
                    <strong>
                      {selectedCandidate
                        ?.quality_classification ??
                        "NON DISPONIBILE"}
                    </strong>
                  </p>
                </div>
              ) : (
                <p className="mt-3 text-xs font-semibold text-amber-300">
                  Nessun wallet selezionato. Le azioni restano disabilitate.
                </p>
              )}

              <span className="mt-2 block text-xs text-slate-500">
                L'audit e disponibile per ogni wallet scoperto. Storico esteso e
                Promotion Gate richiedono qualita COPIABILE o OSSERVAZIONE.
              </span>
            </label>

            <div className="mt-5 rounded-xl border border-cyan-900 bg-cyan-950/20 p-4">
              <h3 className="font-bold text-cyan-300">1. Estendi storico candidato</h3>
              <p className="mt-1 text-xs text-slate-400">
                Una richiesta Helius per pagina, zero retry automatici. Il budget massimo resta rigido.
              </p>
              <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <label className="text-sm text-slate-400">
                  Storico giorni
                  <input
                    type="number" min="7" max="90" value={historyLookbackDays}
                    onChange={(event) => setHistoryLookbackDays(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Budget richieste Helius
                  <input
                    type="number" min="1" max="20" value={historyRequestBudget}
                    onChange={(event) => setHistoryRequestBudget(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Transazioni per pagina
                  <input
                    type="number" min="10" max="100" value={historyPageSize}
                    onChange={(event) => setHistoryPageSize(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => handleExtendedHistoryBackfill()}
                  disabled={runningBackfill || !candidateWallet || !["COPIABILE", "OSSERVAZIONE"].includes(discoveredWallets.find((wallet) => wallet.wallet_address === candidateWallet)?.quality_classification)}
                  className="self-end rounded-lg bg-cyan-600 px-5 py-3 font-bold text-white disabled:opacity-50"
                >
                  {runningBackfill ? "Backfill in corso..." : "Estendi storico"}
                </button>
              </div>

              {extendedHistoryResult && (
                <div className="mt-4 grid gap-3 rounded-lg border border-slate-700 bg-slate-900/70 p-4 text-sm sm:grid-cols-2 xl:grid-cols-9">
                  <span>Stato: <strong className="text-cyan-300">{extendedHistoryResult.status}</strong></span>
                  <span>Stop: <strong>{extendedHistoryResult.stop_reason}</strong></span>
                  <span>Modalità: <strong>{extendedHistoryResult.parameters?.resumed ? "RIPRESA" : "NUOVA"}</strong></span>
                  <span>Cursore iniziale: <strong>{extendedHistoryResult.parameters?.resume_from_signature ? shortenAddress(extendedHistoryResult.parameters.resume_from_signature, 8, 6) : "-"}</strong></span>
                  <span>Helius: <strong>{extendedHistoryResult.helius_requests}/{extendedHistoryResult.request_budget}</strong></span>
                  <span>Pagine: <strong>{extendedHistoryResult.pages_fetched}</strong></span>
                  <span>Swap: <strong>{extendedHistoryResult.swaps_found}</strong></span>
                  <span>Importati: <strong>{extendedHistoryResult.trades_imported}</strong></span>
                  <span>Aggiornati: <strong>{extendedHistoryResult.trades_updated}</strong></span>
                </div>
              )}
            </div>

            <div className="mt-5 rounded-xl border border-emerald-900 bg-emerald-950/10 p-4">
              <h3 className="font-bold text-emerald-300">2. Esegui backtest con sufficienza dati</h3>
              <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <label className="text-sm text-slate-400">
                  Capitale iniziale (SOL)
                  <input
                    type="number" min="0.05" step="0.05" value={backtestStartingCapital}
                    onChange={(event) => setBacktestStartingCapital(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Size BUY (SOL)
                  <input
                    type="number" min="0.001" step="0.01" value={backtestBuySize}
                    onChange={(event) => setBacktestBuySize(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Finestra analisi (giorni)
                  <input
                    type="number" min="1" max="90" value={backtestLookbackDays}
                    onChange={(event) => setBacktestLookbackDays(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Warmup posizioni (giorni)
                  <input
                    type="number" min="0" max="60" value={backtestWarmupDays}
                    onChange={(event) => setBacktestWarmupDays(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Slippage (bps)
                  <input
                    type="number" min="0" max="1000" value={backtestSlippageBps}
                    onChange={(event) => setBacktestSlippageBps(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Commissioni (bps)
                  <input
                    type="number" min="0" max="500" value={backtestFeeBps}
                    onChange={(event) => setBacktestFeeBps(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Ritardo copy (secondi)
                  <input
                    type="number" min="0" max="3600" value={backtestDelaySeconds}
                    onChange={(event) => setBacktestDelaySeconds(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                  />
                </label>

<label className="text-sm text-slate-400">
  Massimo posizioni aperte
  <input
    type="number"
    min="1"
    max="50"
    value={backtestMaxOpenPositions}
    onChange={(event) =>
      setBacktestMaxOpenPositions(
        Number(event.target.value)
      )
    }
    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
  />
</label>
                <label className="text-sm text-slate-400">
                  Freschezza prezzo locale (ore)
                  <input
                    type="number"
                    min="1"
                    max="720"
                    value={maxLocalPriceAgeHours}
                    onChange={(event) => setMaxLocalPriceAgeHours(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                  />
                </label>
                <label className="flex items-center gap-3 self-end rounded-lg border border-slate-600 bg-slate-950 px-4 py-3 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={backtestCheckJupiter}
                    onChange={(event) => setBacktestCheckJupiter(event.target.checked)}
                  />
                  Verifica Jupiter round-trip
                </label>
                <label className="text-sm text-slate-400">
                  Cache Jupiter (ore)
                  <input
                    type="number" min="1" max="24" value={backtestJupiterCacheTtlHours}
                    onChange={(event) => setBacktestJupiterCacheTtlHours(Number(event.target.value))}
                    disabled={!backtestCheckJupiter}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3 disabled:opacity-50"
                  />
                </label>
                <label className="flex items-center gap-3 self-end rounded-lg border border-slate-600 bg-slate-950 px-4 py-3 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={backtestForceJupiterRefresh}
                    onChange={(event) => setBacktestForceJupiterRefresh(event.target.checked)}
                    disabled={!backtestCheckJupiter}
                  />
                  Ignora cache Jupiter
                </label>
              </div>

<div className="mt-5 flex flex-wrap gap-3">
  <button
    type="button"
    onClick={() => handlePromotionBacktest()}
    disabled={runningBacktest || !candidateWallet || !["COPIABILE", "OSSERVAZIONE"].includes(discoveredWallets.find((wallet) => wallet.wallet_address === candidateWallet)?.quality_classification)}
    className="rounded-lg bg-emerald-600 px-5 py-3 font-bold text-white disabled:opacity-50"
  >
    {runningBacktest
      ? "Backtest in corso..."
      : "Esegui backtest e gate"}
  </button>

  <button
    type="button"
    onClick={() => handleReconstructionAudit()}
    disabled={
      runningReconstructionAudit
      || !candidateWallet
    }
    className="rounded-lg bg-indigo-600 px-5 py-3 font-bold text-white disabled:opacity-50"
  >
    {runningReconstructionAudit
      ? "Audit in corso..."
      : "Audit ricostruzione + sensibilita"}
  </button>

  <button
    type="button"
    onClick={() => handleLifecycleAudit()}
    disabled={
      runningLifecycleAudit
      || !candidateWallet
    }
    className="rounded-lg bg-teal-600 px-5 py-3 font-bold text-white disabled:opacity-50"
  >
    {runningLifecycleAudit
      ? "Lifecycle audit in corso..."
      : "Position lifecycle + stale audit"}
  </button>

  <button
    type="button"
    onClick={() => handleExitabilityRefresh()}
    disabled={
      runningExitabilityRefresh
      || !candidateWallet
      || lifecycleAuditResult?.wallet_address !== candidateWallet
      || !lifecycleAuditResult?.run_id
    }
    className="rounded-lg bg-violet-600 px-5 py-3 font-bold text-white disabled:opacity-50"
  >
    {runningExitabilityRefresh
      ? "Refresh Jupiter in corso..."
      : "Refresh Jupiter posizioni aperte"}
  </button>

  <button
    type="button"
    onClick={() => handleExitPriceAudit()}
    disabled={runningExitPriceAudit || !candidateWallet}
    className="rounded-lg bg-rose-600 px-5 py-3 font-bold text-white disabled:opacity-50"
  >
    {runningExitPriceAudit
      ? "Exit price audit in corso..."
      : "Exit price provenance + cached coverage"}
  </button>
</div>
            </div>

            {promotionResult && (
              <div className="mt-6 rounded-xl border border-slate-700 bg-slate-900/70 p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-mono text-xs text-slate-400">{promotionResult.wallet_address}</p>
                    <h3 className="mt-1 text-2xl font-bold text-emerald-300">
                      {promotionResult.decision} · score {formatNumber(promotionResult.score)}
                    </h3>
                  </div>
                  <span className={`rounded-full border px-3 py-1 text-sm font-bold ${promotionBadge(promotionResult.decision).className}`}>
                    {promotionResult.decision}
                  </span>
                </div>
                <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-8">
                  <StatCard label="Sufficienza" value={`${formatNumber(promotionResult.data_sufficiency_score)}%`} tone={promotionResult.data_sufficient ? "text-green-300" : "text-orange-300"} subtitle={promotionResult.data_sufficient ? "SUFFICIENTE" : "INSUFFICIENTE"} />
                  <StatCard label="Storico" value={`${formatNumber(promotionResult.history_span_days, 1)} g`} tone="text-cyan-300" />
                  <StatCard label="Rendimento" value={`${formatNumber(promotionResult.total_return_percent)}%`} tone="text-cyan-300" />
                  <StatCard label="PnL netto" value={`${formatNumber(promotionResult.net_pnl_sol, 4)} SOL`} tone="text-green-300" />
                  <StatCard label="Win rate" value={`${formatNumber(promotionResult.win_rate_percent)}%`} tone="text-blue-300" />
                  <StatCard label="Profit factor" value={promotionResult.profit_factor == null ? "-" : formatNumber(promotionResult.profit_factor)} tone="text-purple-300" />
                  <StatCard label="Max drawdown" value={`${formatNumber(promotionResult.max_drawdown_percent)}%`} tone="text-amber-300" />
                  <StatCard label="Jupiter" value={`${formatNumber(promotionResult.jupiter_compatibility_percent)}%`} tone="text-fuchsia-300" subtitle={promotionResult.jupiter_status} />
                </div>
                <p className="mt-4 text-sm text-slate-400">
                  Analisi: <strong>{promotionResult.analysis_source_trades}</strong> trade · warmup: <strong>{promotionResult.warmup_source_trades}</strong> · bootstrap: <strong>{promotionResult.bootstrap_positions}</strong> ({promotionResult.bootstrap_positions_closed} chiuse) · posizioni chiuse: <strong>{promotionResult.completed_positions}</strong> · aperte: <strong>{promotionResult.open_positions}</strong>.
                </p>
                <p className="mt-2 text-sm text-slate-400">
                  Copertura: <strong>{formatNumber(promotionResult.execution_coverage_percent)}%</strong> · SELL abbinate: <strong>{formatNumber(promotionResult.matched_sell_ratio_percent)}%</strong> · posizioni aperte: <strong>{formatNumber(promotionResult.open_position_ratio_percent)}%</strong> · richieste Jupiter: <strong>{promotionResult.jupiter_requests}</strong> · cache: <strong>{promotionResult.jupiter_cache_hits ?? 0}</strong> · controlli live: <strong>{promotionResult.jupiter_live_checks ?? 0}</strong>.
                </p>
                {(promotionResult.data_sufficiency_reasons ?? []).length > 0 && (
                  <p className="mt-3 text-xs text-orange-300">
                    Dati insufficienti: {(promotionResult.data_sufficiency_reasons ?? []).join(", ")}
                  </p>
                )}
                {(promotionResult.reasons ?? []).length > 0 && (
                  <p className="mt-3 text-xs text-amber-300">
                    Motivi gate: {(promotionResult.reasons ?? []).join(", ")}
                  </p>
                )}
              </div>
            )}
          </div>
        </section>


{reconstructionAuditResult && (
  <section className="mb-8 overflow-hidden rounded-xl border border-indigo-800 bg-slate-800">
    <div className="border-b border-slate-700 p-5">
      <p className="font-mono text-xs text-slate-400">
        {reconstructionAuditResult.wallet_address}
      </p>
      <h2 className="mt-1 text-xl font-bold text-indigo-300">
        Trade Reconstruction Audit
      </h2>
      <p className="mt-2 text-xs text-amber-300">
        Diagnosi: {(
          reconstructionAuditResult.diagnoses ?? []
        ).join(", ")}
      </p>
    </div>

    <div className="p-5">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        <StatCard
          label="Return proporzionale"
          value={`${formatNumber(
            reconstructionAuditResult
              .baseline_metrics
              ?.total_return_percent
          )}%`}
          tone="text-green-300"
        />

        <StatCard
          label="Return senza best"
          value={`${formatNumber(
            reconstructionAuditResult
              .baseline_metrics
              ?.return_without_best_trade_percent
          )}%`}
          tone="text-amber-300"
        />

        <StatCard
          label="Copertura grezza"
          value={`${formatNumber(
            reconstructionAuditResult
              .baseline_metrics
              ?.raw_execution_coverage_percent
          )}%`}
          tone="text-cyan-300"
        />

        <StatCard
          label="Copertura risorse"
          value={`${formatNumber(
            reconstructionAuditResult
              .baseline_metrics
              ?.resource_constrained_coverage_percent
          )}%`}
          tone="text-blue-300"
        />

        <StatCard
          label="SELL parziali"
          value={
            reconstructionAuditResult
              .baseline_metrics
              ?.partial_sell_events ?? 0
          }
          tone="text-purple-300"
        />

        <StatCard
          label="Concentrazione best"
          value={`${formatNumber(
            reconstructionAuditResult
              .baseline_metrics
              ?.top_1_profit_concentration_percent
          )}%`}
          tone="text-fuchsia-300"
        />
      </div>

      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[1200px] text-xs">
          <thead className="bg-slate-950 text-slate-400">
            <tr>
              <th className="p-3">Capitale</th>
              <th className="p-3">Max pos.</th>
              <th className="p-3">Return</th>
              <th className="p-3">Senza best</th>
              <th className="p-3">PnL</th>
              <th className="p-3">Chiuse</th>
              <th className="p-3">Aperte</th>
              <th className="p-3">Cov. grezza</th>
              <th className="p-3">Cov. risorse</th>
              <th className="p-3">SELL abbinate</th>
              <th className="p-3">PF</th>
              <th className="p-3">DD</th>
              <th className="p-3">? bootstrap</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-800">
            {(
              reconstructionAuditResult
                .scenario_results ?? []
            ).map((scenario) => {
              const row =
                scenario.with_bootstrap ?? {};

              return (
                <tr key={scenario.scenario_key}>
                  <td className="p-3 text-center">
                    {scenario.starting_capital_sol} SOL
                  </td>
                  <td className="p-3 text-center">
                    {scenario.max_open_positions}
                  </td>
                  <td className="p-3 text-center text-green-300">
                    {formatNumber(
                      row.total_return_percent
                    )}%
                  </td>
                  <td className="p-3 text-center text-amber-300">
                    {formatNumber(
                      row.return_without_best_trade_percent
                    )}%
                  </td>
                  <td className="p-3 text-center">
                    {formatNumber(
                      row.net_pnl_sol,
                      4
                    )} SOL
                  </td>
                  <td className="p-3 text-center">
                    {row.completed_positions}
                  </td>
                  <td className="p-3 text-center">
                    {row.open_positions}
                  </td>
                  <td className="p-3 text-center">
                    {formatNumber(
                      row.raw_execution_coverage_percent
                    )}%
                  </td>
                  <td className="p-3 text-center text-blue-300">
                    {formatNumber(
                      row.resource_constrained_coverage_percent
                    )}%
                  </td>
                  <td className="p-3 text-center">
                    {formatNumber(
                      row.matched_sell_ratio_percent
                    )}%
                  </td>
                  <td className="p-3 text-center">
                    {row.profit_factor == null
                      ? "-"
                      : formatNumber(
                          row.profit_factor
                        )}
                  </td>
                  <td className="p-3 text-center">
                    {formatNumber(
                      row.max_drawdown_percent
                    )}%
                  </td>
                  <td className="p-3 text-center">
                    {formatNumber(
                      scenario.bootstrap_delta
                        ?.return_percent
                    )}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-2">
        <div className="rounded-lg border border-slate-700 bg-slate-950/60 p-4">
          <h3 className="font-bold text-orange-300">
            Motivi esclusione
          </h3>

          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(
              reconstructionAuditResult
                .exclusion_summary ?? {}
            ).map(([reason, count]) => (
              <span
                key={reason}
                className="rounded-full border border-slate-700 px-2.5 py-1 text-xs text-slate-300"
              >
                {reason}: {count}
              </span>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-slate-700 bg-slate-950/60 p-4">
          <h3 className="font-bold text-indigo-300">
            Prime esclusioni
          </h3>

          <div className="mt-3 max-h-72 space-y-2 overflow-y-auto">
            {(
              reconstructionAuditResult
                .excluded_trades ?? []
            )
              .slice(0, 50)
              .map((item, index) => (
                <div
                  key={`${item.signature}-${index}`}
                  className="rounded border border-slate-800 p-2 text-[11px] text-slate-400"
                >
                  <strong className="text-orange-300">
                    {item.reason}
                  </strong>
                  {" ? "}
                  {shortenAddress(
                    item.token_mint,
                    6,
                    5
                  )}
                  {" ? "}
                  {item.side}
                  {" ? "}
                  {item.signature
                    ? shortenAddress(
                        item.signature,
                        8,
                        6
                      )
                    : "-"}
                </div>
              ))}
          </div>
        </div>
      </div>
    </div>
  </section>
)}

        <LifecycleAuditPanel result={lifecycleAuditResult} />
        <ExitabilityRefreshPanel result={exitabilityRefreshResult} />
        <ExitPriceAuditPanel result={exitPriceAuditResult} />

        <section className="mb-8 overflow-hidden rounded-xl border border-cyan-900 bg-slate-800">
          <div className="border-b border-slate-700 p-5">
            <h2 className="text-xl font-bold text-cyan-300">Discovery Hydration controllata</h2>
            <p className="mt-1 text-sm text-slate-400">
              Recupera gli swap recenti dei wallet con Smart Score più alto, li salva con
              data reale, elimina i duplicati e aggiorna ranking e idoneità.
            </p>
          </div>
          <div className="p-5">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              <label className="text-sm text-slate-400">
                Wallet massimi
                <input
                  type="number" min="1" max="10" value={hydrationMaxWallets}
                  onChange={(event) => setHydrationMaxWallets(Number(event.target.value))}
                  className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                />
              </label>
              <label className="text-sm text-slate-400">
                Budget richieste Helius
                <input
                  type="number" min="1" max="10" value={hydrationRequestBudget}
                  onChange={(event) => setHydrationRequestBudget(Number(event.target.value))}
                  className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                />
              </label>
              <label className="text-sm text-slate-400">
                Storico giorni
                <input
                  type="number" min="1" max="14" value={hydrationLookbackDays}
                  onChange={(event) => setHydrationLookbackDays(Number(event.target.value))}
                  className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                />
              </label>
              <label className="text-sm text-slate-400">
                Transazioni per wallet
                <input
                  type="number" min="1" max="100" value={hydrationTransactionLimit}
                  onChange={(event) => setHydrationTransactionLimit(Number(event.target.value))}
                  className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                />
              </label>
              <label className="text-sm text-slate-400">
                Smart Score minimo
                <input
                  type="number" min="0" max="100" value={hydrationMinimumScore}
                  onChange={(event) => setHydrationMinimumScore(Number(event.target.value))}
                  className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
                />
              </label>
            </div>
            <button
              type="button"
              onClick={handleHydration}
              disabled={hydrating}
              className="mt-5 rounded-lg bg-cyan-600 px-5 py-3 font-bold text-white disabled:opacity-50"
            >
              {hydrating ? "Idratazione in corso..." : "Avvia idratazione controllata"}
            </button>

            {hydrationResult && (
              <div className="mt-5 grid gap-3 rounded-lg border border-slate-700 bg-slate-900/70 p-4 text-sm sm:grid-cols-2 xl:grid-cols-6">
                <span>Stato: <strong className="text-cyan-300">{hydrationResult.status}</strong></span>
                <span>Wallet: <strong>{hydrationResult.wallets_attempted}</strong></span>
                <span>Helius: <strong>{hydrationResult.helius_requests}/{hydrationResult.request_budget}</strong></span>
                <span>Swap: <strong>{hydrationResult.swaps_found}</strong></span>
                <span>Importati: <strong>{hydrationResult.trades_imported}</strong></span>
                <span>Errori: <strong>{hydrationResult.wallets_failed}</strong></span>
              </div>
            )}
          </div>
        </section>

        <section className="mb-8 overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="border-b border-slate-700 p-5">
            <h2 className="text-xl font-bold">Nuova discovery</h2>
            <p className="mt-1 text-sm text-slate-400">
              Ogni wallet importato viene sincronizzato, profilato, classificato e salvato nel ranking attività.
            </p>
          </div>
          <div className="p-5">
            <div className="mb-5 grid grid-cols-2 gap-3">
              {[
                ["FULL", "Full Discovery"],
                ["SMART", "Smart Discovery"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setMode(value)}
                  className={`rounded-lg border px-4 py-3 font-semibold ${
                    mode === value
                      ? value === "SMART"
                        ? "border-purple-600 bg-purple-600"
                        : "border-blue-600 bg-blue-600"
                      : "border-slate-600 bg-slate-900 text-slate-300"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            <input
              type="text"
              value={seedWallet}
              onChange={(event) => setSeedWallet(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !running) handleRunDiscovery();
              }}
              placeholder="Seed wallet address..."
              className="mb-5 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3 font-mono outline-none focus:border-blue-500"
            />

            {mode === "FULL" ? (
              <div className="mb-5 grid gap-4 sm:grid-cols-2">
                <label className="text-sm text-slate-400">
                  Max token
                  <input
                    type="number"
                    min="1"
                    max="5"
                    value={maxTokens}
                    onChange={(event) => setMaxTokens(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3 text-white"
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Wallet per token
                  <input
                    type="number"
                    min="1"
                    max="5"
                    value={maxWalletsPerToken}
                    onChange={(event) => setMaxWalletsPerToken(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3 text-white"
                  />
                </label>
              </div>
            ) : (
              <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <label className="text-sm text-slate-400">
                  Profondità
                  <input
                    type="number"
                    min="1"
                    max="3"
                    value={maxDepth}
                    onChange={(event) => setMaxDepth(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3 text-white"
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Token per wallet
                  <input
                    type="number"
                    min="1"
                    max="10"
                    value={maxTokensPerWallet}
                    onChange={(event) => setMaxTokensPerWallet(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3 text-white"
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Wallet per token
                  <input
                    type="number"
                    min="1"
                    max="10"
                    value={smartMaxWalletsPerToken}
                    onChange={(event) => setSmartMaxWalletsPerToken(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3 text-white"
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Smart Score minimo
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={minSmartScore}
                    onChange={(event) => setMinSmartScore(Number(event.target.value))}
                    className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3 text-white"
                  />
                </label>
              </div>
            )}

            <button
              type="button"
              onClick={handleRunDiscovery}
              disabled={running}
              className={`w-full rounded-lg px-6 py-3 font-semibold disabled:opacity-50 ${
                mode === "SMART"
                  ? "bg-purple-600 hover:bg-purple-700"
                  : "bg-blue-600 hover:bg-blue-700"
              }`}
            >
              {running ? "Discovery in esecuzione..." : `Avvia ${mode === "SMART" ? "Smart" : "Full"} Discovery`}
            </button>
          </div>
        </section>

        {result && (
          <section className="mb-8 overflow-hidden rounded-xl border border-green-800 bg-slate-800">
            <div className="border-b border-slate-700 p-5">
              <h2 className="text-xl font-bold">Ultimo risultato</h2>
              <p className="mt-1 break-all font-mono text-sm text-slate-400">
                {result.seed_wallet ?? seedWallet}
              </p>
            </div>
            <div className="grid gap-4 p-5 sm:grid-cols-2 xl:grid-cols-5">
              <StatCard label="Stato" value={result.status ?? "COMPLETED"} />
              <StatCard label="Analizzati" value={result.wallets_analyzed ?? 0} tone="text-blue-300" />
              <StatCard label="Idonei" value={result.wallets_eligible ?? 0} tone="text-green-300" />
              <StatCard label="Falliti" value={result.wallets_failed ?? 0} tone="text-red-300" />
              <StatCard label="Token processati" value={result.tokens_processed ?? "-"} tone="text-purple-300" />
            </div>
            {resultRanking.length > 0 && (
              <div className="overflow-x-auto border-t border-slate-700">
                <table className="w-full min-w-[1150px] text-sm">
                  <thead className="bg-slate-900 text-slate-400">
                    <tr>
                      <th className="p-4 text-left">Wallet</th>
                      <th className="p-4">Ranking</th>
                      <th className="p-4">Smart</th>
                      <th className="p-4">Attività</th>
                      <th className="p-4">Qualità</th>
                      <th className="p-4">Swap 24h / 7d</th>
                      <th className="p-4">BUY / SELL 7d</th>
                      <th className="p-4">Ultimo swap</th>
                      <th className="p-4">Idoneità</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700">
                    {resultRanking.slice(0, 15).map((wallet, index) => {
                      const address = getResultWalletAddress(wallet);
                      const activity = activityBadge(wallet.activity_classification);
                      const quality = qualityBadge(wallet.quality_classification);
                      const eligibility = eligibilityBadge(wallet);
                      return (
                        <tr key={address || index}>
                          <td className="p-4 font-mono text-xs">
                            {address ? (
                              <Link to={`/wallet/${address}`} className="text-blue-400 hover:underline">
                                {shortenAddress(address)}
                              </Link>
                            ) : "-"}
                          </td>
                          <td className="p-4 text-center font-bold text-cyan-300">{formatNumber(wallet.ranking_score)}</td>
                          <td className="p-4 text-center font-bold text-blue-300">{formatNumber(wallet.smart_score)}</td>
                          <td className="p-4 text-center">
                            <span className={`rounded-full border px-2.5 py-1 text-xs font-bold ${activity.className}`}>{activity.label}</span>
                          </td>
                          <td className="p-4 text-center">
                            <span className={`rounded-full border px-2.5 py-1 text-xs font-bold ${quality.className}`}>
                              {quality.label}
                            </span>
                          </td>
                          <td className="p-4 text-center text-slate-300">{wallet.swaps_24h ?? 0} / {wallet.swaps_7d ?? 0}</td>
                          <td className="p-4 text-center text-slate-300">{wallet.buys_7d ?? 0} / {wallet.sells_7d ?? 0}</td>
                          <td className="p-4 text-center text-xs text-slate-400">{formatDate(wallet.last_swap_at)}</td>
                          <td className="p-4 text-center">
                            <span className={`rounded-full border px-2.5 py-1 text-xs font-bold ${eligibility.className}`}>{eligibility.label}</span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        <section className="mb-8 overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="border-b border-slate-700 p-5">
            <h2 className="text-xl font-bold">Ranking wallet scoperti</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-8">
              <input
                type="text"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Wallet, token o classe..."
                className="rounded-lg border border-slate-600 bg-slate-950 px-4 py-3 xl:col-span-2"
              />
              <input
                type="number"
                min="0"
                max="100"
                value={minimumScore}
                onChange={(event) => setMinimumScore(Number(event.target.value))}
                placeholder="Smart Score minimo"
                className="rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
              />
              <select
                value={activityFilter}
                onChange={(event) => setActivityFilter(event.target.value)}
                className="rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
              >
                {ACTIVITY_OPTIONS.map((option) => (
                  <option key={option} value={option}>{option.replace("_", " ")}</option>
                ))}
              </select>
              <select
                value={qualityFilter}
                onChange={(event) => setQualityFilter(event.target.value)}
                className="rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
              >
                {QUALITY_OPTIONS.map((option) => (
                  <option key={option} value={option}>{option.replace("_", " ")}</option>
                ))}
              </select>
              <select
                value={promotionFilter}
                onChange={(event) => setPromotionFilter(event.target.value)}
                className="rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
              >
                {PROMOTION_OPTIONS.map((option) => (
                  <option key={option} value={option}>{option.replace("_", " ")}</option>
                ))}
              </select>
              <select
                value={exitPriceFilter}
                onChange={(event) => setExitPriceFilter(event.target.value)}
                className="rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
              >
                {EXIT_PRICE_OPTIONS.map((option) => (
                  <option key={option} value={option}>{option.replace("_", " ")}</option>
                ))}
              </select>
              <select
                value={exitabilityGateFilter}
                onChange={(event) => setExitabilityGateFilter(event.target.value)}
                className="rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
              >
                {EXITABILITY_GATE_OPTIONS.map((option) => (
                  <option key={option} value={option}>{option.replace("_", " ")}</option>
                ))}
              </select>
              <select
                value={discoveryFunnelFilter}
                onChange={(event) => setDiscoveryFunnelFilter(event.target.value)}
                className="rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
              >
                {DISCOVERY_FUNNEL_OPTIONS.map((option) => (
                  <option key={option} value={option}>{option.replaceAll("_", " ")}</option>
                ))}
              </select>
              <select
                value={sortBy}
                onChange={(event) => setSortBy(event.target.value)}
                className="rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
              >
                <option value="ranking_score">Ranking Score</option>
                <option value="smart_score">Smart Score</option>
                <option value="activity_score">Activity Score</option>
                <option value="quality_score">Quality Score</option>
                <option value="backtest_score">Backtest Score</option>
                <option value="backtest_data_sufficiency_score">Sufficienza dati</option>
                <option value="exit_price_coverage_score">Exit price score</option>
                <option value="exit_price_local_observable_percent">Prezzi locali freschi</option>
                <option value="exit_price_current_route_percent">Route cached attuale</option>
                <option value="discovery_funnel_score">Candidate funnel score</option>
                <option value="discovery_funnel_priority">Priorità coda storico</option>
                <option value="discovery_funnel_history_budget">Budget storico allocato</option>
                <option value="backtest_total_return_percent">Rendimento backtest</option>
                <option value="backtest_max_drawdown_percent">Drawdown backtest</option>
                <option value="median_swap_sol_7d">Mediana swap</option>
                <option value="size_compatibility_ratio_7d">Compatibilità size</option>
                <option value="last_swap_at">Ultimo swap</option>
                <option value="volume_7d_sol">Volume 7d</option>
              </select>
              <label className="flex items-center gap-3 rounded-lg border border-slate-600 bg-slate-950 px-4 py-3 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={eligibleOnly}
                  onChange={(event) => setEligibleOnly(event.target.checked)}
                />
                Solo idonei
              </label>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[4100px] text-sm">
              <thead className="bg-slate-900 text-slate-400">
                <tr>
                  <th className="p-4 text-left">Wallet</th>
                  <th className="p-4">Hydration</th>
                  <th className="p-4">Storico esteso</th>
                  <th className="p-4">Import</th>
                  <th className="p-4">Ranking</th>
                  <th className="p-4">Smart</th>
                  <th className="p-4">Activity</th>
                  <th className="p-4">Classe attività</th>
                  <th className="p-4">Quality</th>
                  <th className="p-4">Suitability</th>
                  <th className="p-4">Promotion</th>
                  <th className="p-4">Backtest</th>
                  <th className="p-4">Sufficienza</th>
                  <th className="p-4">Return / PnL</th>
                  <th className="p-4">WR / PF</th>
                  <th className="p-4">DD / Coverage</th>
                  <th className="p-4">Jupiter</th>
                  <th className="p-4">Exit price</th>
                  <th className="p-4">Exitability gate</th>
                  <th className="p-4">Candidate funnel</th>
                  <th className="p-4">Mediana</th>
                  <th className="p-4">Dust</th>
                  <th className="p-4">Size compat.</th>
                  <th className="p-4">Token / conc.</th>
                  <th className="p-4">Cicli B→S</th>
                  <th className="p-4">Ultimo swap</th>
                  <th className="p-4">Swap 24h</th>
                  <th className="p-4">Swap 7d</th>
                  <th className="p-4">BUY / SELL 7d</th>
                  <th className="p-4">Volume 24h</th>
                  <th className="p-4">Volume 7d</th>
                  <th className="p-4">Giorni attivi</th>
                  <th className="p-4">Swap/giorno</th>
                  <th className="p-4">Frequenza media</th>
                  <th className="p-4">Idoneità</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700">
                {filteredWallets.map((wallet) => {
                  const activity = activityBadge(wallet.activity_classification);
                  const quality = qualityBadge(wallet.quality_classification);
                  const promotion = promotionBadge(wallet.promotion_status);
                  const exitPrice = exitPriceBadge(wallet.exit_price_coverage_status);
                  const exitabilityGate = exitabilityGateBadge(wallet.exitability_gate_status);
                  const discoveryFunnel = discoveryFunnelBadge(wallet.discovery_funnel_status);
                  const eligibility = eligibilityBadge(wallet);
                  return (
                    <tr key={wallet.wallet_address} className="hover:bg-slate-700/30">
                      <td className="p-4 font-mono text-xs">
                        <Link
                          to={`/wallet/${wallet.wallet_address}`}
                          title={wallet.wallet_address}
                          className="text-blue-400 hover:underline"
                        >
                          {shortenAddress(wallet.wallet_address)}
                        </Link>
                        <p className="mt-1 text-[10px] text-slate-600">
                          {wallet.discovered_from_token || "-"}
                        </p>
                      </td>
                      <td className="p-4 text-center">
                        {(() => {
                          const hydration = hydrationBadge(wallet.hydration_status);
                          return (
                            <span
                              title={wallet.hydration_error_message || formatDate(wallet.hydration_last_attempt_at)}
                              className={`rounded-full border px-2.5 py-1 text-xs font-bold ${hydration.className}`}
                            >
                              {hydration.label}
                            </span>
                          );
                        })()}
                      </td>
                      <td className="p-4 text-center">
                        {(() => {
                          const extended = hydrationBadge(wallet.extended_history_status);
                          return (
                            <span
                              title={wallet.extended_history_stop_reason || wallet.extended_history_error_message || formatDate(wallet.extended_history_last_attempt_at)}
                              className={`rounded-full border px-2.5 py-1 text-xs font-bold ${extended.className}`}
                            >
                              {extended.label}
                            </span>
                          );
                        })()}
                        <p className="mt-1 text-[10px] text-slate-500">
                          {wallet.extended_history_helius_requests ?? 0} req · {wallet.extended_history_trades_imported ?? 0} nuovi
                        </p>
                      </td>
                      <td className="p-4 text-center text-slate-300">
                        {wallet.hydration_trades_imported ?? 0}
                        <p className="text-[10px] text-slate-500">swap {wallet.hydration_swaps_found ?? 0}</p>
                      </td>
                      <td className="p-4 text-center font-bold text-cyan-300">{formatNumber(wallet.ranking_score)}</td>
                      <td className="p-4 text-center font-bold text-blue-300">{formatNumber(wallet.smart_score)}</td>
                      <td className="p-4 text-center font-bold text-purple-300">{formatNumber(wallet.activity_score)}</td>
                      <td className="p-4 text-center">
                        <span className={`rounded-full border px-2.5 py-1 text-xs font-bold ${activity.className}`}>{activity.label}</span>
                      </td>
                      <td className="p-4 text-center font-bold text-fuchsia-300">{formatNumber(wallet.quality_score)}</td>
                      <td className="p-4 text-center">
                        <span
                          title={(wallet.quality_reasons ?? []).join(", ")}
                          className={`rounded-full border px-2.5 py-1 text-xs font-bold ${quality.className}`}
                        >
                          {quality.label}
                        </span>
                      </td>
                      <td className="p-4 text-center">
                        <button
                          type="button"
                          onClick={() => handlePromotionBacktest(wallet.wallet_address)}
                          disabled={runningBacktest || !["COPIABILE", "OSSERVAZIONE"].includes(wallet.quality_classification)}
                          title={(wallet.promotion_reasons ?? []).join(", ")}
                          className={`rounded-full border px-2.5 py-1 text-xs font-bold disabled:cursor-not-allowed disabled:opacity-60 ${promotion.className}`}
                        >
                          {wallet.promotion_status === "NON_ANALIZZATO" && ["COPIABILE", "OSSERVAZIONE"].includes(wallet.quality_classification)
                            ? "BACKTEST"
                            : promotion.label}
                        </button>
                      </td>
                      <td className="p-4 text-center font-bold text-emerald-300">{formatNumber(wallet.backtest_score)}</td>
                      <td className="p-4 text-center">
                        <span
                          title={(wallet.backtest_data_sufficiency_reasons ?? []).join(", ")}
                          className={`rounded-full border px-2.5 py-1 text-xs font-bold ${wallet.backtest_data_sufficient ? "border-green-700 bg-green-950/60 text-green-300" : "border-orange-700 bg-orange-950/60 text-orange-300"}`}
                        >
                          {wallet.backtest_data_sufficient ? "SUFFICIENTE" : "INSUFFICIENTE"}
                        </span>
                        <p className="mt-1 text-[10px] text-slate-500">
                          {formatNumber(wallet.backtest_data_sufficiency_score)}% · {formatNumber(wallet.backtest_history_span_days, 1)} g
                        </p>
                      </td>
                      <td className="p-4 text-center text-slate-300">
                        {formatNumber(wallet.backtest_total_return_percent)}%
                        <p className="text-[10px] text-slate-500">{formatNumber(wallet.backtest_net_pnl_sol, 4)} SOL</p>
                      </td>
                      <td className="p-4 text-center text-slate-300">
                        {formatNumber(wallet.backtest_win_rate_percent)}%
                        <p className="text-[10px] text-slate-500">PF {wallet.backtest_profit_factor == null ? "-" : formatNumber(wallet.backtest_profit_factor)}</p>
                      </td>
                      <td className="p-4 text-center text-slate-300">
                        {formatNumber(wallet.backtest_max_drawdown_percent)}%
                        <p className="text-[10px] text-slate-500">cov. {formatNumber(wallet.backtest_execution_coverage_percent)}%</p>
                      </td>
                      <td className="p-4 text-center text-slate-300">
                        {wallet.backtest_jupiter_status}
                        <p className="text-[10px] text-slate-500">{formatNumber(wallet.backtest_jupiter_compatibility_percent)}%</p>
                      </td>
                      <td className="p-4 text-center">
                        <button
                          type="button"
                          onClick={() => handleExitPriceAudit(wallet.wallet_address)}
                          disabled={runningExitPriceAudit}
                          title={(wallet.exit_price_audit_reasons ?? []).join(", ")}
                          className={`rounded-full border px-2.5 py-1 text-xs font-bold disabled:opacity-50 ${exitPrice.className}`}
                        >
                          {wallet.exit_price_coverage_status === "NON_ANALIZZATO"
                            ? "AUDIT"
                            : exitPrice.label}
                        </button>
                        <p className="mt-1 text-[10px] text-slate-500">
                          {formatNumber(wallet.exit_price_coverage_score)}% · local {formatNumber(wallet.exit_price_local_observable_percent)}% · route {formatNumber(wallet.exit_price_current_route_percent)}%
                        </p>
                      </td>
                      <td className="p-4 text-center">
                        <span
                          title={(wallet.exitability_gate_reasons ?? []).join(", ")}
                          className={`rounded-full border px-2.5 py-1 text-xs font-bold ${exitabilityGate.className}`}
                        >
                          {exitabilityGate.label}
                        </span>
                        <p className="mt-1 text-[10px] text-slate-500">
                          {formatNumber(wallet.exitability_gate_score)}%
                        </p>
                      </td>
                      <td className="p-4 text-center">
                        <span
                          title={(wallet.discovery_funnel_reasons ?? []).join(", ")}
                          className={`rounded-full border px-2.5 py-1 text-xs font-bold ${discoveryFunnel.className}`}
                        >
                          {discoveryFunnel.label}
                        </span>
                        <p className="mt-1 text-[10px] text-slate-500">
                          {formatNumber(wallet.discovery_funnel_score)}% · {wallet.discovery_funnel_action || "-"}
                        </p>
                        {Number(wallet.discovery_funnel_priority ?? 0) > 0 && (
                          <p className="mt-1 text-[10px] font-bold text-cyan-300">
                            Coda #{wallet.discovery_funnel_priority} · {wallet.discovery_funnel_history_budget ?? 0} req
                          </p>
                        )}
                      </td>
                      <td className="p-4 text-center text-slate-300">{formatNumber(wallet.median_swap_sol_7d, 4)} SOL</td>
                      <td className="p-4 text-center text-slate-300">{formatNumber(Number(wallet.dust_ratio_7d ?? 0) * 100, 1)}%</td>
                      <td className="p-4 text-center text-slate-300">{formatNumber(Number(wallet.size_compatibility_ratio_7d ?? 0) * 100, 1)}%</td>
                      <td className="p-4 text-center text-slate-300">{wallet.unique_tokens_7d ?? 0} / {formatNumber(Number(wallet.top_token_concentration_7d ?? 0) * 100, 1)}%</td>
                      <td className="p-4 text-center text-slate-300">{wallet.completed_token_pairs_7d ?? 0}</td>
                      <td className="p-4 text-center text-xs text-slate-400">{formatDate(wallet.last_swap_at)}</td>
                      <td className="p-4 text-center text-slate-300">{wallet.swaps_24h}</td>
                      <td className="p-4 text-center text-slate-300">{wallet.swaps_7d}</td>
                      <td className="p-4 text-center text-slate-300">{wallet.buys_7d} / {wallet.sells_7d}</td>
                      <td className="p-4 text-center text-slate-300">{formatNumber(wallet.volume_24h_sol, 4)} SOL</td>
                      <td className="p-4 text-center text-slate-300">{formatNumber(wallet.volume_7d_sol, 4)} SOL</td>
                      <td className="p-4 text-center text-slate-300">{wallet.active_days_7d}</td>
                      <td className="p-4 text-center text-slate-300">{formatNumber(wallet.average_swaps_per_active_day_7d, 2)}</td>
                      <td className="p-4 text-center text-slate-300">{formatFrequency(wallet.average_minutes_between_swaps_7d)}</td>
                      <td className="p-4 text-center">
                        <span
                          title={(wallet.eligibility_reasons ?? []).join(", ")}
                          className={`rounded-full border px-2.5 py-1 text-xs font-bold ${eligibility.className}`}
                        >
                          {eligibility.label}
                        </span>
                      </td>
                    </tr>
                  );
                })}
                {!filteredWallets.length && (
                  <tr>
                    <td colSpan="35" className="p-10 text-center text-slate-500">
                      Nessun wallet corrisponde ai filtri selezionati.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="flex items-center justify-between border-b border-slate-700 p-5">
            <div>
              <h2 className="text-xl font-bold">Cronologia locale</h2>
              <p className="mt-1 text-sm text-slate-400">Ultime 20 esecuzioni memorizzate nel browser.</p>
            </div>
            <button
              type="button"
              onClick={clearHistory}
              className="rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-300"
            >
              Cancella
            </button>
          </div>
          <div className="divide-y divide-slate-700">
            {historyItems.map((item) => (
              <div key={item.id} className="grid gap-3 p-4 text-sm md:grid-cols-5">
                <span className="font-bold text-blue-300">{item.mode}</span>
                <span className="font-mono text-xs text-slate-400">{shortenAddress(item.seed_wallet)}</span>
                <span>Analizzati: {item.wallets_analyzed}</span>
                <span className="text-green-300">Idonei: {item.wallets_eligible ?? 0}</span>
                <span className="text-slate-500">{formatDate(item.created_at)}</span>
              </div>
            ))}
            {!historyItems.length && (
              <div className="p-8 text-center text-slate-500">Nessuna discovery nella cronologia locale.</div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}


export default Discovery;
