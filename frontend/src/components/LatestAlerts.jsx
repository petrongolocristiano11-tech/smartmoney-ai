import { Link } from "react-router-dom";

function shortenAddress(
  address,
  start = 6,
  end = 5
) {
  if (!address) return "-";

  if (address.length <= start + end + 3) {
    return address;
  }

  return `${address.slice(0, start)}...${address.slice(
    -end
  )}`;
}

function getConfidenceClasses(confidence) {
  switch (confidence) {
    case "HIGH":
      return "border-green-700 bg-green-900/40 text-green-300";

    case "MEDIUM":
      return "border-yellow-700 bg-yellow-900/40 text-yellow-300";

    default:
      return "border-slate-600 bg-slate-700/60 text-slate-300";
  }
}

function LatestAlerts({ alerts = [] }) {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
      <div className="flex items-center justify-between border-b border-slate-700 p-5">
        <div>
          <h2 className="text-xl font-bold">
            Latest Alerts
          </h2>

          <p className="mt-1 text-sm text-slate-400">
            Accumulazioni smart rilevate dal motore
          </p>
        </div>

        <span className="rounded-full border border-red-700 bg-red-900/40 px-3 py-1 text-sm text-red-300">
          {alerts.length}
        </span>
      </div>

      <div className="divide-y divide-slate-700">
        {alerts.length === 0 ? (
          <p className="p-5 text-slate-400">
            Nessun alert disponibile.
          </p>
        ) : (
          alerts.map((alert, index) => (
            <div
              key={`${alert.token}-${index}`}
              className="p-5 hover:bg-slate-700/40"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <p className="text-xs uppercase tracking-wide text-red-300">
                    {alert.type ??
                      "SMART_ACCUMULATION"}
                  </p>

                  <div className="mt-1 flex flex-wrap items-center gap-3">
                    <Link
                      to={`/token/${alert.token}`}
                      className="font-mono text-sm text-blue-300 hover:underline"
                      title={alert.token}
                    >
                      {shortenAddress(
                        alert.token,
                        10,
                        8
                      )}
                    </Link>

                    <a
                      href={`https://solscan.io/token/${alert.token}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-slate-500 hover:text-blue-300"
                    >
                      Solscan ↗
                    </a>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded-full border px-3 py-1 text-xs font-semibold ${getConfidenceClasses(
                      alert.confidence
                    )}`}
                  >
                    {alert.confidence ?? "LOW"}
                  </span>

                  <span className="rounded-full border border-red-700 bg-red-900/40 px-3 py-1 text-xs font-semibold text-red-300">
                    Score {alert.signal_score ?? 0}
                  </span>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <div>
                  <p className="text-slate-400">
                    Buyers
                  </p>

                  <p className="font-semibold">
                    {alert.buyers ?? 0}
                  </p>
                </div>

                <div>
                  <p className="text-slate-400">
                    Avg score
                  </p>

                  <p className="font-semibold">
                    {alert.average_smart_score ?? 0}
                  </p>
                </div>

                <div>
                  <p className="text-slate-400">
                    Avg ROI
                  </p>

                  <p className="font-semibold">
                    {alert.average_roi ?? 0}%
                  </p>
                </div>

                <div>
                  <p className="text-slate-400">
                    Volume
                  </p>

                  <p className="font-semibold">
                    {alert.total_volume_sol ?? 0} SOL
                  </p>
                </div>
              </div>

              <div className="mt-4 text-sm">
                <span className="text-slate-400">
                  Leader:{" "}
                </span>

                {alert.leader_wallet ? (
                  <Link
                    to={`/wallet/${alert.leader_wallet}`}
                    className="font-mono text-blue-400 hover:underline"
                    title={alert.leader_wallet}
                  >
                    {shortenAddress(
                      alert.leader_wallet
                    )}
                  </Link>
                ) : (
                  <span>-</span>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

export default LatestAlerts; 