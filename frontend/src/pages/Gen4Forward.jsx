import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import Gen4ForwardEquityChart from "../components/gen4Forward/Gen4ForwardEquityChart";
import Gen4CopyabilityPanel from "../components/gen4Forward/Gen4CopyabilityPanel";
import Gen4ForwardLaneCard from "../components/gen4Forward/Gen4ForwardLaneCard";
import Gen4ForwardFeedPanel from "../components/gen4Forward/Gen4ForwardFeedPanel";
import Gen4ForwardMetric from "../components/gen4Forward/Gen4ForwardMetric";
import Gen4ForwardProgress from "../components/gen4Forward/Gen4ForwardProgress";
import {
  Gen4CycleTable,
  Gen4DecisionTable,
  Gen4FrozenWallets,
} from "../components/gen4Forward/Gen4ForwardTables";
import {
  GEN4_FORWARD_ACCESS_KEY_STORAGE,
  GEN4_FORWARD_AUTO_REFRESH_MS,
  buildGen4EquitySeries,
  computeGen4Progress,
  formatGen4Date,
  formatGen4Duration,
  formatGen4Number,
  getGen4StatusTone,
  parseGen4ApiError,
  shortenGen4Address,
} from "../components/gen4Forward/gen4ForwardFormatters";
import {
  getGen4CopyabilityStatus,
  getGen4ForwardCampaign,
  getGen4ForwardFeedStatus,
  getGen4ForwardStatus,
  runGen4ForwardCycle,
  runGen4ForwardFeedPoll,
} from "../services/gen4ForwardApi";

const STATUS_CLASSES = {
  positive: "border-emerald-800 bg-emerald-950/50 text-emerald-300",
  warning: "border-amber-800 bg-amber-950/50 text-amber-300",
  danger: "border-red-800 bg-red-950/50 text-red-300",
  neutral: "border-slate-700 bg-slate-900 text-slate-300",
};

function StatusBadge({ value }) {
  const tone = getGen4StatusTone(value);
  return (
    <span
      className={`inline-flex rounded-full border px-3 py-1 text-xs font-black ${
        STATUS_CLASSES[tone] ?? STATUS_CLASSES.neutral
      }`}
    >
      {value || "N/D"}
    </span>
  );
}

function AccessGate({
  keyInput,
  connecting,
  error,
  onKeyInputChange,
  onConnect,
}) {
  return (
    <main className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-7xl items-center justify-center p-4 sm:p-8">
      <section className="w-full max-w-xl rounded-3xl border border-slate-700 bg-slate-800/90 p-6 shadow-2xl shadow-black/30 sm:p-8">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-cyan-700 bg-cyan-950/60 text-2xl">
          🧠
        </div>
        <h1 className="mt-6 text-3xl font-black text-white">
          Gen 4 Forward
        </h1>
        <p className="mt-3 leading-7 text-slate-400">
          Inserisci la chiave <code className="text-cyan-300">AUTOMATION_API_KEY</code> configurata nel backend. La chiave rimane soltanto nella sessione di questa scheda.
        </p>
        <form onSubmit={onConnect} className="mt-7 space-y-4">
          <label className="block">
            <span className="text-sm font-bold text-slate-300">
              X-Automation-Key
            </span>
            <input
              type="password"
              autoComplete="off"
              value={keyInput}
              onChange={(event) => onKeyInputChange(event.target.value)}
              placeholder="Chiave automazione"
              className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 font-mono text-white outline-none transition focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20"
            />
          </label>
          {error && (
            <div className="rounded-xl border border-red-700 bg-red-950/50 px-4 py-3 text-sm text-red-300">
              {error}
            </div>
          )}
          <button
            type="submit"
            disabled={connecting || !keyInput.trim()}
            className="w-full rounded-xl bg-cyan-600 px-5 py-3 font-black text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {connecting ? "Verifica accesso..." : "Apri dashboard Gen 4"}
          </button>
        </form>
        <div className="mt-6 rounded-xl border border-slate-700 bg-slate-900/70 p-4 text-xs leading-6 text-slate-500">
          La dashboard non richiede chiavi private Solana e non può creare ordini paper o LIVE.
        </div>
      </section>
    </main>
  );
}

function EvidenceGaps({ gaps }) {
  return (
    <section className="rounded-3xl border border-amber-800/70 bg-amber-950/20 p-5 sm:p-6">
      <p className="text-xs font-bold uppercase tracking-[0.2em] text-amber-400">
        Condizioni ancora mancanti
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        {(gaps ?? []).length > 0 ? (
          gaps.map((gap) => (
            <span
              key={gap}
              className="rounded-full border border-amber-800 bg-amber-950/60 px-3 py-1.5 text-xs font-bold text-amber-200"
            >
              {gap}
            </span>
          ))
        ) : (
          <span className="text-sm text-emerald-300">
            Nessun evidence gap registrato.
          </span>
        )}
      </div>
    </section>
  );
}

function Gen4Forward() {
  const [accessKey, setAccessKey] = useState(
    sessionStorage.getItem(GEN4_FORWARD_ACCESS_KEY_STORAGE) ?? ""
  );
  const [keyInput, setKeyInput] = useState("");
  const [status, setStatus] = useState(null);
  const [campaign, setCampaign] = useState(null);
  const [feed, setFeed] = useState(null);
  const [copyability, setCopyability] = useState(null);
  const [connecting, setConnecting] = useState(false);
  const [loading, setLoading] = useState(false);
  const [cycleBusy, setCycleBusy] = useState(false);
  const [feedBusy, setFeedBusy] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [laneFilter, setLaneFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const clearAccess = useCallback((reason = "") => {
    sessionStorage.removeItem(GEN4_FORWARD_ACCESS_KEY_STORAGE);
    setAccessKey("");
    setKeyInput("");
    setStatus(null);
    setCampaign(null);
    setFeed(null);
    setCopyability(null);
    setError(reason);
  }, []);

  const handleRequestError = useCallback(
    (requestError) => {
      if (requestError?.response?.status === 401) {
        clearAccess("Chiave di automazione non valida o scaduta.");
        return;
      }
      setError(parseGen4ApiError(requestError));
    },
    [clearAccess]
  );

  const loadDashboard = useCallback(
    async (showLoader = false, keyOverride = "") => {
      const key = (keyOverride || accessKey).trim();
      if (!key) {
        return false;
      }

      if (showLoader) {
        setLoading(true);
      }
      setError("");

      try {
        const statusResponse = await getGen4ForwardStatus(key);
        const nextStatus = statusResponse.data;
        setStatus(nextStatus);

        const feedResponse = await getGen4ForwardFeedStatus(key);
        setFeed(feedResponse.data);

        const copyabilityResponse = await getGen4CopyabilityStatus(key, 100);
        setCopyability(copyabilityResponse.data);

        const campaignId =
          nextStatus.active_campaign_id ||
          nextStatus.latest_campaign?.campaign_id;

        if (campaignId) {
          const campaignResponse = await getGen4ForwardCampaign(
            key,
            campaignId,
            {
              includeDecisions: true,
              decisionLimit: 1000,
            }
          );
          setCampaign(campaignResponse.data);
        } else {
          setCampaign(null);
        }

        setLastUpdated(new Date());
        return true;
      } catch (requestError) {
        handleRequestError(requestError);
        return false;
      } finally {
        if (showLoader) {
          setLoading(false);
        }
      }
    },
    [accessKey, handleRequestError]
  );

  useEffect(() => {
    if (!accessKey) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      loadDashboard(true);
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, [accessKey, loadDashboard]);

  useEffect(() => {
    if (!accessKey || !autoRefresh) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      loadDashboard(false);
    }, GEN4_FORWARD_AUTO_REFRESH_MS);

    return () => window.clearInterval(intervalId);
  }, [accessKey, autoRefresh, loadDashboard]);

  async function connect(event) {
    event.preventDefault();
    const key = keyInput.trim();
    if (!key) {
      return;
    }

    setConnecting(true);
    setError("");
    const connected = await loadDashboard(false, key);
    if (connected) {
      sessionStorage.setItem(GEN4_FORWARD_ACCESS_KEY_STORAGE, key);
      setAccessKey(key);
      setKeyInput("");
    }
    setConnecting(false);
  }

  async function runFeedPoll() {
    if (!campaign?.campaign_id || campaign.status !== "ACTIVE") {
      return;
    }

    setFeedBusy(true);
    setError("");
    setMessage("");

    try {
      const response = await runGen4ForwardFeedPoll(
        accessKey,
        campaign.campaign_id
      );
      const run = response.data?.run;
      setMessage(
        run
          ? `Feed ${run.status}: ${run.helius_requests ?? 0} richieste Helius, ${run.trades_imported ?? 0} trade importati, ${run.new_decisions ?? 0} nuove decisioni.`
          : "Poll feed completato."
      );
      await loadDashboard(false);
    } catch (requestError) {
      handleRequestError(requestError);
    } finally {
      setFeedBusy(false);
    }
  }

  async function runCycle() {
    if (!campaign?.campaign_id || campaign.status !== "ACTIVE") {
      return;
    }

    setCycleBusy(true);
    setError("");
    setMessage("");

    try {
      const response = await runGen4ForwardCycle(
        accessKey,
        campaign.campaign_id
      );
      const cycle = response.data?.cycle;
      const summary = cycle
        ? `Ciclo #${cycle.sequence} completato: ${cycle.new_decision_count ?? 0} nuove decisioni, ${cycle.updated_decision_count ?? 0} aggiornate.`
        : "Ciclo forward completato.";
      setMessage(summary);
      await loadDashboard(false);
    } catch (requestError) {
      handleRequestError(requestError);
    } finally {
      setCycleBusy(false);
    }
  }

  const progress = useMemo(
    () => computeGen4Progress(campaign),
    [campaign]
  );

  const equityData = useMemo(
    () => buildGen4EquitySeries(campaign?.recent_decisions ?? []),
    [campaign]
  );

  const campaignAge = useMemo(() => {
    if (!campaign?.anchor_at) {
      return "N/D";
    }
    return formatGen4Duration(
      Date.now() - new Date(campaign.anchor_at).getTime()
    );
  }, [campaign?.anchor_at, lastUpdated]);

  if (!accessKey) {
    return (
      <AccessGate
        keyInput={keyInput}
        connecting={connecting}
        error={error}
        onKeyInputChange={setKeyInput}
        onConnect={connect}
      />
    );
  }

  return (
    <main className="min-h-[calc(100vh-4rem)] bg-slate-900 text-white">
      <header className="border-b border-slate-700 bg-slate-950/60">
        <div className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-3xl font-black sm:text-4xl">
                  Gen 4 Strict Forward
                </h1>
                <StatusBadge value={campaign?.status || "NO CAMPAIGN"} />
                <StatusBadge value={campaign?.verdict || "NOT READY"} />
              </div>
              <p className="mt-3 max-w-3xl leading-7 text-slate-400">
                Dashboard della prova forward point-in-time. Nessun backfill precedente all'anchor può diventare evidenza Strict.
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => setAutoRefresh((current) => !current)}
                className={`rounded-xl border px-4 py-2 text-sm font-bold transition ${
                  autoRefresh
                    ? "border-emerald-800 bg-emerald-950/50 text-emerald-300"
                    : "border-slate-700 bg-slate-900 text-slate-300"
                }`}
              >
                Auto refresh {autoRefresh ? "ON" : "OFF"}
              </button>
              <button
                type="button"
                onClick={() => loadDashboard(true)}
                disabled={loading}
                className="rounded-xl border border-slate-600 bg-slate-800 px-4 py-2 text-sm font-bold text-white transition hover:bg-slate-700 disabled:opacity-50"
              >
                {loading ? "Aggiornamento..." : "Aggiorna"}
              </button>
              <button
                type="button"
                onClick={runFeedPoll}
                disabled={
                  feedBusy ||
                  campaign?.status !== "ACTIVE" ||
                  feed?.runtime_enabled !== true
                }
                title="Acquisisce i nuovi swap dei wallet congelati e avvia subito un ciclo shadow."
                className="rounded-xl border border-cyan-700 bg-cyan-950/50 px-4 py-2 text-sm font-black text-cyan-300 transition hover:bg-cyan-900/60 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {feedBusy ? "Acquisizione..." : "Acquisisci ora"}
              </button>
              <button
                type="button"
                onClick={runCycle}
                disabled={
                  cycleBusy ||
                  campaign?.status !== "ACTIVE" ||
                  status?.enabled !== true
                }
                title={
                  status?.enabled === false
                    ? "Riavvia il backend dopo l'installazione per abilitare il runtime shadow."
                    : "Esegue un ciclo Gen 4 shadow senza paper o LIVE."
                }
                className="rounded-xl bg-cyan-500 px-5 py-2 text-sm font-black text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {cycleBusy
                  ? "Ciclo in corso..."
                  : status?.enabled === false
                    ? "Runtime shadow OFF"
                    : "Esegui ciclo shadow"}
              </button>
              <button
                type="button"
                onClick={() => clearAccess("")}
                className="rounded-xl border border-red-900 bg-red-950/30 px-4 py-2 text-sm font-bold text-red-300 transition hover:bg-red-950/60"
              >
                Disconnetti
              </button>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-xs text-slate-500">
            <span>Ultimo aggiornamento: {lastUpdated ? lastUpdated.toLocaleTimeString("it-IT") : "in attesa"}</span>
            <span>API: {status?.policy_version ?? "N/D"}</span>
            <span>Runtime shadow: {status?.enabled ? "ON" : "OFF"}</span>
            <span>Feed automatico: {feed?.worker_running ? "RUNNING" : "STOPPED"}</span>
            <span>Polling: {feed?.state?.interval_seconds ?? 0}s (recovery only)</span>
            <span>Real-time: {copyability?.worker_running ? "RUNNING" : "STOPPED"}</span>
            <span>Webhook: {copyability?.campaign?.webhook?.status ?? "N/D"}</span>
            <span>Stato sicurezza: nessun paper / LIVE</span>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1600px] space-y-6 px-4 py-6 sm:px-6 lg:px-8">
        {error && (
          <div className="rounded-2xl border border-red-800 bg-red-950/40 px-5 py-4 text-red-300">
            {error}
          </div>
        )}
        {message && (
          <div className="rounded-2xl border border-emerald-800 bg-emerald-950/35 px-5 py-4 text-emerald-300">
            {message}
          </div>
        )}
        {status && status.enabled === false && (
          <div className="rounded-2xl border border-amber-800 bg-amber-950/35 px-5 py-4 text-amber-200">
            Il runtime Gen 4 shadow è disabilitato nel processo backend corrente.
            Riavvia il backend dopo l'installazione M54–M55; la dashboard rimane
            consultabile, ma il pulsante ciclo resta bloccato finché lo stato non
            diventa ON.
          </div>
        )}

        {!campaign ? (
          <section className="rounded-3xl border border-dashed border-slate-700 bg-slate-800/50 p-10 text-center">
            <h2 className="text-2xl font-black">Nessuna campagna Gen 4 trovata</h2>
            <p className="mt-3 text-slate-400">
              Avvia prima M52–M53 dal backend, poi aggiorna questa pagina.
            </p>
          </section>
        ) : (
          <>
            <Gen4CopyabilityPanel status={copyability} />

            <Gen4ForwardFeedPanel feed={feed} />

            <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-6">
              <Gen4ForwardMetric
                label="Campagna"
                value={shortenGen4Address(campaign.campaign_id, 8, 6)}
                subtitle={`Anchor ${formatGen4Date(campaign.anchor_at)}`}
                tone="info"
              />
              <Gen4ForwardMetric
                label="Età forward"
                value={campaignAge}
                subtitle={`Minimo ${campaign.minimum_observation_days} giorni`}
                tone="warning"
              />
              <Gen4ForwardMetric
                label="Wallet congelati"
                value={campaign.frozen_wallet_count ?? 0}
                subtitle="Snapshot immutabile della campagna"
                tone="positive"
              />
              <Gen4ForwardMetric
                label="Cicli"
                value={campaign.cycle_count ?? 0}
                subtitle={`Watermark ${formatGen4Date(campaign.latest_observed_at)}`}
              />
              <Gen4ForwardMetric
                label="Decisioni"
                value={campaign.decision_count ?? 0}
                subtitle={`${campaign.rejected_decision_count ?? 0} respinte`}
              />
              <Gen4ForwardMetric
                label="Strict chiusi"
                value={`${campaign.strict_closed_trade_count ?? 0}/${campaign.minimum_closed_trades ?? 30}`}
                subtitle={`Proof target ${campaign.proof_closed_trades ?? 100}`}
                tone="info"
              />
            </section>

            <Gen4ForwardProgress progress={progress} />
            <EvidenceGaps gaps={campaign.evidence_gaps} />

            <section className="grid gap-5 xl:grid-cols-3">
              <Gen4ForwardLaneCard
                lane="STRICT_GEN4_FORWARD"
                metrics={campaign.strict_metrics}
              />
              <Gen4ForwardLaneCard
                lane="SIGNAL_ONLY_FORWARD"
                metrics={campaign.proxy_metrics}
              />
              <Gen4ForwardLaneCard
                lane="SIMPLE_COPY_FORWARD_BASELINE"
                metrics={campaign.baseline_metrics}
              />
            </section>

            <Gen4ForwardEquityChart data={equityData} />

            <section className="grid gap-6 2xl:grid-cols-2">
              <Gen4FrozenWallets campaign={campaign} />
              <Gen4CycleTable cycles={campaign.recent_cycles} />
            </section>

            <Gen4DecisionTable
              decisions={campaign.recent_decisions}
              laneFilter={laneFilter}
              statusFilter={statusFilter}
              onLaneFilterChange={setLaneFilter}
              onStatusFilterChange={setStatusFilter}
            />

            <section className="rounded-3xl border border-slate-700 bg-slate-950/40 p-5 text-xs leading-6 text-slate-500 sm:p-6">
              <p className="font-bold text-slate-300">Contratto di sicurezza</p>
              <p className="mt-2">
                Campagna {campaign.campaign_id} · hash evidenza {shortenGen4Address(campaign.evidence_hash, 10, 8)} · {formatGen4Number(campaign.safety?.external_requests ?? 0, 0)} richieste esterne · {formatGen4Number(campaign.safety?.paper_orders_created ?? 0, 0)} ordini paper · {formatGen4Number(campaign.safety?.live_orders_created ?? 0, 0)} ordini LIVE.
              </p>
            </section>
          </>
        )}
      </div>
    </main>
  );
}

export default Gen4Forward;
