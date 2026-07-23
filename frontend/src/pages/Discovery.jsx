import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  getDiscoveredWallets,
  refreshDiscoveredWalletActivity,
  refreshDiscoveredWalletQuality,
  runControlledDiscoveryHydration,
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

  const [discoveredWallets, setDiscoveredWallets] = useState([]);
  const [result, setResult] = useState(null);
  const [historyItems, setHistoryItems] = useState(loadDiscoveryHistory);

  const [search, setSearch] = useState("");
  const [minimumScore, setMinimumScore] = useState(0);
  const [activityFilter, setActivityFilter] = useState("ALL");
  const [qualityFilter, setQualityFilter] = useState("ALL");
  const [eligibleOnly, setEligibleOnly] = useState(false);
  const [sortBy, setSortBy] = useState("ranking_score");

  const [loadingWallets, setLoadingWallets] = useState(true);
  const [running, setRunning] = useState(false);
  const [hydrating, setHydrating] = useState(false);
  const [refreshingActivity, setRefreshingActivity] = useState(false);
  const [refreshingQuality, setRefreshingQuality] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadDiscoveredWallets = useCallback(async () => {
    setLoadingWallets(true);
    try {
      const response = await getDiscoveredWallets(0, 500);
      setDiscoveredWallets(Array.isArray(response.data) ? response.data : []);
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
          String(wallet.hydration_status ?? "").toLowerCase().includes(normalizedSearch);
        const matchesScore = Number(wallet.smart_score ?? 0) >= Number(minimumScore || 0);
        const matchesActivity =
          activityFilter === "ALL" || wallet.activity_classification === activityFilter;
        const matchesQuality =
          qualityFilter === "ALL" || wallet.quality_classification === qualityFilter;
        const matchesEligibility = !eligibleOnly || Boolean(wallet.eligible);
        return matchesSearch && matchesScore && matchesActivity && matchesQuality && matchesEligibility;
      })
      .sort((first, second) => {
        if (sortBy === "last_swap_at") {
          return new Date(second.last_swap_at ?? 0) - new Date(first.last_swap_at ?? 0);
        }
        return Number(second[sortBy] ?? 0) - Number(first[sortBy] ?? 0);
      });
  }, [
    discoveredWallets,
    search,
    minimumScore,
    activityFilter,
    qualityFilter,
    eligibleOnly,
    sortBy,
  ]);

  const resultRanking = useMemo(
    () => (Array.isArray(result?.ranking) ? result.ranking : []),
    [result]
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
            <h1 className="text-3xl font-bold">Wallet Quality & Execution Suitability</h1>
            <p className="mt-2 max-w-3xl text-slate-400">
              Valida se l'attività recente è realmente copiabile: dust, size, equilibrio
              BUY/SELL, concentrazione token e cicli completi diventano filtri obbligatori.
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
          Attività e qualità vengono ricalcolate esclusivamente dai trade salvati.
          L'idratazione resta manuale e limitata dal budget: una richiesta Helius per wallet.
          Nessuna azione abilita stream o LIVE, avvia worker, applica wallet o crea generazioni.
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

        <section className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
          <StatCard label="Wallet scoperti" value={summary.total} tone="text-blue-300" />
          <StatCard label="Idonei finali" value={summary.eligible} tone="text-green-300" />
          <StatCard label="Copiabili" value={summary.copyable} tone="text-emerald-300" />
          <StatCard label="Osservazione" value={summary.observation} tone="text-amber-300" />
          <StatCard label="Sospetti" value={summary.suspicious} tone="text-fuchsia-300" />
          <StatCard label="Non copiabili" value={summary.notCopyable} tone="text-red-300" />
        </section>

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
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-7">
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
                value={sortBy}
                onChange={(event) => setSortBy(event.target.value)}
                className="rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
              >
                <option value="ranking_score">Ranking Score</option>
                <option value="smart_score">Smart Score</option>
                <option value="activity_score">Activity Score</option>
                <option value="quality_score">Quality Score</option>
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
            <table className="w-full min-w-[2500px] text-sm">
              <thead className="bg-slate-900 text-slate-400">
                <tr>
                  <th className="p-4 text-left">Wallet</th>
                  <th className="p-4">Hydration</th>
                  <th className="p-4">Import</th>
                  <th className="p-4">Ranking</th>
                  <th className="p-4">Smart</th>
                  <th className="p-4">Activity</th>
                  <th className="p-4">Classe attività</th>
                  <th className="p-4">Quality</th>
                  <th className="p-4">Suitability</th>
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
                    <td colSpan="24" className="p-10 text-center text-slate-500">
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
