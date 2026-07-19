import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import LiveTradingWorkerPanel from "../components/liveTrading/LiveTradingWorkerPanel";
import LiveTradingBadge from "../components/liveTrading/LiveTradingBadge";
import LiveTradingDryRunReset from "../components/liveTrading/LiveTradingDryRunReset";
import LiveTradingEvents from "../components/liveTrading/LiveTradingEvents";
import LiveTradingMetric from "../components/liveTrading/LiveTradingMetric";
import LiveTradingOrders from "../components/liveTrading/LiveTradingOrders";
import LiveTradingPolicyForm from "../components/liveTrading/LiveTradingPolicyForm";
import LiveTradingPositions from "../components/liveTrading/LiveTradingPositions";
import LiveTradingSection from "../components/liveTrading/LiveTradingSection";
import {
  formatLiveDate,
  formatLiveNumber,
  parseLiveApiError,
  shortenLiveAddress,
} from "../components/liveTrading/liveTradingFormatters";
import {
  engageLiveTradingKillSwitch,
  executeLiveTradingSourceTrade,
  getLiveTradingEvents,
  getLiveTradingOrders,
  getLiveTradingPositions,
  getLiveTradingStatus,
  releaseLiveTradingKillSwitch,
  resetLiveTradingDryRun,
  updateLiveTradingPolicy,
} from "../services/liveTradingApi";


const ACCESS_KEY_STORAGE =
  "smartmoney-live-trading-access-key";

const AUTO_REFRESH_MS = 15_000;

const TABS = [
  ["control", "Controllo e policy"],
  ["orders", "Ordini"],
  ["positions", "Posizioni"],
  ["events", "Eventi"],
];


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
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-blue-700 bg-blue-950/60 text-2xl">
          🔐
        </div>

        <h1 className="mt-6 text-3xl font-bold text-white">
          Live Copy Trading
        </h1>

        <p className="mt-3 leading-7 text-slate-400">
          Inserisci la chiave interna configurata nel backend. La chiave resta soltanto nella sessione di questa scheda e viene rimossa alla chiusura del browser.
        </p>

        <form
          onSubmit={onConnect}
          className="mt-7 space-y-4"
        >
          <label className="block">
            <span className="text-sm font-bold text-slate-300">
              X-Live-Trading-Key
            </span>

            <input
              type="password"
              autoComplete="off"
              value={keyInput}
              onChange={(event) =>
                onKeyInputChange(
                  event.target.value
                )
              }
              placeholder="Chiave Live Trading"
              className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 font-mono text-white outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
            />
          </label>

          {error && (
            <div className="rounded-xl border border-red-700 bg-red-950/50 px-4 py-3 text-sm text-red-300">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={
              connecting
              || !keyInput.trim()
            }
            className="w-full rounded-xl bg-blue-600 px-5 py-3 font-bold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {connecting
              ? "Verifica accesso..."
              : "Accedi alla dashboard"}
          </button>
        </form>

        <div className="mt-6 rounded-xl border border-slate-700 bg-slate-900/70 p-4 text-xs leading-6 text-slate-500">
          Questa schermata non richiede e non mostra mai la chiave privata del wallet Solana.
        </div>
      </section>
    </main>
  );
}


function LiveTrading() {
  const [accessKey, setAccessKey] =
    useState(
      sessionStorage.getItem(
        ACCESS_KEY_STORAGE
      ) ?? ""
    );

  const [keyInput, setKeyInput] =
    useState("");

  const [status, setStatus] =
    useState(null);

  const [orders, setOrders] =
    useState([]);

  const [positions, setPositions] =
    useState([]);

  const [events, setEvents] =
    useState([]);

  const [activeTab, setActiveTab] =
    useState("control");

  const [orderFilters, setOrderFilters] =
    useState({
      status: "",
      mode: "",
    });

  const [positionFilters, setPositionFilters] =
    useState({
      status: "",
      mode: "",
    });

  const [manualTradeId, setManualTradeId] =
    useState("");

  const [releaseConfirmation, setReleaseConfirmation] =
    useState("");

  const [loading, setLoading] =
    useState(false);

  const [connecting, setConnecting] =
    useState(false);

  const [busyAction, setBusyAction] =
    useState("");

  const [error, setError] =
    useState("");

  const [message, setMessage] =
    useState("");

  const [lastUpdated, setLastUpdated] =
    useState(null);

  const [autoRefresh, setAutoRefresh] =
    useState(true);

  const [historyScope, setHistoryScope] =
    useState("ACTIVE");

  const clearAccess = useCallback(
    (reason = "") => {
      sessionStorage.removeItem(
        ACCESS_KEY_STORAGE
      );

      setAccessKey("");
      setKeyInput("");
      setStatus(null);
      setOrders([]);
      setPositions([]);
      setEvents([]);
      setError(reason);
    },
    []
  );

  const handleRequestError = useCallback(
    (requestError) => {
      if (
        requestError?.response?.status
        === 401
      ) {
        clearAccess(
          "Chiave Live Trading non valida o scaduta."
        );
        return;
      }

      setError(
        parseLiveApiError(
          requestError
        )
      );
    },
    [clearAccess]
  );

  const loadDashboard = useCallback(
    async (
      showLoader = false,
      keyOverride = ""
    ) => {
      const key = (
        keyOverride || accessKey
      ).trim();

      if (!key) {
        return false;
      }

      if (showLoader) {
        setLoading(true);
      }

      setError("");

      try {
        const [
          statusResponse,
          ordersResponse,
          positionsResponse,
          eventsResponse,
        ] = await Promise.all([
          getLiveTradingStatus(key),
          getLiveTradingOrders(
            key,
            {
              ...orderFilters,
              scope: historyScope,
            }
          ),
          getLiveTradingPositions(
            key,
            {
              ...positionFilters,
              scope: historyScope,
            }
          ),
          getLiveTradingEvents(
            key,
            200,
            historyScope
          ),
        ]);

        setStatus(
          statusResponse.data
        );

        setOrders(
          ordersResponse.data.orders
          ?? []
        );

        setPositions(
          positionsResponse.data.positions
          ?? []
        );

        setEvents(
          eventsResponse.data.events
          ?? []
        );

        setLastUpdated(
          new Date()
        );

        return true;
      } catch (requestError) {
        handleRequestError(
          requestError
        );
        return false;
      } finally {
        if (showLoader) {
          setLoading(false);
        }
      }
    },
    [
      accessKey,
      handleRequestError,
      historyScope,
      orderFilters,
      positionFilters,
    ]
  );

  useEffect(() => {
    if (!accessKey) {
      return undefined;
    }

    const timeoutId = window.setTimeout(
      () => {
        loadDashboard(true);
      },
      0
    );

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [accessKey, loadDashboard]);

  useEffect(() => {
    if (
      !accessKey
      || !autoRefresh
    ) {
      return undefined;
    }

    const intervalId = window.setInterval(
      () => {
        loadDashboard(false);
      },
      AUTO_REFRESH_MS
    );

    return () => {
      window.clearInterval(
        intervalId
      );
    };
  }, [
    accessKey,
    autoRefresh,
    loadDashboard,
  ]);

  async function handleConnect(event) {
    event.preventDefault();

    const nextKey = keyInput.trim();

    if (!nextKey) {
      setError(
        "Inserisci la chiave Live Trading."
      );
      return;
    }

    setConnecting(true);
    setError("");

    const connected = await loadDashboard(
      false,
      nextKey
    );

    if (connected) {
      sessionStorage.setItem(
        ACCESS_KEY_STORAGE,
        nextKey
      );

      setAccessKey(nextKey);
      setKeyInput("");
    }

    setConnecting(false);
  }

  async function runAction(
    actionName,
    action,
    successMessage
  ) {
    setBusyAction(actionName);
    setError("");
    setMessage("");

    try {
      await action();

      setMessage(successMessage);

      await loadDashboard(false);

      return true;
    } catch (requestError) {
      handleRequestError(
        requestError
      );
      return false;
    } finally {
      setBusyAction("");
    }
  }

  async function handlePolicySave(payload) {
    await runAction(
      "policy",
      () =>
        updateLiveTradingPolicy(
          accessKey,
          payload
        ),
      "Policy Live Trading aggiornata."
    );
  }

  async function handleDryRunReset(
    payload
  ) {
    const resetCompleted = await runAction(
      "dry-run-reset",
      () =>
        resetLiveTradingDryRun(
          accessKey,
          payload
        ),
      "Nuova generazione DRY_RUN creata. Storico precedente archiviato."
    );

    if (resetCompleted) {
      setHistoryScope("ACTIVE");
      setActiveTab("control");
    }

    return resetCompleted;
  }


  async function handleKillSwitch() {
    const confirmed = window.confirm(
      "Attivare immediatamente il kill switch? Lo stream automatico verrà disabilitato."
    );

    if (!confirmed) {
      return;
    }

    await runAction(
      "kill-switch",
      () =>
        engageLiveTradingKillSwitch(
          accessKey
        ),
      "Kill switch attivato."
    );
  }

  async function handleKillSwitchRelease(
    event
  ) {
    event.preventDefault();

    const released = await runAction(
      "release-kill-switch",
      () =>
        releaseLiveTradingKillSwitch(
          accessKey,
          releaseConfirmation
        ),
      "Kill switch rilasciato."
    );

    if (released) {
      setReleaseConfirmation("");
    }
  }

  async function handleManualExecution(
    event
  ) {
    event.preventDefault();

    const tradeId = Number(
      manualTradeId
    );

    if (
      !Number.isInteger(tradeId)
      || tradeId <= 0
    ) {
      setError(
        "Inserisci un ID trade intero e positivo."
      );
      return;
    }

    const executed = await runAction(
      "manual-execution",
      () =>
        executeLiveTradingSourceTrade(
          accessKey,
          tradeId
        ),
      "Trade sorgente elaborato dal motore copy-trading."
    );

    if (executed) {
      setManualTradeId("");
      setActiveTab("orders");
    }
  }

  const policy = status?.policy;

  const modeTone = useMemo(() => {
    if (policy?.mode === "LIVE") {
      return "danger";
    }

    if (policy?.mode === "DRY_RUN") {
      return "info";
    }

    return "default";
  }, [policy?.mode]);

  if (!accessKey) {
    return (
      <div className="min-h-screen bg-slate-900 text-white">
        <AccessGate
          keyInput={keyInput}
          connecting={connecting}
          error={error}
          onKeyInputChange={setKeyInput}
          onConnect={handleConnect}
        />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700 bg-slate-950/50">
        <div className="mx-auto max-w-[1600px] px-4 py-7 sm:px-6 lg:px-8">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-3xl font-bold sm:text-4xl">
                  Live Copy Trading
                </h1>

                {policy && (
                  <LiveTradingBadge
                    value={policy.mode}
                  />
                )}

                {policy?.kill_switch && (
                  <LiveTradingBadge
                    value="CRITICAL"
                  />
                )}
              </div>

              <p className="mt-2 max-w-3xl text-slate-400">
                Controllo centralizzato di policy, rischio, ordini Jupiter, posizioni e audit del motore di esecuzione.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() =>
                  setHistoryScope(
                    (current) =>
                      current === "ACTIVE"
                        ? "ALL"
                        : "ACTIVE"
                  )
                }
                className={`rounded-xl border px-4 py-2.5 text-sm font-bold transition ${
                  historyScope === "ACTIVE"
                    ? "border-blue-700 bg-blue-950/50 text-blue-300"
                    : "border-amber-700 bg-amber-950/50 text-amber-300"
                }`}
              >
                {historyScope === "ACTIVE"
                  ? "Generazione attiva"
                  : "Storico completo"}
              </button>

              <button
                type="button"
                onClick={() =>
                  setAutoRefresh(
                    (current) => !current
                  )
                }
                className={`rounded-xl border px-4 py-2.5 text-sm font-bold transition ${
                  autoRefresh
                    ? "border-green-700 bg-green-950/50 text-green-300"
                    : "border-slate-600 bg-slate-800 text-slate-300"
                }`}
              >
                Auto refresh {
                  autoRefresh
                    ? "ON"
                    : "OFF"
                }
              </button>

              <button
                type="button"
                onClick={() =>
                  loadDashboard(true)
                }
                disabled={loading}
                className="rounded-xl border border-blue-700 bg-blue-950/50 px-4 py-2.5 text-sm font-bold text-blue-300 transition hover:bg-blue-900/60 disabled:opacity-50"
              >
                {loading
                  ? "Aggiornamento..."
                  : "Aggiorna tutto"}
              </button>

              <button
                type="button"
                onClick={() =>
                  clearAccess("")
                }
                className="rounded-xl border border-slate-600 bg-slate-800 px-4 py-2.5 text-sm font-bold text-slate-300 transition hover:border-red-700 hover:text-red-300"
              >
                Disconnetti
              </button>
            </div>
          </div>

          <p className="mt-4 text-xs text-slate-500">
            Ultimo aggiornamento: {lastUpdated
              ? formatLiveDate(lastUpdated)
              : "in attesa"}
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] space-y-6 px-4 py-6 sm:px-6 lg:px-8">
        {error && (
          <div className="rounded-xl border border-red-700 bg-red-950/50 px-4 py-3 text-red-300">
            {error}
          </div>
        )}

        {message && (
          <div className="rounded-xl border border-green-700 bg-green-950/50 px-4 py-3 text-green-300">
            {message}
          </div>
        )}

        {policy?.mode === "LIVE" && (
          <div className="rounded-2xl border border-red-600 bg-red-950/60 p-5 shadow-lg shadow-red-950/30">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-lg font-bold text-red-200">
                  Modalità LIVE attiva
                </h2>

                <p className="mt-1 text-sm leading-6 text-red-300/80">
                  Gli ordini idonei possono utilizzare denaro reale. Verifica saldo, allowlist e limiti prima di attivare lo stream.
                </p>
              </div>

              <button
                type="button"
                onClick={handleKillSwitch}
                disabled={
                  busyAction
                  === "kill-switch"
                }
                className="shrink-0 rounded-xl bg-red-600 px-5 py-3 font-bold text-white transition hover:bg-red-500 disabled:opacity-50"
              >
                ATTIVA KILL SWITCH
              </button>
            </div>
          </div>
        )}

        {policy && (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <LiveTradingMetric
              label="Modalità"
              value={policy.mode}
              tone={modeTone}
              subtitle={`${
                policy.stream_execution_enabled
                  ? "Stream automatico attivo"
                  : "Stream automatico spento"
              } · Generazione #${
                status.active_generation
                ?? policy.dry_run_generation
              }`}
            />

            <LiveTradingMetric
              label="Saldo wallet"
              value={
                status.wallet_balance_sol
                === null
                  ? "Non disponibile"
                  : `${formatLiveNumber(
                      status.wallet_balance_sol,
                      6
                    )} SOL`
              }
              tone={
                status.wallet_balance_sol
                === null
                  ? "warning"
                  : "default"
              }
              subtitle={
                status.wallet_address
                  ? shortenLiveAddress(
                      status.wallet_address,
                      9,
                      8
                    )
                  : "Wallet LIVE non configurato"
              }
            />

            <LiveTradingMetric
              label="Esposizione aperta"
              value={`${formatLiveNumber(
                status.total_exposure_sol,
                6
              )} SOL`}
              subtitle={`${status.open_positions} posizioni aperte`}
            />

            <LiveTradingMetric
              label="PnL realizzato oggi"
              value={`${formatLiveNumber(
                status.realized_pnl_today_sol,
                6
              )} SOL`}
              tone={
                Number(
                  status.realized_pnl_today_sol
                ) > 0
                  ? "positive"
                  : Number(
                      status.realized_pnl_today_sol
                    ) < 0
                    ? "danger"
                    : "default"
              }
              subtitle={`${status.filled_orders_today}/${status.orders_today} ordini completati oggi`}
            />
          </div>
        )}

        <nav className="flex gap-2 overflow-x-auto rounded-2xl border border-slate-700 bg-slate-800/70 p-2">
          {TABS.map(([tab, label]) => (
            <button
              key={tab}
              type="button"
              onClick={() =>
                setActiveTab(tab)
              }
              className={`shrink-0 rounded-xl px-4 py-2.5 text-sm font-bold transition ${
                activeTab === tab
                  ? "bg-blue-600 text-white"
                  : "text-slate-400 hover:bg-slate-700 hover:text-white"
              }`}
            >
              {label}
            </button>
          ))}
        </nav>

        {activeTab === "control" && policy && (
  <div className="space-y-6">
    <LiveTradingWorkerPanel
      worker={status.worker}
    />

    <LiveTradingSection
      title="Stato sicurezza"
              description="Controlli che devono essere verificati prima di qualunque passaggio alla modalità LIVE."
            >
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-xl border border-slate-700 bg-slate-900/70 p-4">
                  <p className="text-sm text-slate-400">
                    Jupiter API
                  </p>
                  <p className={`mt-2 font-bold ${
                    status.jupiter_configured
                      ? "text-green-300"
                      : "text-red-300"
                  }`}>
                    {status.jupiter_configured
                      ? "Configurata"
                      : "Non configurata"}
                  </p>
                </div>

                <div className="rounded-xl border border-slate-700 bg-slate-900/70 p-4">
                  <p className="text-sm text-slate-400">
                    Esecuzione LIVE
                  </p>
                  <p className={`mt-2 font-bold ${
                    status.live_execution_configured
                      ? "text-green-300"
                      : "text-amber-300"
                  }`}>
                    {status.live_execution_configured
                      ? "Configurata"
                      : "Bloccata"}
                  </p>
                </div>

                <div className="rounded-xl border border-slate-700 bg-slate-900/70 p-4">
                  <p className="text-sm text-slate-400">
                    Kill switch
                  </p>
                  <p className={`mt-2 font-bold ${
                    policy.kill_switch
                      ? "text-red-300"
                      : "text-green-300"
                  }`}>
                    {policy.kill_switch
                      ? "ATTIVO"
                      : "Libero"}
                  </p>
                </div>

                <div className="rounded-xl border border-slate-700 bg-slate-900/70 p-4">
                  <p className="text-sm text-slate-400">
                    Errori consecutivi
                  </p>
                  <p className="mt-2 font-bold text-white">
                    {policy.consecutive_failures} / {policy.max_consecutive_failures}
                  </p>
                </div>
              </div>
            </LiveTradingSection>

            <LiveTradingSection
              title="Comandi di emergenza"
              description="Il kill switch interrompe lo stream automatico. Il rilascio richiede una conferma testuale esatta."
            >
              <div className="grid gap-5 lg:grid-cols-2">
                <div className="rounded-xl border border-red-800 bg-red-950/30 p-5">
                  <h3 className="font-bold text-red-200">
                    Arresto immediato
                  </h3>

                  <p className="mt-2 text-sm leading-6 text-red-300/70">
                    Può essere attivato in qualsiasi modalità. Non chiude le posizioni esistenti, ma blocca nuove esecuzioni.
                  </p>

                  <button
                    type="button"
                    onClick={handleKillSwitch}
                    disabled={
                      policy.kill_switch
                      || busyAction
                      === "kill-switch"
                    }
                    className="mt-4 rounded-xl bg-red-600 px-5 py-3 font-bold text-white transition hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {policy.kill_switch
                      ? "Kill switch già attivo"
                      : "Attiva kill switch"}
                  </button>
                </div>

                <form
                  onSubmit={
                    handleKillSwitchRelease
                  }
                  className="rounded-xl border border-slate-700 bg-slate-900/70 p-5"
                >
                  <h3 className="font-bold text-white">
                    Rilascio controllato
                  </h3>

                  <p className="mt-2 text-sm leading-6 text-slate-400">
                    Scrivi esattamente RELEASE LIVE TRADING per azzerare anche il contatore degli errori.
                  </p>

                  <input
                    type="text"
                    value={releaseConfirmation}
                    onChange={(event) =>
                      setReleaseConfirmation(
                        event.target.value
                      )
                    }
                    placeholder="RELEASE LIVE TRADING"
                    disabled={!policy.kill_switch}
                    className="mt-4 w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 font-mono text-white outline-none focus:border-blue-500 disabled:opacity-40"
                  />

                  <button
                    type="submit"
                    disabled={
                      !policy.kill_switch
                      || busyAction
                      === "release-kill-switch"
                      || releaseConfirmation
                      !== "RELEASE LIVE TRADING"
                    }
                    className="mt-3 rounded-xl border border-green-700 bg-green-950/50 px-5 py-3 font-bold text-green-300 transition hover:bg-green-900/60 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Rilascia kill switch
                  </button>
                </form>
              </div>
            </LiveTradingSection>

            <LiveTradingSection
              title="Esecuzione manuale controllata"
              description="Elabora un trade già presente nel database. In DRY_RUN usa una quotazione Jupiter reale senza firmare o inviare transazioni."
            >
              <form
                onSubmit={
                  handleManualExecution
                }
                className="flex flex-col gap-3 sm:flex-row"
              >
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={manualTradeId}
                  onChange={(event) =>
                    setManualTradeId(
                      event.target.value
                    )
                  }
                  placeholder="ID del trade sorgente"
                  className="min-w-0 flex-1 rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 text-white outline-none focus:border-blue-500"
                />

                <button
                  type="submit"
                  disabled={
                    busyAction
                    === "manual-execution"
                  }
                  className="rounded-xl bg-indigo-600 px-5 py-3 font-bold text-white transition hover:bg-indigo-500 disabled:opacity-50"
                >
                  {busyAction
                  === "manual-execution"
                    ? "Elaborazione..."
                    : "Esegui trade sorgente"}
                </button>
              </form>
            </LiveTradingSection>

            <LiveTradingSection
              title="Reset controllato DRY_RUN"
              description="Archivia il test attuale senza cancellare ordini o eventi e crea una nuova generazione con esposizione e limiti giornalieri puliti."
            >
              <LiveTradingDryRunReset
                key={`dry-run-${policy.dry_run_generation}-${policy.updated_at}`}
                policy={policy}
                status={status}
                resetting={
                  busyAction
                  === "dry-run-reset"
                }
                onReset={
                  handleDryRunReset
                }
              />
            </LiveTradingSection>

            <LiveTradingSection
              title="Policy completa"
              description="Configurazione definitiva del motore. Inizia da DRY_RUN e abilita lo stream soltanto dopo un test manuale riuscito."
            >
              <LiveTradingPolicyForm
                key={`${policy.updated_at}-${policy.mode}-${policy.kill_switch}`}
                policy={policy}
                saving={
                  busyAction === "policy"
                }
                onSave={handlePolicySave}
              />
            </LiveTradingSection>
          </div>
        )}

        {activeTab === "orders" && (
          <LiveTradingSection
            title="Ordini copy-trading"
            description="Storico completo di ricezione, quotazione, rifiuto, simulazione ed esecuzione."
          >
            <LiveTradingOrders
              orders={orders}
              filters={orderFilters}
              loading={loading}
              onFilterChange={(
                field,
                value
              ) =>
                setOrderFilters(
                  (current) => ({
                    ...current,
                    [field]: value,
                  })
                )
              }
              onRefresh={() =>
                loadDashboard(true)
              }
            />
          </LiveTradingSection>
        )}

        {activeTab === "positions" && (
          <LiveTradingSection
            title="Posizioni gestite"
            description="Le posizioni DRY_RUN e LIVE restano separate nel database per evitare contaminazioni tra simulazione e capitale reale."
          >
            <LiveTradingPositions
              positions={positions}
              filters={positionFilters}
              loading={loading}
              onFilterChange={(
                field,
                value
              ) =>
                setPositionFilters(
                  (current) => ({
                    ...current,
                    [field]: value,
                  })
                )
              }
              onRefresh={() =>
                loadDashboard(true)
              }
            />
          </LiveTradingSection>
        )}

        {activeTab === "events" && (
          <LiveTradingSection
            title="Audit ed eventi di sicurezza"
            description="Registro cronologico delle modifiche alla policy, ordini, errori e attivazioni del kill switch."
          >
            <LiveTradingEvents
              events={events}
              loading={loading}
              onRefresh={() =>
                loadDashboard(true)
              }
            />
          </LiveTradingSection>
        )}
      </main>
    </div>
  );
}


export default LiveTrading;