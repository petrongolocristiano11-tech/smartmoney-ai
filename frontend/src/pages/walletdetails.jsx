import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  getWallet,
  getWalletTrades,
  getWalletNetwork,
} from "../services/api";

function WalletDetails() {
  const { walletAddress } = useParams();

  const [wallet, setWallet] = useState(null);
  const [trades, setTrades] = useState([]);
  const [network, setNetwork] = useState([]);

  useEffect(() => {
    getWallet(walletAddress)
      .then((response) => setWallet(response.data))
      .catch(console.error);

    getWalletTrades(walletAddress)
      .then((response) => setTrades(response.data))
      .catch(console.error);

    getWalletNetwork(walletAddress)
      .then((response) => setNetwork(response.data.connected_wallets))
      .catch(console.error);
  }, [walletAddress]);

  if (!wallet) {
    return (
      <div className="min-h-screen bg-slate-900 text-white flex items-center justify-center">
        Loading...
      </div>
    );
  }

  const roiPositive = wallet.roi_percent >= 0;
  const profitPositive = wallet.profit_loss_sol >= 0;

  return (
    <div className="min-h-screen bg-slate-900 text-white p-8">
      <Link to="/" className="text-blue-400 hover:underline">
        ← Back to Dashboard
      </Link>

      <div className="mt-8 rounded-xl bg-slate-800 p-8">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-3xl font-bold">Wallet Details</h1>

          <a
            href={`https://solscan.io/account/${wallet.wallet_address}`}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg bg-blue-600 px-4 py-2 font-semibold hover:bg-blue-700"
          >
            Open on Solscan
          </a>
        </div>

        <div className="grid grid-cols-2 gap-6 mb-10">
          <div>
            <p className="text-slate-400">Wallet</p>
            <p className="font-mono break-all">{wallet.wallet_address}</p>
          </div>

          <div>
            <p className="text-slate-400">Status</p>
            <p>{wallet.status}</p>
          </div>

          <div>
            <p className="text-slate-400">Smart Score</p>
            <p className="text-2xl font-bold">{wallet.smart_score}</p>
          </div>

          <div>
            <p className="text-slate-400">ROI</p>
            <p
              className={`text-2xl font-bold ${
                roiPositive ? "text-green-400" : "text-red-400"
              }`}
            >
              {wallet.roi_percent}%
            </p>
          </div>

          <div>
            <p className="text-slate-400">Win Rate</p>
            <p className="text-2xl font-bold">{wallet.win_rate_percent}%</p>
          </div>

          <div>
            <p className="text-slate-400">Profit / Loss</p>
            <p
              className={`text-2xl font-bold ${
                profitPositive ? "text-green-400" : "text-red-400"
              }`}
            >
              {wallet.profit_loss_sol} SOL
            </p>
          </div>

          <div>
            <p className="text-slate-400">Reliable Positions</p>
            <p className="text-2xl font-bold">{wallet.reliable_positions}</p>
          </div>
        </div>

        <h2 className="text-2xl font-bold mb-4">Connected Smart Wallets</h2>

        <div className="rounded-lg overflow-hidden mb-10">
          <table className="w-full">
            <thead className="bg-slate-700">
              <tr>
                <th className="p-3 text-left">Wallet</th>
                <th className="p-3 text-center">Shared Tokens</th>
                <th className="p-3 text-center">Connection</th>
                <th className="p-3 text-center">Score</th>
                <th className="p-3 text-center">ROI</th>
                <th className="p-3 text-center">Win Rate</th>
              </tr>
            </thead>

            <tbody>
              {network.map((item) => (
                <tr
                  key={item.wallet}
                  className="border-b border-slate-700 hover:bg-slate-700"
                >
                  <td className="p-3 font-mono text-xs">
                    <Link
                      to={`/wallet/${item.wallet}`}
                      className="text-blue-400 hover:underline"
                    >
                      {item.wallet}
                    </Link>
                  </td>

                  <td className="text-center">{item.shared_tokens}</td>

                  <td className="text-center font-bold text-purple-400">
                    {item.connection_strength}
                  </td>

                  <td className="text-center font-bold">
                    {item.smart_score}
                  </td>

                  <td className="text-center">{item.roi_percent}%</td>

                  <td className="text-center">
                    {item.win_rate_percent}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2 className="text-2xl font-bold mb-4">Trade History</h2>

        <div className="overflow-x-auto rounded-lg">
          <table className="w-full">
            <thead className="bg-slate-700">
              <tr>
                <th className="p-3 text-left">Side</th>
                <th className="p-3 text-left">Token</th>
                <th className="p-3 text-right">Amount</th>
                <th className="p-3 text-right">SOL</th>
                <th className="p-3 text-left">Source</th>
                <th className="p-3 text-center">Tx</th>
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
                    {trade.token_mint?.slice(0, 12)}...
                  </td>

                  <td className="p-3 text-right">
                    {trade.token_amount?.toLocaleString()}
                  </td>

                  <td className="p-3 text-right">{trade.sol_amount}</td>

                  <td className="p-3">{trade.source}</td>

                  <td className="text-center">
                    <a
                      href={`https://solscan.io/tx/${trade.signature}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-blue-400 hover:underline"
                    >
                      View
                    </a>
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