import LiveTradingBadge from "./LiveTradingBadge";
import {
  formatLiveDate,
  formatLiveNumber,
  shortenLiveAddress,
} from "./liveTradingFormatters";


function LiveTradingPositions({
  positions,
  filters,
  loading,
  activeGeneration,
  streamExecutionEnabled,
  closingPositionId,
  onFilterChange,
  onRefresh,
  onCloseDryRun,
}) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block">
          <span className="text-xs font-bold uppercase tracking-wide text-slate-500">
            Stato posizione
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
            <option value="OPEN">
              OPEN
            </option>
            <option value="CLOSED">
              CLOSED
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
              : "Aggiorna posizioni"}
          </button>
        </div>
      </div>

      {streamExecutionEnabled && (
        <div className="rounded-xl border border-amber-700 bg-amber-950/40 px-4 py-3 text-sm text-amber-300">
          Per chiudere manualmente una posizione DRY_RUN, disattiva prima lo stream automatico e salva la policy.
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-slate-700">
        <table className="min-w-[1120px] w-full text-left text-sm">
          <thead className="bg-slate-950/80 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">
                Token
              </th>
              <th className="px-4 py-3">
                Stato
              </th>
              <th className="px-4 py-3 text-right">
                Quantità raw
              </th>
              <th className="px-4 py-3 text-right">
                Cost basis SOL
              </th>
              <th className="px-4 py-3 text-right">
                PnL realizzato SOL
              </th>
              <th className="px-4 py-3">
                Ultimo BUY
              </th>
              <th className="px-4 py-3">
                Ultimo SELL
              </th>
              <th className="px-4 py-3">
                Aggiornata
              </th>
              <th className="px-4 py-3 text-right">
                Azione
              </th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-800 bg-slate-900/50">
            {positions.map(
              (position) => {
                const isActiveDryRun = (
                  position.mode === "DRY_RUN"
                  && position.status === "OPEN"
                  && Number(position.generation)
                    === Number(activeGeneration)
                );

                const isClosing = (
                  Number(closingPositionId)
                    === Number(position.id)
                );

                return (
                  <tr
                    key={position.id}
                    className="transition hover:bg-slate-800/70"
                  >
                    <td className="px-4 py-4">
                      <p
                        className="font-mono text-xs text-blue-300"
                        title={position.token_mint}
                      >
                        {shortenLiveAddress(
                          position.token_mint,
                          9,
                          8
                        )}
                      </p>

                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <LiveTradingBadge
                          value={position.mode}
                        />

                        <span className="rounded-full border border-slate-600 bg-slate-950 px-2.5 py-1 text-xs font-bold text-slate-400">
                          Gen #{position.generation}
                        </span>
                      </div>
                    </td>

                    <td className="px-4 py-4">
                      <LiveTradingBadge
                        value={position.status}
                      />
                    </td>

                    <td className="px-4 py-4 text-right font-mono text-xs text-slate-300">
                      {formatLiveNumber(
                        position.quantity_raw,
                        0
                      )}
                    </td>

                    <td className="px-4 py-4 text-right font-semibold text-slate-200">
                      {formatLiveNumber(
                        position.cost_basis_sol,
                        6
                      )}
                    </td>

                    <td
                      className={`px-4 py-4 text-right font-bold ${
                        Number(
                          position.realized_pnl_sol
                        ) > 0
                          ? "text-green-300"
                          : Number(
                              position.realized_pnl_sol
                            ) < 0
                            ? "text-red-300"
                            : "text-slate-400"
                      }`}
                    >
                      {formatLiveNumber(
                        position.realized_pnl_sol,
                        6
                      )}
                    </td>

                    <td
                      className="px-4 py-4 font-mono text-xs text-slate-400"
                      title={
                        position.last_buy_signature
                        ?? ""
                      }
                    >
                      {shortenLiveAddress(
                        position.last_buy_signature,
                        8,
                        6
                      )}
                    </td>

                    <td
                      className="px-4 py-4 font-mono text-xs text-slate-400"
                      title={
                        position.last_sell_signature
                        ?? ""
                      }
                    >
                      {shortenLiveAddress(
                        position.last_sell_signature,
                        8,
                        6
                      )}
                    </td>

                    <td className="px-4 py-4 text-xs text-slate-400">
                      {formatLiveDate(
                        position.updated_at
                      )}
                    </td>

                    <td className="px-4 py-4 text-right">
                      {isActiveDryRun ? (
                        <button
                          type="button"
                          onClick={() =>
                            onCloseDryRun(
                              position
                            )
                          }
                          disabled={
                            loading
                            || streamExecutionEnabled
                            || Boolean(
                              closingPositionId
                            )
                          }
                          className="rounded-xl border border-amber-700 bg-amber-950/50 px-3 py-2 text-xs font-bold text-amber-300 transition hover:bg-amber-900/60 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {isClosing
                            ? "Chiusura..."
                            : streamExecutionEnabled
                              ? "Spegni stream"
                              : "Chiudi DRY_RUN"}
                        </button>
                      ) : (
                        <span className="text-xs text-slate-600">
                          —
                        </span>
                      )}
                    </td>
                  </tr>
                );
              }
            )}

            {positions.length === 0 && (
              <tr>
                <td
                  colSpan="9"
                  className="px-6 py-14 text-center text-slate-500"
                >
                  Nessuna posizione trovata con i filtri selezionati.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}


export default LiveTradingPositions;
