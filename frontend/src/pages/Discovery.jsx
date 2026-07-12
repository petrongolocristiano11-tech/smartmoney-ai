import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Link } from "react-router-dom";

import {
  getDiscoveredWallets,
  runDiscovery,
  runSmartDiscovery,
} from "../services/api";

const DISCOVERY_HISTORY_KEY =
  "smartmoney-discovery-history";

function shortenAddress(address, start = 10, end = 8) {
  if (!address) {
    return "-";
  }

  if (address.length <= start + end + 3) {
    return address;
  }

  return `${address.slice(0, start)}...${address.slice(-end)}`;
}

function formatNumber(value, digits = 2) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "0";
  }

  return number.toLocaleString("it-IT", {
    maximumFractionDigits: digits,
  });
}

function loadDiscoveryHistory() {
  try {
    const storedValue = window.localStorage.getItem(
      DISCOVERY_HISTORY_KEY
    );

    if (!storedValue) {
      return [];
    }

    const parsedValue = JSON.parse(storedValue);

    return Array.isArray(parsedValue) ? parsedValue : [];
  } catch (error) {
    console.error(
      "Errore caricamento cronologia discovery:",
      error
    );

    return [];
  }
}

function getResultWalletAddress(wallet) {
  return wallet?.wallet ?? wallet?.wallet_address ?? "";
}

function Discovery() {
  const [mode, setMode] = useState("FULL");
  const [seedWallet, setSeedWallet] = useState("");

  const [maxTokens, setMaxTokens] = useState(3);
  const [maxWalletsPerToken, setMaxWalletsPerToken] =
    useState(3);

  const [maxDepth, setMaxDepth] = useState(2);
  const [
    maxTokensPerWallet,
    setMaxTokensPerWallet,
  ] = useState(5);
  const [
    smartMaxWalletsPerToken,
    setSmartMaxWalletsPerToken,
  ] = useState(5);
  const [minSmartScore, setMinSmartScore] =
    useState(60);

  const [discoveredWallets, setDiscoveredWallets] =
    useState([]);
  const [result, setResult] = useState(null);
  const [historyItems, setHistoryItems] = useState(
    loadDiscoveryHistory
  );

  const [search, setSearch] = useState("");
  const [minimumScore, setMinimumScore] = useState(0);

  const [loadingWallets, setLoadingWallets] =
    useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadDiscoveredWallets = useCallback(async () => {
    setLoadingWallets(true);

    try {
      const response = await getDiscoveredWallets(0, 250);

      setDiscoveredWallets(
        Array.isArray(response.data) ? response.data : []
      );
    } catch (requestError) {
      console.error(
        "Errore caricamento wallet scoperti:",
        requestError
      );

      setError(
        "Impossibile caricare i wallet scoperti dal backend."
      );
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
      console.error(
        "Errore salvataggio cronologia:",
        storageError
      );
    }
  }, [historyItems]);

  const filteredWallets = useMemo(() => {
    const normalizedSearch = search
      .trim()
      .toLowerCase();

    return [...discoveredWallets]
      .filter((wallet) => {
        const matchesScore =
          Number(wallet.smart_score ?? 0) >=
          Number(minimumScore || 0);

        const matchesSearch =
          !normalizedSearch ||
          (wallet.wallet_address ?? "")
            .toLowerCase()
            .includes(normalizedSearch) ||
          (wallet.status ?? "")
            .toLowerCase()
            .includes(normalizedSearch) ||
          (wallet.discovered_from_token ?? "")
            .toLowerCase()
            .includes(normalizedSearch);

        return matchesScore && matchesSearch;
      })
      .sort(
        (firstWallet, secondWallet) =>
          Number(secondWallet.smart_score ?? 0) -
          Number(firstWallet.smart_score ?? 0)
      );
  }, [discoveredWallets, search, minimumScore]);

  const resultRanking = useMemo(() => {
    const ranking = result?.ranking;

    return Array.isArray(ranking) ? ranking : [];
  }, [result]);

  const bestDiscoveredScore = useMemo(() => {
    if (discoveredWallets.length === 0) {
      return "-";
    }

    return formatNumber(
      Math.max(
        ...discoveredWallets.map(
          (wallet) =>
            Number(wallet.smart_score) || 0
        )
      )
    );
  }, [discoveredWallets]);

  function addHistoryItem(responseData) {
    const newItem = {
      id:
        globalThis.crypto?.randomUUID?.() ??
        `${Date.now()}-${Math.random()}`,
      mode,
      seed_wallet: seedWallet.trim(),
      created_at: new Date().toISOString(),
      wallets_found:
        mode === "SMART"
          ? responseData.smart_wallets_found ?? 0
          : responseData.wallets_discovered ?? 0,
      wallets_analyzed:
        responseData.wallets_analyzed ??
        responseData.ranking?.length ??
        0,
      tokens_processed:
        responseData.tokens_processed ?? null,
      max_depth:
        responseData.max_depth ?? null,
    };

    setHistoryItems((currentItems) => [
      newItem,
      ...currentItems,
    ].slice(0, 20));
  }

  async function handleRunDiscovery() {
    const normalizedWallet = seedWallet.trim();

    if (!normalizedWallet) {
      alert("Inserisci il seed wallet");
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

      const walletsFound =
        mode === "SMART"
          ? response.data.smart_wallets_found ?? 0
          : response.data.wallets_discovered ?? 0;

      setMessage(
        `Discovery completata: ${walletsFound} wallet trovati`
      );

      await loadDiscoveredWallets();
    } catch (requestError) {
      console.error(
        "Errore durante la discovery:",
        requestError
      );

      const backendMessage =
        requestError.response?.data?.detail;

      setError(
        typeof backendMessage === "string"
          ? backendMessage
          : "Discovery non completata. Controlla il backend e il seed wallet."
      );
    } finally {
      setRunning(false);
    }
  }

  function clearHistory() {
    if (historyItems.length === 0) {
      return;
    }

    const confirmed = window.confirm(
      "Vuoi cancellare tutta la cronologia delle discovery?"
    );

    if (confirmed) {
      setHistoryItems([]);
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 p-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-3xl font-bold">
              Discovery Center
            </h1>

            <p className="mt-2 text-slate-400">
              Trova e analizza nuovi wallet partendo da
              un seed wallet
            </p>
          </div>

          <button
            type="button"
            onClick={loadDiscoveredWallets}
            disabled={loadingWallets}
            className="w-fit rounded-lg border border-blue-700 bg-blue-900/40 px-4 py-2 text-sm font-semibold text-blue-300 hover:bg-blue-900/70 disabled:opacity-50"
          >
            {loadingWallets
              ? "Aggiornamento..."
              : "Aggiorna wallet"}
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-7xl p-4 sm:p-8">
        {error && (
          <div className="mb-6 rounded-lg border border-red-700 bg-red-900/30 p-4 text-red-300">
            {error}
          </div>
        )}

        {message && (
          <div className="mb-6 rounded-lg border border-green-700 bg-green-900/30 p-4 text-green-300">
            {message}
          </div>
        )}

        <section className="mb-8 overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="border-b border-slate-700 p-5">
            <h2 className="text-xl font-bold">
              Nuova discovery
            </h2>

            <p className="mt-1 text-sm text-slate-400">
              Full Discovery è più rapida. Smart Discovery
              esplora il network a più livelli.
            </p>
          </div>

          <div className="p-5">
            <div className="mb-5 grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setMode("FULL")}
                className={`rounded-lg border px-4 py-3 font-semibold ${
                  mode === "FULL"
                    ? "border-blue-600 bg-blue-600 text-white"
                    : "border-slate-600 bg-slate-900 text-slate-300"
                }`}
              >
                Full Discovery
              </button>

              <button
                type="button"
                onClick={() => setMode("SMART")}
                className={`rounded-lg border px-4 py-3 font-semibold ${
                  mode === "SMART"
                    ? "border-purple-600 bg-purple-600 text-white"
                    : "border-slate-600 bg-slate-900 text-slate-300"
                }`}
              >
                Smart Discovery
              </button>
            </div>

            <input
              type="text"
              value={seedWallet}
              onChange={(event) =>
                setSeedWallet(event.target.value)
              }
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !running
                ) {
                  handleRunDiscovery();
                }
              }}
              placeholder="Seed wallet address..."
              className="mb-5 w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 font-mono outline-none focus:border-blue-500"
            />

            {mode === "FULL" ? (
              <div className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
                <label>
                  <span className="mb-2 block text-sm text-slate-400">
                    Max token
                  </span>

                  <input
                    type="number"
                    min="1"
                    max="20"
                    value={maxTokens}
                    onChange={(event) =>
                      setMaxTokens(
                        Number(event.target.value)
                      )
                    }
                    className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-blue-500"
                  />
                </label>

                <label>
                  <span className="mb-2 block text-sm text-slate-400">
                    Wallet per token
                  </span>

                  <input
                    type="number"
                    min="1"
                    max="20"
                    value={maxWalletsPerToken}
                    onChange={(event) =>
                      setMaxWalletsPerToken(
                        Number(event.target.value)
                      )
                    }
                    className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-blue-500"
                  />
                </label>
              </div>
            ) : (
              <div className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <label>
                  <span className="mb-2 block text-sm text-slate-400">
                    Profondità
                  </span>

                  <input
                    type="number"
                    min="1"
                    max="5"
                    value={maxDepth}
                    onChange={(event) =>
                      setMaxDepth(
                        Number(event.target.value)
                      )
                    }
                    className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-purple-500"
                  />
                </label>

                <label>
                  <span className="mb-2 block text-sm text-slate-400">
                    Token per wallet
                  </span>

                  <input
                    type="number"
                    min="1"
                    max="20"
                    value={maxTokensPerWallet}
                    onChange={(event) =>
                      setMaxTokensPerWallet(
                        Number(event.target.value)
                      )
                    }
                    className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-purple-500"
                  />
                </label>

                <label>
                  <span className="mb-2 block text-sm text-slate-400">
                    Wallet per token
                  </span>

                  <input
                    type="number"
                    min="1"
                    max="20"
                    value={smartMaxWalletsPerToken}
                    onChange={(event) =>
                      setSmartMaxWalletsPerToken(
                        Number(event.target.value)
                      )
                    }
                    className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-purple-500"
                  />
                </label>

                <label>
                  <span className="mb-2 block text-sm text-slate-400">
                    Smart Score minimo
                  </span>

                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={minSmartScore}
                    onChange={(event) =>
                      setMinSmartScore(
                        Number(event.target.value)
                      )
                    }
                    className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-purple-500"
                  />
                </label>
              </div>
            )}

            <button
              type="button"
              onClick={handleRunDiscovery}
              disabled={running}
              className={`w-full rounded-lg px-6 py-3 font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${
                mode === "SMART"
                  ? "bg-purple-600 hover:bg-purple-700"
                  : "bg-blue-600 hover:bg-blue-700"
              }`}
            >
              {running
                ? "Discovery in esecuzione..."
                : `Avvia ${
                    mode === "SMART"
                      ? "Smart Discovery"
                      : "Full Discovery"
                  }`}
            </button>
          </div>
        </section>

        {result && (
          <section className="mb-8 overflow-hidden rounded-xl border border-green-800 bg-slate-800">
            <div className="border-b border-slate-700 p-5">
              <h2 className="text-xl font-bold">
                Ultimo risultato
              </h2>

              <p className="mt-1 break-all font-mono text-sm text-slate-400">
                {result.seed_wallet}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-4 p-5 lg:grid-cols-4">
              <div className="rounded-lg bg-slate-900 p-4">
                <p className="text-sm text-slate-400">
                  Modalità
                </p>

                <p className="mt-2 text-xl font-bold">
                  {mode}
                </p>
              </div>

              <div className="rounded-lg bg-slate-900 p-4">
                <p className="text-sm text-slate-400">
                  Wallet trovati
                </p>

                <p className="mt-2 text-xl font-bold text-green-300">
                  {result.smart_wallets_found ??
                    result.wallets_discovered ??
                    0}
                </p>
              </div>

              <div className="rounded-lg bg-slate-900 p-4">
                <p className="text-sm text-slate-400">
                  Wallet analizzati
                </p>

                <p className="mt-2 text-xl font-bold text-blue-300">
                  {result.wallets_analyzed ??
                    resultRanking.length}
                </p>
              </div>

              <div className="rounded-lg bg-slate-900 p-4">
                <p className="text-sm text-slate-400">
                  Token processati
                </p>

                <p className="mt-2 text-xl font-bold text-purple-300">
                  {result.tokens_processed ?? "-"}
                </p>
              </div>
            </div>

            {resultRanking.length > 0 && (
              <div className="overflow-x-auto border-t border-slate-700">
                <table className="w-full min-w-[760px]">
                  <thead className="bg-slate-700">
                    <tr>
                      <th className="p-4 text-left">
                        Wallet
                      </th>
                      <th className="p-4">Score</th>
                      <th className="p-4">DNA</th>
                      <th className="p-4">ROI</th>
                      <th className="p-4">
                        Win Rate
                      </th>
                    </tr>
                  </thead>

                  <tbody>
                    {resultRanking
                      .slice(0, 10)
                      .map((wallet, index) => {
                        const walletAddress =
                          getResultWalletAddress(wallet);

                        return (
                          <tr
                            key={
                              walletAddress || index
                            }
                            className="border-t border-slate-700"
                          >
                            <td className="p-4 font-mono text-sm">
                              {walletAddress ? (
                                <Link
                                  to={`/wallet/${walletAddress}`}
                                  className="text-blue-400 hover:underline"
                                  title={walletAddress}
                                >
                                  {shortenAddress(
                                    walletAddress
                                  )}
                                </Link>
                              ) : (
                                "-"
                              )}
                            </td>

                            <td className="text-center font-bold text-green-300">
                              {formatNumber(
                                wallet.smart_score
                              )}
                            </td>

                            <td className="text-center text-purple-300">
                              {wallet.classification ??
                                "NORMAL"}
                            </td>

                            <td className="text-center">
                              {formatNumber(
                                wallet.roi_percent
                              )}
                              %
                            </td>

                            <td className="text-center">
                              {formatNumber(
                                wallet.win_rate_percent
                              )}
                              %
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

        <section className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Wallet scoperti
            </p>

            <p className="mt-2 text-3xl font-bold text-blue-300">
              {discoveredWallets.length}
            </p>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Risultati visualizzati
            </p>

            <p className="mt-2 text-3xl font-bold text-purple-300">
              {filteredWallets.length}
            </p>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
            <p className="text-sm text-slate-400">
              Miglior Smart Score
            </p>

            <p className="mt-2 text-3xl font-bold text-green-300">
              {bestDiscoveredScore}
            </p>
          </div>
        </section>

        <section className="mb-8 overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="border-b border-slate-700 p-5">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <input
                type="text"
                value={search}
                onChange={(event) =>
                  setSearch(event.target.value)
                }
                placeholder="Cerca wallet, token o stato..."
                className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-blue-500 md:col-span-2"
              />

              <input
                type="number"
                min="0"
                max="100"
                value={minimumScore}
                onChange={(event) =>
                  setMinimumScore(
                    Number(event.target.value)
                  )
                }
                placeholder="Score minimo"
                className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[1050px]">
              <thead className="bg-slate-700">
                <tr>
                  <th className="p-4 text-left">
                    Wallet
                  </th>
                  <th className="p-4">Score</th>
                  <th className="p-4">ROI</th>
                  <th className="p-4">Win Rate</th>
                  <th className="p-4">Profit</th>
                  <th className="p-4">
                    Reliable Positions
                  </th>
                  <th className="p-4">
                    Provenienza
                  </th>
                  <th className="p-4">Stato</th>
                </tr>
              </thead>

              <tbody>
                {loadingWallets ? (
                  <tr>
                    <td
                      colSpan={8}
                      className="p-10 text-center text-slate-400"
                    >
                      Caricamento wallet scoperti...
                    </td>
                  </tr>
                ) : filteredWallets.length === 0 ? (
                  <tr>
                    <td
                      colSpan={8}
                      className="p-10 text-center text-slate-400"
                    >
                      Nessun wallet trovato.
                    </td>
                  </tr>
                ) : (
                  filteredWallets.map((wallet) => (
                    <tr
                      key={wallet.wallet_address}
                      className="border-t border-slate-700 hover:bg-slate-700/60"
                    >
                      <td className="p-4 font-mono text-sm">
                        <Link
                          to={`/wallet/${wallet.wallet_address}`}
                          className="text-blue-400 hover:underline"
                          title={wallet.wallet_address}
                        >
                          {shortenAddress(
                            wallet.wallet_address
                          )}
                        </Link>
                      </td>

                      <td className="text-center font-bold text-green-300">
                        {formatNumber(
                          wallet.smart_score
                        )}
                      </td>

                      <td
                        className={`text-center ${
                          Number(wallet.roi_percent) >= 0
                            ? "text-green-300"
                            : "text-red-300"
                        }`}
                      >
                        {formatNumber(
                          wallet.roi_percent
                        )}
                        %
                      </td>

                      <td className="text-center">
                        {formatNumber(
                          wallet.win_rate_percent
                        )}
                        %
                      </td>

                      <td
                        className={`text-center ${
                          Number(
                            wallet.profit_loss_sol
                          ) >= 0
                            ? "text-green-300"
                            : "text-red-300"
                        }`}
                      >
                        {formatNumber(
                          wallet.profit_loss_sol,
                          4
                        )}{" "}
                        SOL
                      </td>

                      <td className="text-center">
                        {wallet.reliable_positions ?? 0}
                      </td>

                      <td
                        className="p-4 text-center font-mono text-xs"
                        title={
                          wallet.discovered_from_token
                        }
                      >
                        {shortenAddress(
                          wallet.discovered_from_token,
                          6,
                          5
                        )}
                      </td>

                      <td className="p-4 text-center">
                        <span className="rounded-full bg-blue-900/40 px-3 py-1 text-xs text-blue-300">
                          {wallet.status ?? "DISCOVERED"}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="flex items-center justify-between border-b border-slate-700 p-5">
            <div>
              <h2 className="text-xl font-bold">
                Cronologia discovery
              </h2>

              <p className="mt-1 text-sm text-slate-400">
                Salvata localmente su questo browser
              </p>
            </div>

            <button
              type="button"
              onClick={clearHistory}
              disabled={historyItems.length === 0}
              className="rounded-lg border border-red-700 bg-red-900/30 px-4 py-2 text-sm text-red-300 hover:bg-red-900/60 disabled:opacity-40"
            >
              Cancella cronologia
            </button>
          </div>

          <div className="divide-y divide-slate-700">
            {historyItems.length === 0 ? (
              <p className="p-8 text-center text-slate-400">
                Nessuna discovery eseguita.
              </p>
            ) : (
              historyItems.map((item) => (
                <article
                  key={item.id}
                  className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center lg:justify-between"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded-full px-3 py-1 text-xs font-semibold ${
                          item.mode === "SMART"
                            ? "bg-purple-900/50 text-purple-300"
                            : "bg-blue-900/50 text-blue-300"
                        }`}
                      >
                        {item.mode}
                      </span>

                      <span className="text-sm text-slate-500">
                        {new Date(
                          item.created_at
                        ).toLocaleString("it-IT")}
                      </span>
                    </div>

                    <Link
                      to={`/wallet/${item.seed_wallet}`}
                      className="mt-2 block truncate font-mono text-sm text-blue-400 hover:underline"
                      title={item.seed_wallet}
                    >
                      {item.seed_wallet}
                    </Link>
                  </div>

                  <div className="flex flex-wrap gap-5 text-sm">
                    <div>
                      <p className="text-slate-500">
                        Trovati
                      </p>

                      <p className="font-bold text-green-300">
                        {item.wallets_found}
                      </p>
                    </div>

                    <div>
                      <p className="text-slate-500">
                        Analizzati
                      </p>

                      <p className="font-bold text-blue-300">
                        {item.wallets_analyzed}
                      </p>
                    </div>

                    <div>
                      <p className="text-slate-500">
                        Token
                      </p>

                      <p className="font-bold">
                        {item.tokens_processed ?? "-"}
                      </p>
                    </div>

                    <div>
                      <p className="text-slate-500">
                        Depth
                      </p>

                      <p className="font-bold">
                        {item.max_depth ?? "-"}
                      </p>
                    </div>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

export default Discovery;  