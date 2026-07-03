import { useEffect, useState } from "react";
import axios from "axios";

function App() {
  const [wallets, setWallets] = useState([]);

  useEffect(() => {
    axios
      .get("http://127.0.0.1:8000/discovered-wallets")
      .then((response) => setWallets(response.data))
      .catch(console.error);
  }, []);

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700 p-6">
        <h1 className="text-4xl font-bold">🚀 SmartMoney AI</h1>
        <p className="text-slate-400 mt-2">
          Discover the smartest wallets on Solana
        </p>
      </header>

      <main className="max-w-7xl mx-auto p-8">

        <div className="mb-8 flex gap-4">
          <input
            type="text"
            placeholder="Wallet address..."
            className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-4 py-3"
          />

          <button
            className="rounded-lg bg-blue-600 px-6 py-3 font-semibold hover:bg-blue-700"
          >
            Discover
          </button>
        </div>

        <div className="grid grid-cols-3 gap-6 mb-8">

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
            <h3 className="text-slate-400">Status</h3>
            <p className="text-3xl font-bold text-green-400">
              Online
            </p>
          </div>

        </div>

        <div className="rounded-xl bg-slate-800 overflow-hidden">

          <table className="w-full">

            <thead className="bg-slate-700">

              <tr>
                <th className="text-left p-4">Wallet</th>
                <th className="p-4">Score</th>
                <th className="p-4">ROI</th>
                <th className="p-4">Win Rate</th>
              </tr>

            </thead>

            <tbody>

              {wallets.map((wallet) => (

                <tr
                  key={wallet.id}
                  className="border-t border-slate-700 hover:bg-slate-700"
                >

                  <td className="p-4 font-mono text-sm">
                    {wallet.wallet_address}
                  </td>

                  <td className="text-center">
                    {wallet.smart_score}
                  </td>

                  <td className="text-center">
                    {wallet.roi_percent}%
                  </td>

                  <td className="text-center">
                    {wallet.win_rate_percent}%
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