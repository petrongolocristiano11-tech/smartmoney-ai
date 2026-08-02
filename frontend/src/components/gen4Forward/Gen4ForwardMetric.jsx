const TONE_CLASSES = {
  neutral: "border-slate-700 bg-slate-900/70 text-slate-100",
  positive: "border-emerald-800 bg-emerald-950/35 text-emerald-100",
  warning: "border-amber-800 bg-amber-950/35 text-amber-100",
  danger: "border-red-800 bg-red-950/35 text-red-100",
  info: "border-cyan-800 bg-cyan-950/35 text-cyan-100",
};

function Gen4ForwardMetric({
  label,
  value,
  subtitle = "",
  tone = "neutral",
}) {
  return (
    <article
      className={`rounded-2xl border p-4 shadow-lg shadow-black/10 ${
        TONE_CLASSES[tone] ?? TONE_CLASSES.neutral
      }`}
    >
      <p className="text-xs font-bold uppercase tracking-wider opacity-65">
        {label}
      </p>
      <p className="mt-2 break-words text-2xl font-black text-white">
        {value}
      </p>
      {subtitle && (
        <p className="mt-2 text-xs leading-5 opacity-70">
          {subtitle}
        </p>
      )}
    </article>
  );
}

export default Gen4ForwardMetric;
