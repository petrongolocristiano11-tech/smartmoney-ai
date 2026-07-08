import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getDiscoveredWallets, runDiscovery } from "./services/api";

function App() {
  const [wallets, setWallets] = useState([]);
  const [walletAddress, setWalletAddress] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [lastDiscovery, setLastDiscovery] = useState(null);
  const [maxTokens, setMaxTokens] = useState(3);
  const [maxWalletsPerToken, setMaxWalletsPerToken] = useState(3);
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("smart_score");

  const averageScore =
    wallets.length > 0
      ? (
          wallets.reduce((sum, wallet) => sum + wallet.smart_score, 0) /
          wallets.length
        ).toFixed(2)
      : "-";

  const filteredWallets = wallets
    .filter((wallet) =>
      wallet.wallet_address.toLowerCase().includes(search.toLowerCase())
    )
    .sort((a, b) => {
      switch (sortBy) {
        case "roi":
          return b.roi_percent - a.roi_percent;
        case "winrate":
          return b.win_rate_percent - a.win_rate_percent;
        case "profit":
          return b.profit_loss_sol - a.profit_loss_sol;
        default:
          return b.smart_score - a.smart_score;
      }
    });

  function loadWallets() {
    getDiscoveredWallets()
      .then((response) => setWallets(response.data))
      .catch(console.error);
  }

  useEffect(() => {
    loadWallets();
  }, []);

  function handleDiscover() {
    if (!walletAddress.trim()) {
      alert("Inserisci un wallet");
      return;
    }

    setLoading(true);
    setMessage("");
    setLastDiscovery(null);

    runDiscovery(walletAddress, maxTokens, maxWalletsPerToken)
      .then((response) => {
        loadWallets();
        setWalletAddress("");
        setMessage(
          `Discovery completata: ${response.data.wallets_discovered} wallet trovati`
        );
        setLastDiscovery(response.data);
      })
      .catch((error) => {
        console.error(error);
        alert("Errore durante la discovery");
      })
      .finally(() => setLoading(false));
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700 p-6">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-4xl font-bold">🚀 SmartMoney AI</h1>
            <p className="text-slate-400 mt-2">
              Discover the smartest wallets on Solana
            </p>
          </div>

          <div className="rounded-full bg-green-900/40 border border-green-700 px-4 py-2 text-green-300 text-sm">
            Backend Online
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto p-8">
        <div className="mb-6 grid grid-cols-1 md:grid-cols-6 gap-4">
          <input
            type="text"
            value={walletAddress}
            onChange={(event) => setWalletAddress(event.target.value)}
            placeholder="Wallet address..."
            className="md:col-span-2 rounded-lg bg-slate-800 border border-slate-700 px-4 py-3 outline-none focus:border-blue-500"
          />

          <input
            type="number"
            value={maxTokens}
            onChange={(event) => setMaxTokens(Number(event.target.value))}
            min="1"
            max="20"
            className="rounded-lg bg-slate-800 border border-slate-700 px-4 py-3 outline-none focus:border-blue-500"
            placeholder="Max tokens"
          />

          <input
            type="number"
            value={maxWalletsPerToken}
            onChange={(event) =>
              setMaxWalletsPerToken(Number(event.target.value))
            }
            min="1"
            max="20"
            className="rounded-lg bg-slate-800 border border-slate-700 px-4 py-3 outline-none focus:border-blue-500"
            placeholder="Wallets/token"
          />

          <input
            type="text"
            placeholder="Search wallet..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="rounded-lg bg-slate-800 border border-slate-700 px-4 py-3 outline-none focus:border-blue-500"
          />

          <select
            value={sortBy}
            onChange={(event) => setSortBy(event.target.value)}
            className="rounded-lg bg-slate-800 border border-slate-700 px-4 py-3 outline-none focus:border-blue-500"
          >
            <option value="smart_score">Smart Score</option>
            <option value="roi">ROI</option>
            <option value="winrate">Win Rate</option>
            <option value="profit">Profit</option>
          </select>

          <button
            onClick={handleDiscover}
            disabled={loading}
            className="md:col-span-6 rounded-lg bg-blue-600 px-6 py-3 font-semibold hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "Discovering..." : "Discover"}
          </button>
        </div>

        {message && (
          <div className="mb-6 rounded-lg bg-green-900/40 border border-green-700 px-4 py-3 text-green-300">
            {message}
          </div>
        )}

        {lastDiscovery && (
          <div className="mb-8 rounded-xl bg-slate-800 border border-slate-700 p-6">
            <h2 className="text-xl font-bold mb-4">Last Discovery Result</h2>

            <div className="grid grid-cols-3 gap-4 mb-6">
              <div>
                <p className="text-slate-400">Seed Wallet</p>
                <p className="font-mono text-xs break-all">
                  {lastDiscovery.seed_wallet}
                </p>
              </div>

              <div>
                <p className="text-slate-400">Tokens Processed</p>
                <p className="text-2xl font-bold">
                  {lastDiscovery.tokens_processed}
                </p>
              </div>

              <div>
                <p className="text-slate-400">Wallets Discovered</p>
                <p className="text-2xl font-bold">
                  {lastDiscovery.wallets_discovered}
                </p>
              </div>
            </div>

            <h3 className="font-semibold mb-3">Top Results</h3>

            <div className="space-y-2">
              {lastDiscovery.ranking?.slice(0, 5).map((item) => (
                <div
                  key={item.wallet}
                  className="flex justify-between gap-4 rounded-lg bg-slate-900 px-4 py-3"
                >
                  <span className="font-mono text-xs break-all">
                    {item.wallet}
                  </span>
                  <span className="font-bold whitespace-nowrap">
                    Score: {item.smart_score}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="grid grid-cols-4 gap-6 mb-8">
          <div className="rounded-xl bg-slate-800 p-6">
            <h3 className="text-slate-400">Wallets</h3>
            <p className="text-3xl font-bold">{wallets.length}</p>
          </div>

          <div className="rounded-xl bg-slate-800 p-6">
            <h3 className="text-slate-400">Best Score</h3>
            <p className="text-3xl font-bold">
              {wallets.length ? wallets[0].smart_score : "-"}
            </p>
          </div>

          <div className="rounded-xl bg-slate-800 p-6">
            <h3 className="text-slate-400">Average Score</h3>
            <p className="text-3xl font-bold">{averageScore}</p>
          </div>

          <div className="rounded-xl bg-slate-800 p-6">
            <h3 className="text-slate-400">Showing</h3>
            <p className="text-3xl font-bold text-green-400">
              {filteredWallets.length}
            </p>
          </div>
        </div>

        <div className="rounded-xl bg-slate-800 overflow-hidden">
          <div className="p-5 border-b border-slate-700">
            <h2 className="text-xl font-bold">Top Smart Wallets</h2>
          </div>

          <table className="w-full">
            <thead className="bg-slate-700">
              <tr>
                <th className="text-left p-4">Wallet</th>
                <th className="p-4">Score</th>
                <th className="p-4">ROI</th>
                <th className="p-4">Win Rate</th>
                <th className="p-4">Profit</th>
                <th className="p-4">Status</th>
              </tr>
            </thead>

            <tbody>
              {filteredWallets.map((wallet) => (
                <tr
                  key={wallet.id}
                  className="border-t border-slate-700 hover:bg-slate-700"
                >
                  <td className="p-4 font-mono text-sm">
                    <Link
                      to={`/wallet/${wallet.wallet_address}`}
                      className="text-blue-400 hover:underline"
                    >
                      {wallet.wallet_address}
                    </Link>
                  </td>

                  <td className="text-center font-bold">
                    {wallet.smart_score}
                  </td>

                  <td className="text-center">{wallet.roi_percent}%</td>

                  <td className="text-center">
                    {wallet.win_rate_percent}%
                  </td>

                  <td className="text-center">
                    {wallet.profit_loss_sol} SOL
                  </td>

                  <td className="text-center">
                    <span className="rounded-full bg-slate-700 px-3 py-1 text-xs">
                      {wallet.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}

export default App; 