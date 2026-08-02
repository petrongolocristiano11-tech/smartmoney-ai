import {
  formatGen4Duration,
  formatGen4Number,
} from "./gen4ForwardFormatters";

function ProgressBar({ label, current, target, percent, subtitle }) {
  return (
    <div>
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="font-bold text-white">{label}</p>
          <p className="mt-1 text-xs text-slate-500">{subtitle}</p>
        </div>
        <p className="text-sm font-black text-cyan-300">
          {current} / {target}
        </p>
      </div>
      <div className="mt-3 h-3 overflow-hidden rounded-full bg-slate-950">
        <div
          className="h-full rounded-full bg-gradient-to-r from-blue-600 to-cyan-400 transition-all duration-500"
          style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
        />
      </div>
      <p className="mt-2 text-right text-xs text-slate-500">
        {formatGen4Number(percent, 1)}%
      </p>
    </div>
  );
}

function Gen4ForwardProgress({ progress }) {
  return (
    <section className="rounded-3xl border border-slate-700 bg-slate-800/70 p-5 sm:p-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-cyan-400">
            Evidenza strict
          </p>
          <h2 className="mt-1 text-2xl font-black text-white">
            Avanzamento della prova
          </h2>
        </div>
        <p className="text-sm text-slate-400">
          Tempo minimo residuo: {formatGen4Duration(progress.remainingObservationMs)}
        </p>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <ProgressBar
          label="Periodo di osservazione"
          current={formatGen4Number(progress.observationDays, 2)}
          target={`${progress.observationTarget} giorni`}
          percent={progress.observationPercent}
          subtitle="Solo dati successivi all'anchor della campagna."
        />
        <ProgressBar
          label="Campione Strict chiuso"
          current={progress.strictClosed}
          target={`${progress.closedTarget} trade`}
          percent={progress.closedPercent}
          subtitle="La valutazione resta bloccata finché entrambi i requisiti non sono raggiunti."
        />
      </div>
    </section>
  );
}

export default Gen4ForwardProgress;
