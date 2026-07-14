import { Link } from "react-router-dom";

function shortenAddress(
  address,
  start = 6,
  end = 5
) {
  if (!address) {
    return "-";
  }

  if (
    address.length
    <= start + end + 3
  ) {
    return address;
  }

  return `${address.slice(
    0,
    start
  )}...${address.slice(-end)}`;
}

function formatNumber(
  value,
  digits = 2
) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "0";
  }

  return number.toLocaleString(
    "it-IT",
    {
      maximumFractionDigits: digits,
    }
  );
}

function formatAge(hours) {
  const value = Number(hours);

  if (!Number.isFinite(value)) {
    return "-";
  }

  if (value < 1) {
    return "< 1 ora";
  }

  if (value < 24) {
    return `${Math.round(value)} ore`;
  }

  return `${Math.round(
    value / 24
  )} giorni`;
}

function getConfidenceClasses(
  confidence
) {
  switch (confidence) {
    case "HIGH":
      return "border-green-700 bg-green-900/40 text-green-300";

    case "MEDIUM":
      return "border-yellow-700 bg-yellow-900/40 text-yellow-300";

    default:
      return "border-slate-600 bg-slate-700/60 text-slate-300";
  }
}

function TopSignals({
  signals = [],
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
      <div className="flex items-center justify-between border-b border-slate-700 p-5">
        <div>
          <h2 className="text-xl font-bold">
            Top Signals v2
          </h2>

          <p className="mt-1 text-sm text-slate-400">
            Segnali pesati per consenso,
            freschezza e qualità dei dati
          </p>
        </div>

        <span className="rounded-full border border-yellow-700 bg-yellow-900/40 px-3 py-1 text-sm text-yellow-300">
          {signals.length}
        </span>
      </div>

      <div className="divide-y divide-slate-700">
        {signals.length === 0 ? (
          <p className="p-5 text-slate-400">
            Nessun segnale disponibile.
          </p>
        ) : (
          signals.map(
            (signal, index) => (
              <article
                key={`${signal.token_mint}-${index}`}
                className="p-5 hover:bg-slate-700/40"
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <p className="text-xs uppercase tracking-wide text-slate-400">
                      Token
                    </p>

                    <div className="mt-1 flex flex-wrap items-center gap-3">
                      <Link
                        to={`/token/${signal.token_mint}`}
                        className="font-mono text-sm text-blue-300 hover:underline"
                        title={
                          signal.token_mint
                        }
                      >
                        {shortenAddress(
                          signal.token_mint,
                          10,
                          8
                        )}
                      </Link>

                      <span className="rounded-full border border-slate-600 px-2 py-0.5 text-xs text-slate-400">
                        v
                        {signal.version ??
                          "2.0"}
                      </span>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-full border px-3 py-1 text-xs font-semibold ${getConfidenceClasses(
                        signal.confidence
                      )}`}
                    >
                      {signal.confidence ??
                        "LOW"}
                    </span>

                    <span className="rounded-full border border-blue-700 bg-blue-900/40 px-3 py-1 text-xs font-semibold text-blue-300">
                      Score{" "}
                      {formatNumber(
                        signal.signal_score
                      )}
                    </span>

                    <span className="rounded-full border border-purple-700 bg-purple-900/40 px-3 py-1 text-xs font-semibold text-purple-300">
                      Evidenza{" "}
                      {formatNumber(
                        signal.evidence_score
                      )}
                    </span>
                  </div>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3 lg:grid-cols-6">
                  <div>
                    <p className="text-slate-400">
                      Buyers
                    </p>

                    <p className="font-semibold">
                      {signal.buyers ?? 0}
                    </p>
                  </div>

                  <div>
                    <p className="text-slate-400">
                      Avg score
                    </p>

                    <p className="font-semibold">
                      {formatNumber(
                        signal.average_smart_score
                      )}
                    </p>
                  </div>

                  <div>
                    <p className="text-slate-400">
                      Avg ROI
                    </p>

                    <p className="font-semibold">
                      {formatNumber(
                        signal.average_roi
                      )}
                      %
                    </p>
                  </div>

                  <div>
                    <p className="text-slate-400">
                      Volume
                    </p>

                    <p className="font-semibold">
                      {formatNumber(
                        signal.total_volume_sol,
                        4
                      )}{" "}
                      SOL
                    </p>
                  </div>

                  <div>
                    <p className="text-slate-400">
                      Quota smart
                    </p>

                    <p className="font-semibold">
                      {formatNumber(
                        signal.smart_volume_share_percent
                      )}
                      %
                    </p>
                  </div>

                  <div>
                    <p className="text-slate-400">
                      Freschezza
                    </p>

                    <p className="font-semibold">
                      {formatAge(
                        signal.age_hours
                      )}
                    </p>
                  </div>
                </div>

                {signal.reasons?.length > 0 && (
                  <div className="mt-4 space-y-1">
                    {signal.reasons
                      .slice(0, 2)
                      .map((reason) => (
                        <p
                          key={reason}
                          className="text-xs text-green-300"
                        >
                          ✓ {reason}
                        </p>
                      ))}
                  </div>
                )}

                {signal.risk_flags?.length >
                  0 && (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {signal.risk_flags.map(
                      (flag) => (
                        <span
                          key={flag}
                          className="rounded-full border border-red-800 bg-red-950/30 px-2 py-1 text-[11px] text-red-300"
                        >
                          {flag}
                        </span>
                      )
                    )}
                  </div>
                )}

                <div className="mt-4 text-sm">
                  <span className="text-slate-400">
                    Leader:{" "}
                  </span>

                  {signal.leader_wallet ? (
                    <Link
                      to={`/wallet/${signal.leader_wallet}`}
                      className="font-mono text-blue-400 hover:underline"
                      title={
                        signal.leader_wallet
                      }
                    >
                      {shortenAddress(
                        signal.leader_wallet
                      )}
                    </Link>
                  ) : (
                    <span>-</span>
                  )}
                </div>
              </article>
            )
          )
        )}
      </div>
    </section>
  );
}

export default TopSignals; 