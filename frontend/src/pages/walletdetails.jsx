import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getWallet, getWalletTrades } from "../services/api";

function WalletDetails() {
  const { walletAddress } = useParams();

  const [wallet, setWallet] = useState(null);
  const [trades, setTrades] = useState([]);

  useEffect(() => {
    getWallet(walletAddress)
      .then((response) => setWallet(response.data))
      .catch(console.error);

    getWalletTrades(walletAddress)
      .then((response) => setTrades(response.data))
      .catch(console.error);
  }, [walletAddress]);

  if (!wallet) {
    return (
      <div className="min-h-screen bg-slate-900 text-white flex items-center justify-center">
        Loading...
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white p-8">
      <Link to="/" className="text-blue-400 hover:underline">
        ← Back to Dashboard
      </Link>

      <div className="mt-8 rounded-xl bg-slate-800 p-8">

        <h1 className="text-3xl font-bold mb-8">
          Wallet Details
        </h1>

        <div className="grid grid-cols-2 gap-6 mb-10">

          <div>
            <p className="text-slate-400">Wallet</p>
            <p className="font-mono break-all">
              {wallet.wallet_address}
            </p>
          </div>

          <div>
            <p className="text-slate-400">Status</p>
            <p>{wallet.status}</p>
          </div>

          <div>
            <p className="text-slate-400">Smart Score</p>
            <p className="text-2xl font-bold">
              {wallet.smart_score}
            </p>
          </div>

          <div>
            <p className="text-slate-400">ROI</p>
            <p className="text-2xl font-bold">
              {wallet.roi_percent}%
            </p>
          </div>

          <div>
            <p className="text-slate-400">Win Rate</p>
            <p className="text-2xl font-bold">
              {wallet.win_rate_percent}%
            </p>
          </div>

          <div>
            <p className="text-slate-400">Profit / Loss</p>
            <p className="text-2xl font-bold">
              {wallet.profit_loss_sol} SOL
            </p>
          </div>

          <div>
            <p className="text-slate-400">Reliable Positions</p>
            <p className="text-2xl font-bold">
              {wallet.reliable_positions}
            </p>
          </div>

        </div>

        <h2 className="text-2xl font-bold mb-4">
          Trade History
        </h2>

        <div className="overflow-x-auto rounded-lg">

          <table className="w-full">

            <thead className="bg-slate-700">

              <tr>
                <th className="p-3 text-left">Side</th>
                <th className="p-3 text-left">Token</th>
                <th className="p-3 text-right">Amount</th>
                <th className="p-3 text-right">SOL</th>
                <th className="p-3 text-left">Source</th>
              </tr>

            </thead>

            <tbody>

              {trades.map((trade) => (

                <tr
                  key={trade.id}
                  className="border-b border-slate-700 hover:bg-slate-700"
                >

                  <td className="p-3">

                    <span
                      className={`px-3 py-1 rounded-full text-sm font-semibold ${
                        trade.side === "BUY"
                          ? "bg-green-700"
                          : "bg-red-700"
                      }`}
                    >
                      {trade.side}
                    </span>

                  </td>

                  <td className="p-3 font-mono text-xs">
                    {trade.token_mint.slice(0, 12)}...
                  </td>

                  <td className="p-3 text-right">
                    {trade.token_amount.toLocaleString()}
                  </td>

                  <td className="p-3 text-right">
                    {trade.sol_amount}
                  </td>

                  <td className="p-3">
                    {trade.source}
                  </td>

                </tr>

              ))}

            </tbody>

          </table>

        </div>

      </div>
    </div>
  );
}

export default WalletDetails; 