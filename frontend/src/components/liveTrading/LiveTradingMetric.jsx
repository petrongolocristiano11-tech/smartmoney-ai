function LiveTradingMetric({
  label,
  value,
  subtitle = "",
  tone = "default",
}) {
  const valueStyles = {
    default: "text-white",
    positive: "text-green-300",
    warning: "text-amber-300",
    danger: "text-red-300",
    info: "text-blue-300",
  };

  return (
    <article className="rounded-2xl border border-slate-700 bg-slate-900/80 p-5 shadow-lg shadow-black/10">
      <p className="text-sm font-medium text-slate-400">
        {label}
      </p>

      <p
        className={`mt-2 break-words text-2xl font-bold ${
          valueStyles[tone]
          ?? valueStyles.default
        }`}
      >
        {value}
      </p>

      {subtitle && (
        <p className="mt-2 text-xs leading-5 text-slate-500">
          {subtitle}
        </p>
      )}
    </article>
  );
}


export default LiveTradingMetric; 