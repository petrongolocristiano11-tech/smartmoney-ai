import LiveTradingBadge from "./LiveTradingBadge";
import {
  formatLiveDate,
} from "./liveTradingFormatters";


function LiveTradingEvents({
  events,
  loading,
  onRefresh,
}) {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="rounded-xl border border-slate-600 bg-slate-900 px-4 py-2.5 text-sm font-bold text-slate-200 transition hover:border-blue-500 hover:text-white disabled:opacity-50"
        >
          {loading
            ? "Aggiornamento..."
            : "Aggiorna eventi"}
        </button>
      </div>

      <div className="space-y-3">
        {events.map((event) => (
          <article
            key={event.id}
            className="rounded-xl border border-slate-700 bg-slate-900/70 p-4"
          >
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex flex-wrap items-center gap-2">
                <LiveTradingBadge
                  value={event.severity}
                />

                <span className="font-bold text-white">
                  {event.event_type}
                </span>

                {event.order_id && (
                  <span className="text-xs font-semibold text-slate-500">
                    Ordine #{event.order_id}
                  </span>
                )}
              </div>

              <time className="shrink-0 text-xs text-slate-500">
                {formatLiveDate(
                  event.created_at
                )}
              </time>
            </div>

            <p className="mt-3 text-sm leading-6 text-slate-300">
              {event.message}
            </p>

            {event.payload
              && Object.keys(
                event.payload
              ).length > 0 && (
                <details className="mt-3">
                  <summary className="cursor-pointer text-xs font-bold text-blue-300 hover:text-blue-200">
                    Mostra dettagli tecnici
                  </summary>

                  <pre className="mt-3 overflow-x-auto rounded-lg border border-slate-700 bg-slate-950 p-3 text-xs leading-5 text-slate-400">
                    {JSON.stringify(
                      event.payload,
                      null,
                      2
                    )}
                  </pre>
                </details>
              )}
          </article>
        ))}

        {events.length === 0 && (
          <div className="rounded-xl border border-dashed border-slate-700 px-6 py-14 text-center text-slate-500">
            Nessun evento Live Trading registrato.
          </div>
        )}
      </div>
    </div>
  );
}


export default LiveTradingEvents; 