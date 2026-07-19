import { useState } from "react";
import {
  formatLiveDate,
  formatLiveNumber,
} from "./liveTradingFormatters";


function parseWallets(value) {
  const seen = new Set();

  return String(value ?? "")
    .split(/[\n,\s]+/)
    .map((wallet) => wallet.trim())
    .filter((wallet) => {
      if (!wallet || seen.has(wallet)) {
        return false;
      }

      seen.add(wallet);
      return true;
    });
}


function LiveTradingDryRunReset({
  policy,
  status,
  resetting,
  onReset,
}) {
  const [wallets, setWallets] =
    useState(
      () => (
        policy.source_wallets ?? []
      ).join("\n")
    );

  const [startStream, setStartStream] =
    useState(false);

  const [buyEnabled, setBuyEnabled] =
    useState(true);

  const [sellEnabled, setSellEnabled] =
    useState(true);

  const [confirmation, setConfirmation] =
    useState("");

  const parsedWallets = parseWallets(
    wallets
  );

  const streamMustBeStopped =
    Boolean(
      policy.stream_execution_enabled
    );

  const modeIsValid =
    policy.mode === "DRY_RUN";

  const canSubmit =
    modeIsValid
    && !streamMustBeStopped
    && confirmation === "RESET DRY RUN"
    && (
      !startStream
      || parsedWallets.length > 0
    )
    && !resetting;

  async function handleSubmit(event) {
    event.preventDefault();

    if (!canSubmit) {
      return;
    }

    const completed = await onReset({
      confirmation,
      source_wallets: parsedWallets,
      start_stream: startStream,
      buy_enabled: buyEnabled,
      sell_enabled: sellEnabled,
    });

    if (completed) {
      setConfirmation("");
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-5"
    >
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-slate-700 bg-slate-900/70 p-4">
          <p className="text-xs font-bold uppercase tracking-wide text-slate-500">
            Generazione attiva
          </p>

          <p className="mt-2 text-2xl font-bold text-blue-300">
            #{status.active_generation
              ?? policy.dry_run_generation}
          </p>
        </div>

        <div className="rounded-xl border border-slate-700 bg-slate-900/70 p-4">
          <p className="text-xs font-bold uppercase tracking-wide text-slate-500">
            Avviata
          </p>

          <p className="mt-2 font-bold text-white">
            {formatLiveDate(
              status.generation_started_at
              ?? policy.dry_run_started_at
            )}
          </p>
        </div>

        <div className="rounded-xl border border-slate-700 bg-slate-900/70 p-4">
          <p className="text-xs font-bold uppercase tracking-wide text-slate-500">
            Posizioni da archiviare
          </p>

          <p className="mt-2 text-2xl font-bold text-white">
            {status.open_positions}
          </p>
        </div>

        <div className="rounded-xl border border-slate-700 bg-slate-900/70 p-4">
          <p className="text-xs font-bold uppercase tracking-wide text-slate-500">
            Esposizione da archiviare
          </p>

          <p className="mt-2 text-2xl font-bold text-amber-300">
            {formatLiveNumber(
              status.total_exposure_sol,
              6
            )} SOL
          </p>
        </div>
      </div>

      <div className="rounded-xl border border-amber-800 bg-amber-950/30 p-5">
        <h3 className="font-bold text-amber-200">
          Cosa fa il reset controllato
        </h3>

        <p className="mt-2 text-sm leading-6 text-amber-200/70">
          Archivia le posizioni aperte della generazione attuale, mantiene ordini ed eventi nello storico e avvia una generazione DRY_RUN vuota. Non cancella dati e non usa denaro reale.
        </p>
      </div>

      {!modeIsValid && (
        <div className="rounded-xl border border-red-800 bg-red-950/40 p-4 text-sm text-red-300">
          Imposta prima la modalità DRY_RUN.
        </div>
      )}

      {streamMustBeStopped && (
        <div className="rounded-xl border border-red-800 bg-red-950/40 p-4 text-sm text-red-300">
          Disattiva e salva prima lo stream automatico. Il backend rifiuta il reset mentre il worker può ancora creare ordini.
        </div>
      )}

      <label className="block rounded-xl border border-slate-700 bg-slate-900/70 p-4">
        <span className="text-sm font-bold text-slate-200">
          Wallet della nuova generazione
        </span>

        <span className="mt-1 block text-xs leading-5 text-slate-500">
          Puoi lasciarli vuoti e configurare la policy in seguito. Per avviare subito lo stream serve almeno un wallet.
        </span>

        <textarea
          rows="4"
          value={wallets}
          onChange={(event) =>
            setWallets(
              event.target.value
            )
          }
          placeholder="Un wallet Solana per riga"
          className="mt-3 w-full resize-y rounded-xl border border-slate-600 bg-slate-950 px-3 py-3 font-mono text-sm text-white outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
        />
      </label>

      <div className="grid gap-3 md:grid-cols-3">
        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-700 bg-slate-900/70 p-4">
          <input
            type="checkbox"
            checked={buyEnabled}
            onChange={(event) =>
              setBuyEnabled(
                event.target.checked
              )
            }
            className="mt-1 h-4 w-4 accent-blue-600"
          />

          <span>
            <span className="block font-semibold text-slate-200">
              BUY attivi
            </span>

            <span className="mt-1 block text-xs leading-5 text-slate-500">
              Consenti nuovi acquisti simulati.
            </span>
          </span>
        </label>

        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-700 bg-slate-900/70 p-4">
          <input
            type="checkbox"
            checked={sellEnabled}
            onChange={(event) =>
              setSellEnabled(
                event.target.checked
              )
            }
            className="mt-1 h-4 w-4 accent-blue-600"
          />

          <span>
            <span className="block font-semibold text-slate-200">
              SELL attivi
            </span>

            <span className="mt-1 block text-xs leading-5 text-slate-500">
              Consenti la chiusura delle nuove posizioni.
            </span>
          </span>
        </label>

        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-700 bg-slate-900/70 p-4">
          <input
            type="checkbox"
            checked={startStream}
            onChange={(event) =>
              setStartStream(
                event.target.checked
              )
            }
            className="mt-1 h-4 w-4 accent-blue-600"
          />

          <span>
            <span className="block font-semibold text-slate-200">
              Avvia subito lo stream
            </span>

            <span className="mt-1 block text-xs leading-5 text-slate-500">
              Lascia spento per controllare prima il nuovo wallet.
            </span>
          </span>
        </label>
      </div>

      <div className="rounded-xl border border-red-800 bg-red-950/30 p-5">
        <label className="block">
          <span className="font-bold text-red-200">
            Conferma testuale
          </span>

          <span className="mt-1 block text-sm leading-6 text-red-300/70">
            Scrivi esattamente RESET DRY RUN.
          </span>

          <input
            type="text"
            value={confirmation}
            onChange={(event) =>
              setConfirmation(
                event.target.value
              )
            }
            placeholder="RESET DRY RUN"
            className="mt-3 w-full rounded-xl border border-red-800 bg-slate-950 px-4 py-3 font-mono text-white outline-none focus:ring-2 focus:ring-red-500/30"
          />
        </label>

        <button
          type="submit"
          disabled={!canSubmit}
          className="mt-4 rounded-xl bg-amber-600 px-5 py-3 font-bold text-white transition hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {resetting
            ? "Reset in corso..."
            : "Archivia e crea nuova generazione"}
        </button>
      </div>
    </form>
  );
}


export default LiveTradingDryRunReset;
