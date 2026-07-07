import { useParams, Link } from "react-router-dom";

function WalletDetails() {
  const { walletAddress } = useParams();

  return (
    <div className="min-h-screen bg-slate-900 text-white p-8">
      <Link to="/" className="text-blue-400 hover:underline">
        ← Back to Dashboard
      </Link>

      <div className="mt-8 rounded-xl bg-slate-800 p-6">
        <h1 className="text-3xl font-bold mb-4">Wallet Details</h1>

        <p className="text-slate-400">Wallet Address</p>
        <p className="font-mono text-sm break-all mt-2">
          {walletAddress}
        </p>
      </div>
    </div>
  );
}

export default WalletDetails; 