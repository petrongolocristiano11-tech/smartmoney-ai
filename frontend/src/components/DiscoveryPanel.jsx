function DiscoveryPanel({
  walletAddress,
  setWalletAddress,
  maxTokens,
  setMaxTokens,
  maxWalletsPerToken,
  setMaxWalletsPerToken,
  search,
  setSearch,
  sortBy,
  setSortBy,
  loading,
  message,
  lastDiscovery,
  onDiscover,
}) {
  return (
    <>
      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-6">
        <input
          type="text"
          value={walletAddress}
          onChange={(event) => setWalletAddress(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !loading) {
              onDiscover();
            }
          }}
          placeholder="Wallet address..."
          className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-3 outline-none focus:border-blue-500 md:col-span-2"
        />

        <input
          type="number"
          value={maxTokens}
          onChange={(event) => setMaxTokens(Number(event.target.value))}
          min="1"
          max="20"
          placeholder="Max tokens"
          className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-3 outline-none focus:border-blue-500"
        />

        <input
          type="number"
          value={maxWalletsPerToken}
          onChange={(event) =>
            setMaxWalletsPerToken(Number(event.target.value))
          }
          min="1"
          max="20"
          placeholder="Wallets/token"
          className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-3 outline-none focus:border-blue-500"
        />

        <input
          type="text"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search wallet..."
          className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-3 outline-none focus:border-blue-500"
        />

        <select
          value={sortBy}
          onChange={(event) => setSortBy(event.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-3 outline-none focus:border-blue-500"
        >
          <option value="smart_score">Smart Score</option>
          <option value="roi">ROI</option>
          <option value="winrate">Win Rate</option>
          <option value="profit">Profit</option>
        </select>

        <button
          type="button"
          onClick={onDiscover}
          disabled={loading}
          className="rounded-lg bg-blue-600 px-6 py-3 font-semibold hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 md:col-span-6"
        >
          {loading ? "Discovering..." : "Discover"}
        </button>
      </div>

      {message && (
        <div className="mb-6 rounded-lg border border-green-700 bg-green-900/40 px-4 py-3 text-green-300">
          {message}
        </div>
      )}

      {lastDiscovery && (
        <div className="mb-8 rounded-xl border border-slate-700 bg-slate-800 p-6">
          <h2 className="mb-4 text-xl font-bold">
            Last Discovery Result
          </h2>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <div>
              <p className="text-slate-400">Seed Wallet</p>

              <p className="break-all font-mono text-xs">
                {lastDiscovery.seed_wallet ?? "-"}
              </p>
            </div>

            <div>
              <p className="text-slate-400">Tokens Processed</p>

              <p className="text-2xl font-bold">
                {lastDiscovery.tokens_processed ?? 0}
              </p>
            </div>

            <div>
              <p className="text-slate-400">Wallets Discovered</p>

              <p className="text-2xl font-bold">
                {lastDiscovery.wallets_discovered ?? 0}
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default DiscoveryPanel; 