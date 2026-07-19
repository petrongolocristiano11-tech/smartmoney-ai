const BADGE_STYLES = {
  DISABLED:
    "border-slate-600 bg-slate-800 text-slate-300",
  DRY_RUN:
    "border-blue-700 bg-blue-950/60 text-blue-300",
  LIVE:
    "border-red-700 bg-red-950/60 text-red-300",
  OPEN:
    "border-green-700 bg-green-950/60 text-green-300",
  CLOSED:
    "border-slate-600 bg-slate-800 text-slate-300",
  BUY:
    "border-green-700 bg-green-950/60 text-green-300",
  SELL:
    "border-red-700 bg-red-950/60 text-red-300",
  RECEIVED:
    "border-slate-600 bg-slate-800 text-slate-300",
  REJECTED:
    "border-amber-700 bg-amber-950/60 text-amber-300",
  QUOTED:
    "border-cyan-700 bg-cyan-950/60 text-cyan-300",
  SUBMITTED:
    "border-indigo-700 bg-indigo-950/60 text-indigo-300",
  FILLED:
    "border-green-700 bg-green-950/60 text-green-300",
  FAILED:
    "border-red-700 bg-red-950/60 text-red-300",
  INFO:
    "border-blue-700 bg-blue-950/60 text-blue-300",
  WARNING:
    "border-amber-700 bg-amber-950/60 text-amber-300",
  ERROR:
    "border-red-700 bg-red-950/60 text-red-300",
  CRITICAL:
    "border-red-500 bg-red-950 text-red-200",
  STOPPED:
    "border-slate-600 bg-slate-800 text-slate-300",
  STARTING:
    "border-indigo-700 bg-indigo-950/60 text-indigo-300",
  IDLE:
    "border-slate-600 bg-slate-800 text-slate-300",
  CONNECTING:
    "border-cyan-700 bg-cyan-950/60 text-cyan-300",
  RUNNING:
    "border-green-700 bg-green-950/60 text-green-300",
  DEGRADED:
    "border-amber-700 bg-amber-950/60 text-amber-300",
};


function LiveTradingBadge({ value }) {
  const normalized = String(
    value ?? "UNKNOWN"
  ).toUpperCase();

  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-bold tracking-wide ${
        BADGE_STYLES[normalized]
        ?? BADGE_STYLES.DISABLED
      }`}
    >
      {normalized}
    </span>
  );
}


export default LiveTradingBadge; 