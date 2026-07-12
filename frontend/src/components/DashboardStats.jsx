export default function DashboardStats({
  wallets,
  averageScore,
  filteredWallets,
  dashboard,
}) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-8 gap-6 mb-8">
      <div className="rounded-xl bg-slate-800 p-6">
        <h3 className="text-slate-400">Wallets</h3>
        <p className="text-3xl font-bold">
          {dashboard?.stats?.wallets ?? wallets.length}
        </p>
      </div>

      <div className="rounded-xl bg-slate-800 p-6">
        <h3 className="text-slate-400">Smart</h3>
        <p className="text-3xl font-bold text-green-400">
          {dashboard?.stats?.smart_wallets ?? "-"}
        </p>
      </div>

      <div className="rounded-xl bg-slate-800 p-6">
        <h3 className="text-slate-400">Trades</h3>
        <p className="text-3xl font-bold">
          {dashboard?.stats?.trades ?? "-"}
        </p>
      </div>

      <div className="rounded-xl bg-slate-800 p-6">
        <h3 className="text-slate-400">Signals</h3>
        <p className="text-3xl font-bold text-yellow-400">
          {dashboard?.stats?.signals ?? "-"}
        </p>
      </div>

      <div className="rounded-xl bg-slate-800 p-6">
        <h3 className="text-slate-400">Alerts</h3>
        <p className="text-3xl font-bold text-red-400">
          {dashboard?.stats?.alerts ?? "-"}
        </p>
      </div>

      <div className="rounded-xl bg-slate-800 p-6">
        <h3 className="text-slate-400">Best Score</h3>
        <p className="text-3xl font-bold">
          {wallets.length ? wallets[0].smart_score : "-"}
        </p>
      </div>

      <div className="rounded-xl bg-slate-800 p-6">
        <h3 className="text-slate-400">Average</h3>
        <p className="text-3xl font-bold">
          {averageScore}
        </p>
      </div>

      <div className="rounded-xl bg-slate-800 p-6">
        <h3 className="text-slate-400">Showing</h3>
        <p className="text-3xl font-bold text-cyan-400">
          {filteredWallets.length}
        </p>
      </div>
    </div>
  );
} 