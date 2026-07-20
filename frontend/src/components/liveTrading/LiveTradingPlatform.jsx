import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  applyLiveTradingWalletRanking,
  armLiveTrading,
  disarmLiveTrading,
  downloadLiveTradingAnalyticsCsv,
  getLivePlatformConfig,
  getLiveTokenSafety,
  getLiveTradingAnalytics,
  getLiveTradingReadiness,
  getLiveWalletRanking,
  refreshLiveTokenSafety,
  refreshLiveWalletRanking,
  updateLivePlatformConfig,
} from "../../services/liveTradingApi";
import {
  formatLiveDate,
  formatLiveNumber,
  parseLiveApiError,
  shortenLiveAddress,
} from "./liveTradingFormatters";
import LiveTradingMetric from "./LiveTradingMetric";
import LiveTradingSection from "./LiveTradingSection";


const BOOLEAN_FIELDS = [
  "auto_wallet_selection_enabled",
  "token_safety_enabled",
  "token_safety_fail_closed",
  "token_allowlist_mode",
  "require_rugcheck_pass",
  "reject_honeypot",
  "require_disabled_mint_authority",
  "require_disabled_freeze_authority",
];

const NUMBER_FIELDS = [
  "analytics_starting_equity_sol",
  "max_source_wallets",
  "min_wallet_smart_score",
  "min_token_liquidity_usd",
  "min_token_market_cap_usd",
  "min_token_volume_24h_usd",
  "max_top_holder_percent",
  "max_token_risk_score",
  "safety_snapshot_max_age_seconds",
  "live_arm_ttl_minutes",
];


function TextListField({
  label,
  value,
  onChange,
  placeholder,
}) {
  return (
    <label className="block">
      <span className="text-sm font-bold text-slate-300">
        {label}
      </span>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        rows="4"
        className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 font-mono text-xs text-white outline-none transition focus:border-blue-500"
      />
      <span className="mt-1 block text-xs text-slate-500">
        Un mint per riga oppure separato da virgole.
      </span>
    </label>
  );
}


function ToggleField({
  label,
  description,
  checked,
  onChange,
}) {
  return (
    <label className="flex cursor-pointer gap-3 rounded-xl border border-slate-700 bg-slate-900/70 p-4">
      <input
        type="checkbox"
        checked={Boolean(checked)}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-1 h-4 w-4 accent-blue-600"
      />
      <span>
        <span className="block font-bold text-white">
          {label}
        </span>
        <span className="mt-1 block text-xs leading-5 text-slate-400">
          {description}
        </span>
      </span>
    </label>
  );
}


function NumberField({
  label,
  value,
  onChange,
  min = "0",
  max,
  step = "0.01",
}) {
  return (
    <label className="block">
      <span className="text-sm font-bold text-slate-300">
        {label}
      </span>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 text-white outline-none transition focus:border-blue-500"
      />
    </label>
  );
}


function parseMintList(value) {
  return String(value ?? "")
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}


function configToForm(config) {
  if (!config) {
    return null;
  }

  const result = {};
  BOOLEAN_FIELDS.forEach((field) => {
    result[field] = Boolean(config[field]);
  });
  NUMBER_FIELDS.forEach((field) => {
    result[field] = String(config[field] ?? "");
  });
  result.token_allowlist = (config.token_allowlist ?? []).join("\n");
  result.token_blocklist = (config.token_blocklist ?? []).join("\n");
  return result;
}


function MetricGrid({ analytics }) {
  const summary = analytics?.summary;
  if (!summary) {
    return null;
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <LiveTradingMetric
        label="PnL realizzato"
        value={`${formatLiveNumber(summary.net_realized_pnl_sol, 6)} SOL`}
        tone={summary.net_realized_pnl_sol > 0 ? "positive" : summary.net_realized_pnl_sol < 0 ? "danger" : "default"}
        subtitle={`ROI ${formatLiveNumber(summary.roi_percent, 2)}%`}
      />
      <LiveTradingMetric
        label="Win rate"
        value={`${formatLiveNumber(summary.win_rate_percent, 2)}%`}
        subtitle={`${summary.winning_trades} vinte · ${summary.losing_trades} perse`}
      />
      <LiveTradingMetric
        label="Profit factor"
        value={summary.profit_factor === null ? "N/D" : formatLiveNumber(summary.profit_factor, 3)}
        subtitle={`${summary.sell_orders} SELL completati`}
      />
      <LiveTradingMetric
        label="Drawdown massimo"
        value={`${formatLiveNumber(summary.max_drawdown_sol, 6)} SOL`}
        tone={summary.max_drawdown_sol > 0 ? "warning" : "default"}
        subtitle={`${formatLiveNumber(summary.max_drawdown_percent, 2)}%`}
      />
    </div>
  );
}


function LiveTradingPlatform({
  accessKey,
  activeGeneration,
  mode = "DRY_RUN",
}) {
  const [config, setConfig] = useState(null);
  const [configForm, setConfigForm] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [ranking, setRanking] = useState([]);
  const [safety, setSafety] = useState([]);
  const [readiness, setReadiness] = useState(null);
  const [tokenMint, setTokenMint] = useState("");
  const [armConfirmation, setArmConfirmation] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadPlatform = useCallback(async (showLoader = true) => {
    if (!accessKey) {
      return;
    }

    if (showLoader) {
      setLoading(true);
    }
    setError("");

    try {
      const [
        configResponse,
        analyticsResponse,
        rankingResponse,
        safetyResponse,
        readinessResponse,
      ] = await Promise.all([
        getLivePlatformConfig(accessKey),
        getLiveTradingAnalytics(accessKey, {
          mode: mode === "LIVE" ? "LIVE" : "DRY_RUN",
          generation: mode === "LIVE" ? 1 : activeGeneration,
          days: 30,
        }),
        getLiveWalletRanking(accessKey),
        getLiveTokenSafety(accessKey),
        getLiveTradingReadiness(accessKey),
      ]);

      setConfig(configResponse.data);
      setConfigForm(configToForm(configResponse.data));
      setAnalytics(analyticsResponse.data);
      setRanking(rankingResponse.data.ranking ?? []);
      setSafety(safetyResponse.data.snapshots ?? []);
      setReadiness(readinessResponse.data);
    } catch (requestError) {
      setError(parseLiveApiError(requestError));
    } finally {
      if (showLoader) {
        setLoading(false);
      }
    }
  }, [accessKey, activeGeneration, mode]);

  useEffect(() => {
    const timeoutId = window.setTimeout(
      () => {
        loadPlatform(true);
      },
      0
    );

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [loadPlatform]);

  const chartData = useMemo(
    () => (analytics?.daily ?? []).map((row) => ({
      ...row,
      label: String(row.date).slice(5),
    })),
    [analytics]
  );

  async function runAction(name, action, successMessage) {
    setBusy(name);
    setError("");
    setMessage("");

    try {
      await action();
      setMessage(successMessage);
      await loadPlatform(false);
      return true;
    } catch (requestError) {
      setError(parseLiveApiError(requestError));
      return false;
    } finally {
      setBusy("");
    }
  }

  function updateForm(field, value) {
    setConfigForm((current) => ({
      ...current,
      [field]: value,
    }));
  }

  async function saveConfig(event) {
    event.preventDefault();
    if (!configForm) {
      return;
    }

    const payload = {};
    BOOLEAN_FIELDS.forEach((field) => {
      payload[field] = Boolean(configForm[field]);
    });
    NUMBER_FIELDS.forEach((field) => {
      payload[field] = Number(configForm[field]);
    });
    payload.token_allowlist = parseMintList(configForm.token_allowlist);
    payload.token_blocklist = parseMintList(configForm.token_blocklist);

    await runAction(
      "config",
      () => updateLivePlatformConfig(accessKey, payload),
      "Configurazione piattaforma salvata."
    );
  }

  async function handleRefreshRanking() {
    await runAction(
      "ranking-refresh",
      () => refreshLiveWalletRanking(accessKey),
      "Ranking wallet aggiornato."
    );
  }

  async function handleApplyRanking() {
    const confirmed = window.confirm(
      "Sostituire i wallet sorgente della policy con quelli idonei nel ranking?"
    );
    if (!confirmed) {
      return;
    }

    await runAction(
      "ranking-apply",
      () => applyLiveTradingWalletRanking(accessKey, {
        confirmation: "APPLY SMART WALLETS",
        limit: Number(config?.max_source_wallets ?? 20),
      }),
      "Wallet sorgente aggiornati dal ranking."
    );
  }

  async function handleSafetyScan(event) {
    event.preventDefault();
    const mint = tokenMint.trim();
    if (!mint) {
      setError("Inserisci il mint del token.");
      return;
    }

    const completed = await runAction(
      "safety-scan",
      () => refreshLiveTokenSafety(accessKey, mint),
      "Controllo di sicurezza token completato."
    );
    if (completed) {
      setTokenMint("");
    }
  }

  async function handleExport() {
    setBusy("csv");
    setError("");
    try {
      const response = await downloadLiveTradingAnalyticsCsv(accessKey, {
        mode: mode === "LIVE" ? "LIVE" : "DRY_RUN",
        generation: mode === "LIVE" ? 1 : activeGeneration,
        days: 30,
      });
      const url = window.URL.createObjectURL(response.data);
      const link = document.createElement("a");
      const disposition = response.headers["content-disposition"] ?? "";
      const match = disposition.match(/filename="?([^";]+)"?/i);
      link.href = url;
      link.download = match?.[1] ?? "smartmoney-analytics.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      setMessage("CSV analytics esportato.");
    } catch (requestError) {
      setError(parseLiveApiError(requestError));
    } finally {
      setBusy("");
    }
  }

  async function handleArm(event) {
    event.preventDefault();
    const armed = await runAction(
      "arm",
      () => armLiveTrading(accessKey, armConfirmation),
      "Finestra LIVE armata."
    );
    if (armed) {
      setArmConfirmation("");
    }
  }

  async function handleDisarm() {
    await runAction(
      "disarm",
      () => disarmLiveTrading(accessKey),
      "Esecuzione LIVE disarmata."
    );
  }

  if (loading && !config) {
    return (
      <div className="rounded-2xl border border-slate-700 bg-slate-800/70 p-8 text-center text-slate-400">
        Caricamento piattaforma analytics e sicurezza...
      </div>
    );
  }

  return (
    <div className="space-y-6">
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

      <LiveTradingSection
        title="Portfolio Analytics"
        description="Equity curve, PnL, ROI, win rate, profit factor e drawdown della generazione selezionata."
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-400">
            {analytics
              ? `${analytics.mode} · Generazione #${analytics.generation} · ultimi ${analytics.window.days} giorni`
              : "Analytics non disponibili"}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => loadPlatform(true)}
              disabled={loading}
              className="rounded-xl border border-slate-600 bg-slate-900 px-4 py-2 text-sm font-bold text-slate-300 disabled:opacity-50"
            >
              Aggiorna
            </button>
            <button
              type="button"
              onClick={handleExport}
              disabled={!analytics || busy === "csv"}
              className="rounded-xl border border-green-700 bg-green-950/50 px-4 py-2 text-sm font-bold text-green-300 disabled:opacity-50"
            >
              Esporta CSV
            </button>
          </div>
        </div>

        <div className="mt-5">
          <MetricGrid analytics={analytics} />
        </div>

        <div className="mt-6 h-80 rounded-xl border border-slate-700 bg-slate-950/70 p-3">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="label" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" domain={["auto", "auto"]} />
              <Tooltip
                contentStyle={{
                  background: "#0f172a",
                  border: "1px solid #475569",
                  borderRadius: "12px",
                }}
              />
              <Line
                type="monotone"
                dataKey="equity_sol"
                name="Equity SOL"
                stroke="#60a5fa"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="cumulative_pnl_sol"
                name="PnL cumulativo SOL"
                stroke="#34d399"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="mt-6 grid gap-5 xl:grid-cols-2">
          <div className="overflow-x-auto rounded-xl border border-slate-700">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-900 text-left text-slate-400">
                <tr>
                  <th className="px-4 py-3">Wallet</th>
                  <th className="px-4 py-3">Ordini</th>
                  <th className="px-4 py-3">Win rate</th>
                  <th className="px-4 py-3">PnL</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700">
                {(analytics?.wallet_performance ?? []).slice(0, 10).map((row) => (
                  <tr key={row.source_wallet}>
                    <td className="px-4 py-3 font-mono text-xs text-white">
                      {shortenLiveAddress(row.source_wallet, 7, 6)}
                    </td>
                    <td className="px-4 py-3 text-slate-300">{row.orders}</td>
                    <td className="px-4 py-3 text-slate-300">
                      {formatLiveNumber(row.win_rate_percent, 2)}%
                    </td>
                    <td className={`px-4 py-3 font-bold ${row.realized_pnl_sol >= 0 ? "text-green-300" : "text-red-300"}`}>
                      {formatLiveNumber(row.realized_pnl_sol, 6)} SOL
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-700">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-900 text-left text-slate-400">
                <tr>
                  <th className="px-4 py-3">Token</th>
                  <th className="px-4 py-3">Ordini</th>
                  <th className="px-4 py-3">ROI</th>
                  <th className="px-4 py-3">PnL</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700">
                {(analytics?.token_performance ?? []).slice(0, 10).map((row) => (
                  <tr key={row.token_mint}>
                    <td className="px-4 py-3 font-mono text-xs text-white">
                      {shortenLiveAddress(row.token_mint, 7, 6)}
                    </td>
                    <td className="px-4 py-3 text-slate-300">{row.orders}</td>
                    <td className="px-4 py-3 text-slate-300">
                      {formatLiveNumber(row.roi_percent, 2)}%
                    </td>
                    <td className={`px-4 py-3 font-bold ${row.realized_pnl_sol >= 0 ? "text-green-300" : "text-red-300"}`}>
                      {formatLiveNumber(row.realized_pnl_sol, 6)} SOL
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </LiveTradingSection>

      <LiveTradingSection
        title="Smart Wallet Ranking"
        description="Combina Smart Score storico e performance copy-trading per ordinare fino a 50 wallet sorgente."
      >
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={handleRefreshRanking}
            disabled={busy === "ranking-refresh"}
            className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50"
          >
            Ricalcola ranking
          </button>
          <button
            type="button"
            onClick={handleApplyRanking}
            disabled={busy === "ranking-apply" || !config?.auto_wallet_selection_enabled || !ranking.some((row) => row.eligible)}
            className="rounded-xl border border-amber-700 bg-amber-950/50 px-4 py-2.5 text-sm font-bold text-amber-300 disabled:opacity-50"
          >
            Applica wallet idonei
          </button>
        </div>

        <div className="mt-5 overflow-x-auto rounded-xl border border-slate-700">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-900 text-left text-slate-400">
              <tr>
                <th className="px-4 py-3">#</th>
                <th className="px-4 py-3">Wallet</th>
                <th className="px-4 py-3">Smart Score</th>
                <th className="px-4 py-3">Win rate</th>
                <th className="px-4 py-3">ROI</th>
                <th className="px-4 py-3">Campione</th>
                <th className="px-4 py-3">Stato</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700">
              {ranking.map((row) => (
                <tr key={row.wallet_address}>
                  <td className="px-4 py-3 text-slate-400">{row.rank}</td>
                  <td className="px-4 py-3 font-mono text-xs text-white">
                    {shortenLiveAddress(row.wallet_address, 8, 7)}
                  </td>
                  <td className="px-4 py-3 font-bold text-blue-300">
                    {formatLiveNumber(row.smart_score, 2)}
                  </td>
                  <td className="px-4 py-3 text-slate-300">
                    {formatLiveNumber(row.win_rate_percent, 2)}%
                  </td>
                  <td className="px-4 py-3 text-slate-300">
                    {formatLiveNumber(row.roi_percent, 2)}%
                  </td>
                  <td className="px-4 py-3 text-slate-300">{row.closed_trades}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${row.eligible ? "bg-green-950 text-green-300" : "bg-slate-800 text-slate-400"}`}>
                      {row.eligible ? "IDONEO" : "ESCLUSO"}
                    </span>
                  </td>
                </tr>
              ))}
              {!ranking.length && (
                <tr>
                  <td colSpan="7" className="px-4 py-8 text-center text-slate-500">
                    Nessun wallet disponibile per il ranking.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </LiveTradingSection>

      <LiveTradingSection
        title="Token Safety Engine"
        description="Controlla liquidità, market cap, volume, concentrazione holder, autorità mint/freeze, vendibilità Jupiter e RugCheck facoltativo."
      >
        <form onSubmit={handleSafetyScan} className="flex flex-col gap-3 sm:flex-row">
          <input
            type="text"
            value={tokenMint}
            onChange={(event) => setTokenMint(event.target.value)}
            placeholder="Mint token Solana"
            className="min-w-0 flex-1 rounded-xl border border-slate-600 bg-slate-950 px-4 py-3 font-mono text-sm text-white outline-none focus:border-blue-500"
          />
          <button
            type="submit"
            disabled={busy === "safety-scan" || !tokenMint.trim()}
            className="rounded-xl bg-indigo-600 px-5 py-3 font-bold text-white disabled:opacity-50"
          >
            Analizza token
          </button>
        </form>

        <div className="mt-5 overflow-x-auto rounded-xl border border-slate-700">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-900 text-left text-slate-400">
              <tr>
                <th className="px-4 py-3">Token</th>
                <th className="px-4 py-3">Liquidità</th>
                <th className="px-4 py-3">Market cap</th>
                <th className="px-4 py-3">Volume 24h</th>
                <th className="px-4 py-3">Top holder</th>
                <th className="px-4 py-3">Rischio</th>
                <th className="px-4 py-3">Vendibilità</th>
                <th className="px-4 py-3">Aggiornato</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700">
              {safety.map((row) => (
                <tr key={row.token_mint}>
                  <td className="px-4 py-3 font-mono text-xs text-white">
                    {shortenLiveAddress(row.token_mint, 7, 6)}
                  </td>
                  <td className="px-4 py-3 text-slate-300">${formatLiveNumber(row.liquidity_usd, 0)}</td>
                  <td className="px-4 py-3 text-slate-300">${formatLiveNumber(row.market_cap_usd, 0)}</td>
                  <td className="px-4 py-3 text-slate-300">${formatLiveNumber(row.volume_24h_usd, 0)}</td>
                  <td className="px-4 py-3 text-slate-300">{formatLiveNumber(row.top_holder_percent, 2)}%</td>
                  <td className={`px-4 py-3 font-bold ${row.risk_score <= 30 ? "text-green-300" : row.risk_score <= 60 ? "text-amber-300" : "text-red-300"}`}>
                    {row.risk_score}/100
                  </td>
                  <td className={`px-4 py-3 font-bold ${row.honeypot ? "text-red-300" : "text-green-300"}`}>
                    {row.honeypot ? "BLOCCATA" : "OK"}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-400">{formatLiveDate(row.fetched_at)}</td>
                </tr>
              ))}
              {!safety.length && (
                <tr>
                  <td colSpan="8" className="px-4 py-8 text-center text-slate-500">
                    Nessuna analisi token ancora salvata.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </LiveTradingSection>

      {configForm && (
        <LiveTradingSection
          title="Filtri e configurazione piattaforma"
          description="I filtri token sono applicati ai nuovi BUY; i SELL restano sempre consentiti per poter uscire dalle posizioni."
        >
          <form onSubmit={saveConfig} className="space-y-6">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <NumberField label="Equity iniziale analytics (SOL)" value={configForm.analytics_starting_equity_sol} onChange={(value) => updateForm("analytics_starting_equity_sol", value)} min="0.000001" step="0.01" />
              <NumberField label="Wallet sorgente massimi" value={configForm.max_source_wallets} onChange={(value) => updateForm("max_source_wallets", value)} min="1" max="50" step="1" />
              <NumberField label="Smart Score minimo" value={configForm.min_wallet_smart_score} onChange={(value) => updateForm("min_wallet_smart_score", value)} max="100" step="0.1" />
              <NumberField label="Durata armamento LIVE (min)" value={configForm.live_arm_ttl_minutes} onChange={(value) => updateForm("live_arm_ttl_minutes", value)} min="1" max="60" step="1" />
              <NumberField label="Liquidità minima USD" value={configForm.min_token_liquidity_usd} onChange={(value) => updateForm("min_token_liquidity_usd", value)} step="100" />
              <NumberField label="Market cap minimo USD" value={configForm.min_token_market_cap_usd} onChange={(value) => updateForm("min_token_market_cap_usd", value)} step="1000" />
              <NumberField label="Volume 24h minimo USD" value={configForm.min_token_volume_24h_usd} onChange={(value) => updateForm("min_token_volume_24h_usd", value)} step="100" />
              <NumberField label="Top holder massimo %" value={configForm.max_top_holder_percent} onChange={(value) => updateForm("max_top_holder_percent", value)} max="100" step="0.1" />
              <NumberField label="Risk score massimo" value={configForm.max_token_risk_score} onChange={(value) => updateForm("max_token_risk_score", value)} max="100" step="1" />
              <NumberField label="Validità snapshot (secondi)" value={configForm.safety_snapshot_max_age_seconds} onChange={(value) => updateForm("safety_snapshot_max_age_seconds", value)} min="30" max="86400" step="30" />
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <ToggleField label="Selezione wallet automatica" description="Consente di applicare il ranking alla policy solo tramite conferma esplicita." checked={configForm.auto_wallet_selection_enabled} onChange={(value) => updateForm("auto_wallet_selection_enabled", value)} />
              <ToggleField label="Token safety attivo" description="Analizza ogni nuovo token prima di un BUY." checked={configForm.token_safety_enabled} onChange={(value) => updateForm("token_safety_enabled", value)} />
              <ToggleField label="Fail closed" description="Blocca il BUY quando non è possibile completare i controlli." checked={configForm.token_safety_fail_closed} onChange={(value) => updateForm("token_safety_fail_closed", value)} />
              <ToggleField label="Modalità allowlist" description="Permette BUY soltanto dei mint presenti nell'allowlist." checked={configForm.token_allowlist_mode} onChange={(value) => updateForm("token_allowlist_mode", value)} />
              <ToggleField label="Blocca honeypot" description="Rifiuta token senza una quotazione di vendita Jupiter valida." checked={configForm.reject_honeypot} onChange={(value) => updateForm("reject_honeypot", value)} />
              <ToggleField label="Richiedi RugCheck PASS" description="Da attivare soltanto dopo avere configurato il servizio esterno." checked={configForm.require_rugcheck_pass} onChange={(value) => updateForm("require_rugcheck_pass", value)} />
              <ToggleField label="Mint authority disabilitata" description="Blocca token per cui è ancora possibile creare nuova supply." checked={configForm.require_disabled_mint_authority} onChange={(value) => updateForm("require_disabled_mint_authority", value)} />
              <ToggleField label="Freeze authority disabilitata" description="Blocca token i cui account possono ancora essere congelati." checked={configForm.require_disabled_freeze_authority} onChange={(value) => updateForm("require_disabled_freeze_authority", value)} />
            </div>

            <div className="grid gap-5 lg:grid-cols-2">
              <TextListField label="Token allowlist" value={configForm.token_allowlist} onChange={(value) => updateForm("token_allowlist", value)} placeholder="Mint autorizzati" />
              <TextListField label="Token blocklist" value={configForm.token_blocklist} onChange={(value) => updateForm("token_blocklist", value)} placeholder="Mint bloccati" />
            </div>

            <button
              type="submit"
              disabled={busy === "config"}
              className="rounded-xl bg-blue-600 px-5 py-3 font-bold text-white disabled:opacity-50"
            >
              Salva configurazione completa
            </button>
          </form>
        </LiveTradingSection>
      )}

      <LiveTradingSection
        title="LIVE Readiness e armamento"
        description="La modalità LIVE richiede policy LIVE, kill switch libero, signer coerente, saldo sufficiente, sicurezza fail-closed e simulazione pre-invio. L'armamento scade automaticamente."
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(readiness?.checks ?? []).map((check) => (
            <div key={check.code} className={`rounded-xl border p-4 ${check.passed ? "border-green-800 bg-green-950/30" : check.blocking ? "border-red-800 bg-red-950/30" : "border-amber-800 bg-amber-950/30"}`}>
              <p className={`font-bold ${check.passed ? "text-green-300" : "text-red-300"}`}>
                {check.passed ? "✓" : "✕"} {check.label}
              </p>
              <p className="mt-2 text-xs leading-5 text-slate-400">{check.message}</p>
            </div>
          ))}
        </div>

        <div className="mt-5 rounded-xl border border-red-800 bg-red-950/30 p-5">
          <p className="font-bold text-red-200">
            Stato: {readiness?.armed ? "LIVE ARMATO" : readiness?.ready ? "PRONTO MA NON ARMATO" : "BLOCCATO"}
          </p>
          <p className="mt-2 text-sm text-red-300/70">
            {readiness?.armed_until
              ? `Scadenza: ${formatLiveDate(readiness.armed_until)}`
              : "Nessuna finestra LIVE attiva. Questa funzione non modifica né mostra la chiave privata."}
          </p>

          <div className="mt-4 flex flex-col gap-3 lg:flex-row">
            <form onSubmit={handleArm} className="flex min-w-0 flex-1 flex-col gap-3 sm:flex-row">
              <input
                type="text"
                value={armConfirmation}
                onChange={(event) => setArmConfirmation(event.target.value)}
                placeholder="ARM LIVE FOR 15 MINUTES"
                className="min-w-0 flex-1 rounded-xl border border-red-800 bg-slate-950 px-4 py-3 font-mono text-sm text-white outline-none"
              />
              <button
                type="submit"
                disabled={!readiness?.ready || readiness?.armed || armConfirmation !== "ARM LIVE FOR 15 MINUTES" || busy === "arm"}
                className="rounded-xl bg-red-600 px-5 py-3 font-bold text-white disabled:cursor-not-allowed disabled:opacity-40"
              >
                Arma LIVE
              </button>
            </form>
            <button
              type="button"
              onClick={handleDisarm}
              disabled={!readiness?.armed || busy === "disarm"}
              className="rounded-xl border border-green-700 bg-green-950/50 px-5 py-3 font-bold text-green-300 disabled:opacity-40"
            >
              Disarma immediatamente
            </button>
          </div>
        </div>
      </LiveTradingSection>
    </div>
  );
}


export default LiveTradingPlatform;
