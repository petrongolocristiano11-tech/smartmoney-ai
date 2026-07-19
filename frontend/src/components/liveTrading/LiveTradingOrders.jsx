import LiveTradingBadge from "./LiveTradingBadge";
import {
  formatLiveDate,
  formatLiveNumber,
  shortenLiveAddress,
} from "./liveTradingFormatters";


function LiveTradingOrders({
  orders,
  filters,
  loading,
  onFilterChange,
  onRefresh,
}) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block">
          <span className="text-xs font-bold uppercase tracking-wide text-slate-500">
            Stato
          </span>

          <select
            value={filters.status}
            onChange={(event) =>
              onFilterChange(
                "status",
                event.target.value
              )
            }
            className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-3 py-2.5 text-sm text-white outline-none focus:border-blue-500"
          >
            <option value="">
              Tutti gli stati
            </option>
            <option value="RECEIVED">
              RECEIVED
            </option>
            <option value="REJECTED">
              REJECTED
            </option>
            <option value="DRY_RUN">
              DRY_RUN
            </option>
            <option value="QUOTED">
              QUOTED
            </option>
            <option value="SUBMITTED">
              SUBMITTED
            </option>
            <option value="FILLED">
              FILLED
            </option>
            <option value="FAILED">
              FAILED
            </option>
          </select>
        </label>

        <label className="block">
          <span className="text-xs font-bold uppercase tracking-wide text-slate-500">
            Modalità
          </span>

          <select
            value={filters.mode}
            onChange={(event) =>
              onFilterChange(
                "mode",
                event.target.value
              )
            }
            className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-3 py-2.5 text-sm text-white outline-none focus:border-blue-500"
          >
            <option value="">
              Tutte le modalità
            </option>
            <option value="DRY_RUN">
              DRY_RUN
            </option>
            <option value="LIVE">
              LIVE
            </option>
          </select>
        </label>

        <div className="flex items-end">
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="w-full rounded-xl border border-slate-600 bg-slate-900 px-4 py-2.5 text-sm font-bold text-slate-200 transition hover:border-blue-500 hover:text-white disabled:opacity-50"
          >
            {loading
              ? "Aggiornamento..."
              : "Aggiorna ordini"}
          </button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-700">
        <table className="min-w-[1180px] w-full text-left text-sm">
          <thead className="bg-slate-950/80 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">
                Ordine
              </th>
              <th className="px-4 py-3">
                Stato
              </th>
              <th className="px-4 py-3">
                Sorgente
              </th>
              <th className="px-4 py-3">
                Token
              </th>
              <th className="px-4 py-3 text-right">
                Valore SOL
              </th>
              <th className="px-4 py-3 text-right">
                Output raw
              </th>
              <th className="px-4 py-3 text-right">
                PnL SOL
              </th>
              <th className="px-4 py-3">
                Router
              </th>
              <th className="px-4 py-3">
                Data
              </th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-800 bg-slate-900/50">
            {orders.map((order) => (
              <tr
                key={order.id}
                className="transition hover:bg-slate-800/70"
              >
                <td className="px-4 py-4 align-top">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-bold text-white">
                      #{order.id}
                    </span>

                    <LiveTradingBadge
                      value={order.mode}
                    />

                    <LiveTradingBadge
                      value={order.source_side}
                    />

                    <span className="rounded-full border border-slate-600 bg-slate-950 px-2.5 py-1 text-xs font-bold text-slate-400">
                      Gen #{order.generation}
                    </span>
                  </div>

                  <p
                    className="mt-2 max-w-[260px] truncate font-mono text-xs text-slate-500"
                    title={
                      order.transaction_signature
                      ?? order.source_signature
                    }
                  >
                    {shortenLiveAddress(
                      order.transaction_signature
                      ?? order.source_signature,
                      10,
                      8
                    )}
                  </p>
                </td>

                <td className="px-4 py-4 align-top">
                  <LiveTradingBadge
                    value={order.status}
                  />

                  {order.error_message && (
                    <p
                      className="mt-2 max-w-[240px] text-xs leading-5 text-red-300"
                      title={order.error_message}
                    >
                      {order.error_code
                        ? `${order.error_code}: `
                        : ""}
                      {order.error_message}
                    </p>
                  )}
                </td>

                <td className="px-4 py-4 align-top">
                  <p
                    className="font-mono text-xs text-slate-300"
                    title={order.source_wallet}
                  >
                    {shortenLiveAddress(
                      order.source_wallet
                    )}
                  </p>

                  <p className="mt-2 text-xs text-slate-500">
                    Trade #{
                      order.source_trade_id
                      ?? "-"
                    }
                  </p>
                </td>

                <td className="px-4 py-4 align-top">
                  <p
                    className="font-mono text-xs text-blue-300"
                    title={order.source_token_mint}
                  >
                    {shortenLiveAddress(
                      order.source_token_mint
                    )}
                  </p>
                </td>

                <td className="px-4 py-4 text-right align-top font-semibold text-slate-200">
                  {formatLiveNumber(
                    order.requested_value_sol,
                    6
                  )}
                </td>

                <td className="px-4 py-4 text-right align-top font-mono text-xs text-slate-400">
                  {formatLiveNumber(
                    order.actual_output_amount_raw
                    ?? order.expected_output_amount_raw,
                    0
                  )}
                </td>

                <td
                  className={`px-4 py-4 text-right align-top font-bold ${
                    Number(
                      order.realized_pnl_sol
                    ) > 0
                      ? "text-green-300"
                      : Number(
                          order.realized_pnl_sol
                        ) < 0
                        ? "text-red-300"
                        : "text-slate-400"
                  }`}
                >
                  {formatLiveNumber(
                    order.realized_pnl_sol,
                    6
                  )}
                </td>

                <td className="px-4 py-4 align-top text-slate-300">
                  {order.router ?? "-"}
                </td>

                <td className="px-4 py-4 align-top text-xs text-slate-400">
                  {formatLiveDate(
                    order.created_at
                  )}
                </td>
              </tr>
            ))}

            {orders.length === 0 && (
              <tr>
                <td
                  colSpan="9"
                  className="px-6 py-14 text-center text-slate-500"
                >
                  Nessun ordine trovato con i filtri selezionati.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}


export default LiveTradingOrders; 