function LiveTradingSection({
  title,
  description = "",
  action = null,
  children,
  className = "",
}) {
  return (
    <section
      className={`rounded-2xl border border-slate-700 bg-slate-800/70 shadow-xl shadow-black/10 ${className}`}
    >
      <header className="flex flex-col gap-4 border-b border-slate-700 px-5 py-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">
            {title}
          </h2>

          {description && (
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-400">
              {description}
            </p>
          )}
        </div>

        {action}
      </header>

      <div className="p-5">
        {children}
      </div>
    </section>
  );
}


export default LiveTradingSection; 