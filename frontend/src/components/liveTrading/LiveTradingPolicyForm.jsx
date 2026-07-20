import { useState } from "react";


const NUMERIC_FIELDS = [
  "fixed_buy_size_sol",
  "source_trade_percentage",
  "sell_position_percentage",
  "max_order_size_sol",
  "max_daily_buy_sol",
  "max_daily_loss_sol",
  "max_total_exposure_sol",
  "min_wallet_reserve_sol",
  "max_slippage_bps",
  "max_price_impact_percent",
  "min_source_trade_sol",
  "max_source_trade_age_seconds",
  "max_consecutive_failures",
  "take_profit_percent",
  "stop_loss_percent",
  "trailing_stop_percent",
  "max_position_age_minutes",
  "auto_exit_position_percentage",
  "max_open_positions",
  "max_token_exposure_sol",
  "max_daily_orders",
  "max_portfolio_drawdown_percent",
  "loss_streak_cooldown_threshold",
  "cooldown_after_loss_minutes",
];


const FIELD_GROUPS = [
  {
    title: "Dimensionamento ordini",
    description:
      "Definisce quanto capitale usare per ogni copia e quanto vendere dalle posizioni aperte.",
    fields: [
      {
        name: "sizing_mode",
        label: "Metodo dimensionamento BUY",
        type: "select",
        options: [
          ["FIXED", "Importo fisso"],
          [
            "SOURCE_PERCENTAGE",
            "Percentuale del trade sorgente",
          ],
        ],
      },
      {
        name: "fixed_buy_size_sol",
        label: "Importo fisso BUY (SOL)",
        step: "0.001",
      },
      {
        name: "source_trade_percentage",
        label: "Percentuale trade sorgente",
        step: "0.1",
      },
      {
        name: "sell_position_percentage",
        label: "Quota posizione venduta (%)",
        step: "0.1",
      },
    ],
  },
  {
    title: "Limiti capitale e rischio",
    description:
      "Blocca automaticamente ordini troppo grandi, esposizione e perdite oltre i limiti impostati.",
    fields: [
      {
        name: "max_order_size_sol",
        label: "Massimo singolo ordine (SOL)",
        step: "0.001",
      },
      {
        name: "max_daily_buy_sol",
        label: "Massimo acquisti giornalieri (SOL)",
        step: "0.001",
      },
      {
        name: "max_daily_loss_sol",
        label: "Perdita giornaliera massima (SOL)",
        step: "0.001",
      },
      {
        name: "max_total_exposure_sol",
        label: "Esposizione totale massima (SOL)",
        step: "0.001",
      },
      {
        name: "min_wallet_reserve_sol",
        label: "Riserva minima wallet (SOL)",
        step: "0.001",
      },
      {
        name: "max_consecutive_failures",
        label: "Errori prima del kill switch",
        step: "1",
      },
    ],
  },
  {
    title: "Uscite automatiche",
    description:
      "Parametri usati dal monitor per take profit, stop loss, trailing stop e chiusura temporale.",
    fields: [
      { name: "take_profit_percent", label: "Take profit (%)", step: "0.1" },
      { name: "stop_loss_percent", label: "Stop loss (%)", step: "0.1" },
      { name: "trailing_stop_percent", label: "Trailing stop (%)", step: "0.1" },
      { name: "max_position_age_minutes", label: "Durata massima posizione (min)", step: "1" },
      { name: "auto_exit_position_percentage", label: "Quota venduta all'uscita (%)", step: "0.1" },
    ],
  },
  {
    title: "Rischio portafoglio",
    description:
      "Limiti su posizioni, token, ordini, drawdown e cooldown dopo perdite consecutive.",
    fields: [
      { name: "max_open_positions", label: "Posizioni aperte massime", step: "1" },
      { name: "max_token_exposure_sol", label: "Esposizione massima per token (SOL)", step: "0.001" },
      { name: "max_daily_orders", label: "Ordini giornalieri massimi", step: "1" },
      { name: "max_portfolio_drawdown_percent", label: "Drawdown portafoglio massimo (%)", step: "0.1" },
      { name: "loss_streak_cooldown_threshold", label: "Perdite consecutive prima cooldown", step: "1" },
      { name: "cooldown_after_loss_minutes", label: "Durata cooldown (min)", step: "1" },
    ],
  },
  {
    title: "Qualità esecuzione",
    description:
      "Scarta segnali vecchi, trade troppo piccoli e quotazioni Jupiter con impatto eccessivo.",
    fields: [
      {
        name: "max_slippage_bps",
        label: "Slippage massimo (bps)",
        step: "1",
      },
      {
        name: "max_price_impact_percent",
        label: "Price impact massimo (%)",
        step: "0.1",
      },
      {
        name: "min_source_trade_sol",
        label: "Trade sorgente minimo (SOL)",
        step: "0.001",
      },
      {
        name: "max_source_trade_age_seconds",
        label: "Età massima trade (secondi)",
        step: "1",
      },
    ],
  },
];


function policyToForm(policy) {
  const nextForm = {
    mode: policy.mode,
    stream_execution_enabled:
      Boolean(
        policy.stream_execution_enabled
      ),
    buy_enabled:
      Boolean(policy.buy_enabled),
    sell_enabled:
      Boolean(policy.sell_enabled),
    automatic_exits_enabled: Boolean(policy.automatic_exits_enabled),
    take_profit_enabled: Boolean(policy.take_profit_enabled),
    stop_loss_enabled: Boolean(policy.stop_loss_enabled),
    trailing_stop_enabled: Boolean(policy.trailing_stop_enabled),
    time_exit_enabled: Boolean(policy.time_exit_enabled),
    sizing_mode:
      policy.sizing_mode,
    source_wallets: (
      policy.source_wallets ?? []
    ).join("\n"),
    live_confirmation: "",
  };

  for (const field of NUMERIC_FIELDS) {
    nextForm[field] = String(
      policy[field]
    );
  }

  return nextForm;
}


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


function buildPayload(
  form,
  policy
) {
  const payload = {
    stream_execution_enabled:
      Boolean(
        form.stream_execution_enabled
      ),
    source_wallets:
      parseWallets(
        form.source_wallets
      ),
    buy_enabled:
      Boolean(form.buy_enabled),
    sell_enabled:
      Boolean(form.sell_enabled),
    automatic_exits_enabled: Boolean(form.automatic_exits_enabled),
    take_profit_enabled: Boolean(form.take_profit_enabled),
    stop_loss_enabled: Boolean(form.stop_loss_enabled),
    trailing_stop_enabled: Boolean(form.trailing_stop_enabled),
    time_exit_enabled: Boolean(form.time_exit_enabled),
    sizing_mode:
      form.sizing_mode,
  };

  for (const field of NUMERIC_FIELDS) {
    payload[field] = Number(
      form[field]
    );
  }

  if (form.mode !== policy.mode) {
    payload.mode = form.mode;

    if (form.mode === "LIVE") {
      payload.confirmation =
        form.live_confirmation;
    }
  }

  return payload;
}


function ToggleField({
  checked,
  label,
  description,
  disabled = false,
  onChange,
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-700 bg-slate-900/70 p-4">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) =>
          onChange(
            event.target.checked
          )
        }
        className="mt-1 h-4 w-4 accent-blue-600 disabled:cursor-not-allowed"
      />

      <span>
        <span className="block font-semibold text-slate-200">
          {label}
        </span>

        <span className="mt-1 block text-xs leading-5 text-slate-500">
          {description}
        </span>
      </span>
    </label>
  );
}


function FormField({
  field,
  value,
  onChange,
}) {
  const commonClasses =
    "mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-3 py-2.5 text-white outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20";

  return (
    <label className="block">
      <span className="text-sm font-semibold text-slate-300">
        {field.label}
      </span>

      {field.type === "select" ? (
        <select
          value={value}
          onChange={(event) =>
            onChange(event.target.value)
          }
          className={commonClasses}
        >
          {field.options.map(
            ([optionValue, label]) => (
              <option
                key={optionValue}
                value={optionValue}
              >
                {label}
              </option>
            )
          )}
        </select>
      ) : (
        <input
          type="number"
          value={value}
          min="0"
          step={field.step ?? "any"}
          required
          onChange={(event) =>
            onChange(event.target.value)
          }
          className={commonClasses}
        />
      )}
    </label>
  );
}


function LiveTradingPolicyForm({
  policy,
  saving,
  onSave,
}) {
  const [form, setForm] = useState(
    () => policyToForm(policy)
  );


  function updateField(
    field,
    value
  ) {
    setForm((current) => ({
      ...current,
      [field]: value,
    }));
  }

  async function handleSubmit(event) {
    event.preventDefault();

    await onSave(
      buildPayload(form, policy)
    );
  }

  const changingToLive =
    form.mode === "LIVE"
    && policy.mode !== "LIVE";

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-6"
    >
      <div className="grid gap-4 lg:grid-cols-3">
        <label className="block rounded-xl border border-slate-700 bg-slate-900/70 p-4">
          <span className="text-sm font-bold text-slate-200">
            Modalità operativa
          </span>

          <select
            value={form.mode}
            onChange={(event) =>
              updateField(
                "mode",
                event.target.value
              )
            }
            className="mt-3 w-full rounded-xl border border-slate-600 bg-slate-950 px-3 py-2.5 font-semibold text-white outline-none focus:border-blue-500"
          >
            <option value="DISABLED">
              DISABLED — nessuna esecuzione
            </option>

            <option value="DRY_RUN">
              DRY_RUN — quotazioni reali, zero denaro
            </option>

            <option value="LIVE">
              LIVE — denaro reale
            </option>
          </select>
        </label>

        <ToggleField
          checked={form.buy_enabled}
          label="Copy BUY"
          description="Permette al motore di copiare gli acquisti dei wallet autorizzati."
          onChange={(value) =>
            updateField(
              "buy_enabled",
              value
            )
          }
        />

        <ToggleField
          checked={form.sell_enabled}
          label="Copy SELL"
          description="Permette al motore di ridurre le posizioni quando il wallet sorgente vende."
          onChange={(value) =>
            updateField(
              "sell_enabled",
              value
            )
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
        <ToggleField
          checked={
            form.stream_execution_enabled
          }
          disabled={
            form.mode === "DISABLED"
          }
          label="Esecuzione automatica dallo stream"
          description="Quando attiva, gli swap Helius dei wallet in allowlist vengono inviati al motore copy-trading."
          onChange={(value) =>
            updateField(
              "stream_execution_enabled",
              value
            )
          }
        />

        <label className="block rounded-xl border border-slate-700 bg-slate-900/70 p-4">
          <span className="text-sm font-bold text-slate-200">
            Wallet sorgente autorizzati
          </span>

          <span className="mt-1 block text-xs leading-5 text-slate-500">
            Un indirizzo Solana per riga. Solo questi wallet potranno generare ordini.
          </span>

          <textarea
            rows="5"
            value={form.source_wallets}
            onChange={(event) =>
              updateField(
                "source_wallets",
                event.target.value
              )
            }
            placeholder="Wallet Solana 1&#10;Wallet Solana 2"
            className="mt-3 w-full resize-y rounded-xl border border-slate-600 bg-slate-950 px-3 py-3 font-mono text-sm text-white outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
          />
        </label>
      </div>

      <div className="rounded-xl border border-slate-700 bg-slate-900/50 p-5">
        <h3 className="font-bold text-white">Motore automatico di uscita</h3>
        <p className="mt-1 text-sm leading-6 text-slate-500">
          Inizia disattivato. Dopo i test DRY_RUN puoi abilitare il monitor e scegliere le condizioni operative.
        </p>
        <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <ToggleField checked={form.automatic_exits_enabled} label="Uscite automatiche" description="Permette al monitor di generare ordini SELL autonomi." onChange={(value) => updateField("automatic_exits_enabled", value)} />
          <ToggleField checked={form.take_profit_enabled} label="Take profit" description="Chiude quando il ROI raggiunge la soglia positiva." onChange={(value) => updateField("take_profit_enabled", value)} />
          <ToggleField checked={form.stop_loss_enabled} label="Stop loss" description="Chiude quando il ROI scende sotto la perdita massima." onChange={(value) => updateField("stop_loss_enabled", value)} />
          <ToggleField checked={form.trailing_stop_enabled} label="Trailing stop" description="Segue il massimo valore raggiunto dalla posizione." onChange={(value) => updateField("trailing_stop_enabled", value)} />
          <ToggleField checked={form.time_exit_enabled} label="Chiusura temporale" description="Chiude le posizioni oltre la durata massima." onChange={(value) => updateField("time_exit_enabled", value)} />
        </div>
      </div>

      {FIELD_GROUPS.map((group) => (
        <div
          key={group.title}
          className="rounded-xl border border-slate-700 bg-slate-900/50 p-5"
        >
          <h3 className="font-bold text-white">
            {group.title}
          </h3>

          <p className="mt-1 text-sm leading-6 text-slate-500">
            {group.description}
          </p>

          <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {group.fields.map(
              (field) => (
                <FormField
                  key={field.name}
                  field={field}
                  value={form[field.name]}
                  onChange={(value) =>
                    updateField(
                      field.name,
                      value
                    )
                  }
                />
              )
            )}
          </div>
        </div>
      ))}

      {changingToLive && (
        <div className="rounded-xl border border-red-700 bg-red-950/50 p-5">
          <h3 className="font-bold text-red-200">
            Conferma attivazione con denaro reale
          </h3>

          <p className="mt-2 text-sm leading-6 text-red-300/80">
            Scrivi esattamente ENABLE LIVE TRADING. Il backend consentirà il passaggio solo se wallet, chiave privata e Jupiter sono configurati.
          </p>

          <input
            type="text"
            value={form.live_confirmation}
            onChange={(event) =>
              updateField(
                "live_confirmation",
                event.target.value
              )
            }
            placeholder="ENABLE LIVE TRADING"
            required
            className="mt-4 w-full rounded-xl border border-red-700 bg-slate-950 px-4 py-3 font-mono text-white outline-none focus:ring-2 focus:ring-red-500/30"
          />
        </div>
      )}

      <div className="flex flex-col gap-3 border-t border-slate-700 pt-5 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs leading-5 text-slate-500">
          La chiave privata non viene mai inserita o mostrata in questa dashboard.
        </p>

        <button
          type="submit"
          disabled={saving}
          className="rounded-xl bg-blue-600 px-5 py-3 font-bold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving
            ? "Salvataggio..."
            : "Salva policy completa"}
        </button>
      </div>
    </form>
  );
}


export default LiveTradingPolicyForm; 