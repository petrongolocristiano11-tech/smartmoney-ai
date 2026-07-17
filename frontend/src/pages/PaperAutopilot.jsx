import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  getPaperAccounts,
  getPaperAutopilot,
  runPaperAutopilot,
  updatePaperAutopilotPolicy,
} from "../services/api";


const ACCESS_KEY_STORAGE =
  "smartmoney-paper-access-key";

const AUTO_REFRESH_MS = 30_000;


const NUMERIC_FIELDS = new Set([
  "min_signal_score",
  "min_evidence_score",
  "min_buyers",
  "max_signal_age_hours",
  "min_smart_volume_share_percent",
  "max_volume_concentration_percent",
  "max_signals_per_run",
  "max_entries_per_run",
  "max_entries_per_day",
  "token_cooldown_hours",
  "max_position_percent_of_equity",
  "max_total_exposure_percent",
  "minimum_cash_reserve_percent",
  "minimum_order_size_sol",
  "stop_loss_percent",
  "take_profit_percent",
  "trailing_stop_percent",
  "max_holding_hours",
  "slippage_percent",
  "fee_percent",
  "max_consecutive_errors",
]);


const LIST_FIELDS = new Set([
  "blocked_risk_flags",
  "excluded_token_mints",
]);


const FIELD_GROUPS = [
  {
    title: "Filtri segnali",
    fields: [
      [
        "min_signal_score",
        "Signal score minimo",
      ],
      [
        "min_evidence_score",
        "Evidence score minimo",
      ],
      [
        "min_buyers",
        "Buyer minimi",
        "integer",
      ],
      [
        "minimum_confidence",
        "Confidenza minima",
        "confidence",
      ],
      [
        "max_signal_age_hours",
        "Età massima segnale (ore)",
      ],
      [
        "min_smart_volume_share_percent",
        "Smart volume minimo %",
      ],
      [
        "max_volume_concentration_percent",
        "Concentrazione massima %",
      ],
      [
        "max_signals_per_run",
        "Segnali analizzati per run",
        "integer",
      ],
    ],
  },
  {
    title: "Entrate e capitale",
    fields: [
      [
        "max_entries_per_run",
        "Entrate massime per run",
        "integer",
      ],
      [
        "max_entries_per_day",
        "Entrate massime al giorno",
        "integer",
      ],
      [
        "token_cooldown_hours",
        "Cooldown token (ore)",
        "integer",
      ],
      [
        "minimum_order_size_sol",
        "Ordine minimo SOL",
      ],
      [
        "max_position_percent_of_equity",
        "Massimo posizione % equity",
      ],
      [
        "max_total_exposure_percent",
        "Esposizione totale massima %",
      ],
      [
        "minimum_cash_reserve_percent",
        "Riserva minima liquidità %",
      ],
    ],
  },
  {
    title: "Uscite ed esecuzione",
    fields: [
      [
        "stop_loss_percent",
        "Stop-loss %",
      ],
      [
        "take_profit_percent",
        "Take-profit %",
      ],
      [
        "trailing_stop_enabled",
        "Trailing stop attivo",
        "boolean",
      ],
      [
        "trailing_stop_percent",
        "Trailing stop %",
      ],
      [
        "max_holding_hours",
        "Durata massima (ore)",
        "integer",
      ],
      [
        "slippage_percent",
        "Slippage simulato %",
      ],
      [
        "fee_percent",
        "Commissione simulata %",
      ],
      [
        "max_consecutive_errors",
        "Errori prima della pausa",
        "integer",
      ],
    ],
  },
];


function formatNumber(
  value,
  digits = 4
) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "0";
  }

  return number.toLocaleString(
    "it-IT",
    {
      maximumFractionDigits:
        digits,
    }
  );
}


function formatDate(value) {
  if (!value) {
    return "-";
  }

  return new Date(
    value
  ).toLocaleString("it-IT");
}


function shortenAddress(value) {
  const text = String(
    value ?? ""
  );

  if (text.length <= 18) {
    return text || "-";
  }

  return `${text.slice(
    0,
    8
  )}...${text.slice(-7)}`;
}


function parseApiError(error) {
  const detail =
    error?.response?.data?.detail;

  if (typeof detail === "string") {
    return detail;
  }

  if (
    detail
    && typeof detail === "object"
  ) {
    return (
      detail.message
      ?? detail.code
      ?? "Operazione non riuscita."
    );
  }

  return (
    error?.message
    ?? "Operazione non riuscita."
  );
}


function splitList(value) {
  return String(
    value ?? ""
  )
    .split(/[\n,]+/)
    .map(
      (item) => item.trim()
    )
    .filter(Boolean);
}


function policyToForm(policy) {
  const form = {};

  for (
    const field
    of NUMERIC_FIELDS
  ) {
    form[field] = String(
      policy[field]
    );
  }

  form.minimum_confidence =
    policy.minimum_confidence;

  form.trailing_stop_enabled =
    Boolean(
      policy.trailing_stop_enabled
    );

  form.blocked_risk_flags = (
    policy.blocked_risk_flags
    ?? []
  ).join("\n");

  form.excluded_token_mints = (
    policy.excluded_token_mints
    ?? []
  ).join("\n");

  return form;
}


function formToPayload(form) {
  const payload = {};

  for (
    const [field, value]
    of Object.entries(form)
  ) {
    if (
      NUMERIC_FIELDS.has(field)
    ) {
      payload[field] = Number(value);
    } else if (
      LIST_FIELDS.has(field)
    ) {
      payload[field] =
        splitList(value);
    } else {
      payload[field] = value;
    }
  }

  return payload;
}


function StatusBadge({ status }) {
  const classes = {
    ENABLED:
      "border-green-700 bg-green-950/50 text-green-300",
    PAUSED:
      "border-yellow-700 bg-yellow-950/50 text-yellow-300",
    DISABLED:
      "border-slate-600 bg-slate-800 text-slate-300",
    ACTIVE:
      "border-blue-700 bg-blue-950/50 text-blue-300",
    CLOSED:
      "border-slate-600 bg-slate-800 text-slate-300",
    COMPLETED:
      "border-green-700 bg-green-950/50 text-green-300",
    PARTIAL:
      "border-yellow-700 bg-yellow-950/50 text-yellow-300",
    FAILED:
      "border-red-700 bg-red-950/50 text-red-300",
    SKIPPED:
      "border-slate-600 bg-slate-800 text-slate-300",
    RUNNING:
      "border-blue-700 bg-blue-950/50 text-blue-300",
  };

  return (
    <span
      className={`rounded-full border px-3 py-1 text-xs font-semibold ${
        classes[status]
        ?? classes.DISABLED
      }`}
    >
      {status}
    </span>
  );
}


function Metric({
  label,
  value,
  className = "",
}) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900 p-5">
      <p className="text-sm text-slate-400">
        {label}
      </p>

      <p
        className={`mt-2 text-2xl font-bold ${className}`}
      >
        {value}
      </p>
    </div>
  );
}


function PolicyField({
  label,
  kind,
  value,
  onChange,
}) {
  if (kind === "confidence") {
    return (
      <label className="block">
        <span className="text-xs text-slate-400">
          {label}
        </span>

        <select
          value={value}
          onChange={(event) =>
            onChange(
              event.target.value
            )
          }
          className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
        >
          <option value="LOW">
            LOW
          </option>

          <option value="MEDIUM">
            MEDIUM
          </option>

          <option value="HIGH">
            HIGH
          </option>
        </select>
      </label>
    );
  }

  if (kind === "boolean") {
    return (
      <label className="flex items-center gap-3 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) =>
            onChange(
              event.target.checked
            )
          }
        />

        <span className="text-sm text-slate-300">
          {label}
        </span>
      </label>
    );
  }

  return (
    <label className="block">
      <span className="text-xs text-slate-400">
        {label}
      </span>

      <input
        type="number"
        step={
          kind === "integer"
            ? "1"
            : "any"
        }
        value={value}
        onChange={(event) =>
          onChange(
            event.target.value
          )
        }
        className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
      />
    </label>
  );
}


function DataTable({
  title,
  empty,
  columns,
  rows,
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-900">
      <div className="border-b border-slate-700 p-5">
        <h2 className="text-xl font-bold">
          {title}
        </h2>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[950px]">
          <thead className="bg-slate-800">
            <tr>
              {columns.map(
                (column) => (
                  <th
                    key={column}
                    className="p-4 text-center"
                  >
                    {column}
                  </th>
                )
              )}
            </tr>
          </thead>

          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td
                  colSpan={
                    columns.length
                  }
                  className="p-10 text-center text-slate-400"
                >
                  {empty}
                </td>
              </tr>
            ) : (
              rows.map(
                (
                  row,
                  rowIndex
                ) => (
                  <tr
                    key={rowIndex}
                    className="border-t border-slate-700"
                  >
                    {row.map(
                      (
                        cell,
                        cellIndex
                      ) => (
                        <td
                          key={
                            cellIndex
                          }
                          className="p-4 text-center text-sm text-slate-300"
                        >
                          {cell}
                        </td>
                      )
                    )}
                  </tr>
                )
              )
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}


function PaperAutopilot() {
  const [accessKey, setAccessKey] =
    useState(
      sessionStorage.getItem(
        ACCESS_KEY_STORAGE
      ) ?? ""
    );

  const [keyInput, setKeyInput] =
    useState("");

  const [accounts, setAccounts] =
    useState([]);

  const [
    selectedAccountId,
    setSelectedAccountId,
  ] = useState(null);

  const [dashboard, setDashboard] =
    useState(null);

  const [
    policyForm,
    setPolicyForm,
  ] = useState(null);

  const [
    policyDirty,
    setPolicyDirty,
  ] = useState(false);

  const [loading, setLoading] =
    useState(false);

  const [
    busyAction,
    setBusyAction,
  ] = useState("");

  const [error, setError] =
    useState("");

  const [message, setMessage] =
    useState("");


  const handleError = useCallback(
    (requestError) => {
      if (
        requestError
          ?.response
          ?.status
        === 401
      ) {
        sessionStorage.removeItem(
          ACCESS_KEY_STORAGE
        );

        setAccessKey("");
        setAccounts([]);
        setDashboard(null);
        setPolicyForm(null);

        setError(
          "Chiave Paper Trading "
          + "non valida."
        );

        return;
      }

      setError(
        parseApiError(
          requestError
        )
      );
    },
    []
  );


  const applyDashboard =
    useCallback(
      (
        data,
        resetForm = true
      ) => {
        setDashboard(data);

        if (resetForm) {
          setPolicyForm(
            policyToForm(
              data.policy
            )
          );

          setPolicyDirty(false);
        }
      },
      []
    );


  const loadDashboard =
    useCallback(
      async (
        key,
        accountId,
        resetForm = true
      ) => {
        const response =
          await getPaperAutopilot(
            key,
            accountId
          );

        applyDashboard(
          response.data,
          resetForm
        );
      },
      [applyDashboard]
    );


  const loadAccounts =
    useCallback(
      async (
        key,
        preferredId = null
      ) => {
        setLoading(true);
        setError("");

        try {
          const response =
            await getPaperAccounts(
              key
            );

          const rows =
            response.data
              .accounts
            ?? [];

          setAccounts(rows);

          const ids = new Set(
            rows.map(
              (row) =>
                row.account.id
            )
          );

          const requested =
            Number(preferredId);

          const nextId =
            ids.has(requested)
              ? requested
              : rows[0]
                  ?.account
                  ?.id
                ?? null;

          setSelectedAccountId(
            nextId
          );

          if (nextId) {
            await loadDashboard(
              key,
              nextId,
              true
            );
          } else {
            setDashboard(null);
            setPolicyForm(null);
          }
        } catch (requestError) {
          handleError(
            requestError
          );
        } finally {
          setLoading(false);
        }
      },
      [
        handleError,
        loadDashboard,
      ]
    );


  useEffect(() => {
    if (accessKey) {
      loadAccounts(
        accessKey,
        null
      );
    }
  }, [
    accessKey,
    loadAccounts,
  ]);


  useEffect(() => {
    if (
      !accessKey
      || !selectedAccountId
    ) {
      return undefined;
    }

    const intervalId =
      window.setInterval(
        async () => {
          try {
            await loadDashboard(
              accessKey,
              selectedAccountId,
              !policyDirty
            );

            const response =
              await getPaperAccounts(
                accessKey
              );

            setAccounts(
              response.data
                .accounts
              ?? []
            );
          } catch (
            requestError
          ) {
            handleError(
              requestError
            );
          }
        },
        AUTO_REFRESH_MS
      );

    return () => {
      window.clearInterval(
        intervalId
      );
    };
  }, [
    accessKey,
    selectedAccountId,
    policyDirty,
    handleError,
    loadDashboard,
  ]);


  const activePositions =
    useMemo(
      () =>
        dashboard
          ?.managed_positions
          ?.filter(
            (item) =>
              item.status
              === "ACTIVE"
          )
        ?? [],
      [dashboard]
    );


  function connect(event) {
    event.preventDefault();

    const value =
      keyInput.trim();

    if (!value) {
      setError(
        "Inserisci la chiave "
        + "Paper Trading."
      );

      return;
    }

    sessionStorage.setItem(
      ACCESS_KEY_STORAGE,
      value
    );

    setError("");
    setAccessKey(value);
  }


  function disconnect() {
    sessionStorage.removeItem(
      ACCESS_KEY_STORAGE
    );

    setAccessKey("");
    setKeyInput("");
    setAccounts([]);
    setSelectedAccountId(null);
    setDashboard(null);
    setPolicyForm(null);
    setPolicyDirty(false);
    setError("");
    setMessage("");
  }


  async function selectAccount(
    accountId
  ) {
    setSelectedAccountId(
      accountId
    );

    setLoading(true);
    setError("");

    try {
      await loadDashboard(
        accessKey,
        accountId,
        true
      );
    } catch (requestError) {
      handleError(
        requestError
      );
    } finally {
      setLoading(false);
    }
  }


  function changeField(
    field,
    value
  ) {
    setPolicyForm(
      (current) => ({
        ...current,
        [field]: value,
      })
    );

    setPolicyDirty(true);
  }


  async function savePolicy(
    event
  ) {
    event.preventDefault();

    setBusyAction("save");
    setError("");
    setMessage("");

    try {
      const response =
        await updatePaperAutopilotPolicy(
          accessKey,
          selectedAccountId,
          formToPayload(
            policyForm
          )
        );

      applyDashboard(
        response.data,
        true
      );

      setMessage(
        "Politica Autopilot "
        + "salvata."
      );
    } catch (requestError) {
      handleError(
        requestError
      );
    } finally {
      setBusyAction("");
    }
  }


  async function setStatus(status) {
    setBusyAction(
      `status-${status}`
    );

    setError("");
    setMessage("");

    try {
      const response =
        await updatePaperAutopilotPolicy(
          accessKey,
          selectedAccountId,
          { status }
        );

      applyDashboard(
        response.data,
        true
      );

      setMessage(
        `Autopilot impostato su ${status}.`
      );
    } catch (requestError) {
      handleError(
        requestError
      );
    } finally {
      setBusyAction("");
    }
  }


  async function runNow() {
    setBusyAction("run");
    setError("");
    setMessage("");

    try {
      const response =
        await runPaperAutopilot(
          accessKey,
          selectedAccountId
        );

      setMessage(
        "Esecuzione completata: "
        + `${response.data.run.entries_opened} entrate, `
        + `${response.data.run.exits_closed} uscite.`
      );

      await loadDashboard(
        accessKey,
        selectedAccountId,
        true
      );

      const accountsResponse =
        await getPaperAccounts(
          accessKey
        );

      setAccounts(
        accountsResponse
          .data
          .accounts
        ?? []
      );
    } catch (requestError) {
      handleError(
        requestError
      );
    } finally {
      setBusyAction("");
    }
  }


  async function refreshNow() {
    setBusyAction("refresh");
    setError("");

    try {
      await loadDashboard(
        accessKey,
        selectedAccountId,
        !policyDirty
      );

      setMessage(
        "Dashboard aggiornata."
      );
    } catch (requestError) {
      handleError(
        requestError
      );
    } finally {
      setBusyAction("");
    }
  }


  if (!accessKey) {
    return (
      <main className="min-h-screen bg-slate-950 p-4 text-white sm:p-8">
        <form
          onSubmit={connect}
          className="mx-auto mt-24 max-w-xl rounded-2xl border border-slate-700 bg-slate-900 p-8"
        >
          <p className="text-sm font-semibold uppercase tracking-wider text-blue-300">
            Accesso protetto
          </p>

          <h1 className="mt-2 text-3xl font-bold">
            Paper Autopilot
          </h1>

          <p className="mt-3 text-slate-400">
            Usa la stessa chiave della
            Paper Trading Console.
          </p>

          {error && (
            <div className="mt-5 rounded-lg border border-red-700 bg-red-950/40 p-4 text-red-300">
              {error}
            </div>
          )}

          <input
            type="password"
            value={keyInput}
            onChange={(event) =>
              setKeyInput(
                event.target.value
              )
            }
            className="mt-6 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3"
            placeholder="Chiave Paper Trading"
          />

          <button
            type="submit"
            className="mt-4 w-full rounded-lg bg-blue-600 px-5 py-3 font-semibold"
          >
            Accedi
          </button>
        </form>
      </main>
    );
  }


  const account =
    dashboard?.account;

  const summary =
    dashboard?.summary;

  const policy =
    dashboard?.policy;


  return (
    <main className="min-h-screen bg-slate-950 p-4 text-white sm:p-8">
      <div className="mx-auto max-w-7xl">
        <header className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wider text-blue-300">
              Automazione senza fondi reali
            </p>

            <h1 className="mt-2 text-3xl font-bold">
              Paper Autopilot
            </h1>

            <p className="mt-2 text-slate-400">
              Entrate automatiche e gestione
              di stop-loss, take-profit,
              trailing stop e durata massima.
            </p>
          </div>

          <div className="flex gap-3">
            <button
              type="button"
              onClick={refreshNow}
              className="rounded-lg border border-blue-700 px-4 py-2 text-blue-300"
            >
              Aggiorna
            </button>

            <button
              type="button"
              onClick={disconnect}
              className="rounded-lg border border-slate-600 px-4 py-2 text-slate-300"
            >
              Disconnetti
            </button>
          </div>
        </header>

        {error && (
          <div className="mt-6 rounded-lg border border-red-700 bg-red-950/40 p-4 text-red-300">
            {error}
          </div>
        )}

        {message && (
          <div className="mt-6 rounded-lg border border-green-700 bg-green-950/40 p-4 text-green-300">
            {message}
          </div>
        )}

        <div className="mt-8 grid gap-6 xl:grid-cols-[300px_1fr]">
          <aside className="rounded-xl border border-slate-700 bg-slate-900 p-5">
            <h2 className="text-lg font-bold">
              Conti virtuali
            </h2>

            <div className="mt-4 space-y-3">
              {accounts.map(
                (row) => (
                  <button
                    type="button"
                    key={
                      row.account.id
                    }
                    onClick={() =>
                      selectAccount(
                        row.account.id
                      )
                    }
                    className={`w-full rounded-xl border p-4 text-left ${
                      row.account.id
                      === selectedAccountId
                        ? "border-blue-500 bg-blue-950/40"
                        : "border-slate-700 bg-slate-950"
                    }`}
                  >
                    <p className="font-semibold">
                      {row.account.name}
                    </p>

                    <p className="mt-2 text-sm text-slate-400">
                      {formatNumber(
                        row.summary
                          .equity_sol
                      )}{" "}
                      SOL
                    </p>
                  </button>
                )
              )}

              {accounts.length
                === 0 && (
                <p className="text-sm text-slate-400">
                  Nessun conto disponibile.
                </p>
              )}
            </div>
          </aside>

          <div className="min-w-0 space-y-6">
            {(
              !account
              || !summary
              || !policy
              || !policyForm
            ) ? (
              <div className="rounded-xl border border-slate-700 bg-slate-900 p-10 text-center text-slate-400">
                {loading
                  ? "Caricamento..."
                  : "Seleziona un conto."}
              </div>
            ) : (
              <>
                <section className="rounded-xl border border-slate-700 bg-slate-900 p-6">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                    <div>
                      <div className="flex items-center gap-3">
                        <h2 className="text-2xl font-bold">
                          {account.name}
                        </h2>

                        <StatusBadge
                          status={
                            policy.status
                          }
                        />
                      </div>

                      <p className="mt-2 text-sm text-slate-400">
                        Ultima esecuzione:{" "}
                        {formatDate(
                          policy.last_run_at
                        )}
                      </p>

                      {policy.paused_reason
                        && (
                          <p className="mt-2 text-sm text-yellow-300">
                            {
                              policy
                                .paused_reason
                            }
                          </p>
                        )}
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          setStatus(
                            "ENABLED"
                          )
                        }
                        className="rounded-lg border border-green-700 px-3 py-2 text-sm text-green-300"
                      >
                        Abilita
                      </button>

                      <button
                        type="button"
                        onClick={() =>
                          setStatus(
                            "PAUSED"
                          )
                        }
                        className="rounded-lg border border-yellow-700 px-3 py-2 text-sm text-yellow-300"
                      >
                        Pausa entrate
                      </button>

                      <button
                        type="button"
                        onClick={() =>
                          setStatus(
                            "DISABLED"
                          )
                        }
                        className="rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-300"
                      >
                        Disabilita
                      </button>

                      <button
                        type="button"
                        onClick={runNow}
                        disabled={
                          policy.status
                          === "DISABLED"
                          || busyAction
                          === "run"
                        }
                        className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold disabled:opacity-40"
                      >
                        {busyAction
                          === "run"
                          ? "Esecuzione..."
                          : "Esegui ora"}
                      </button>
                    </div>
                  </div>
                </section>

                <section className="grid grid-cols-2 gap-4 lg:grid-cols-5">
                  <Metric
                    label="Equity"
                    value={`${formatNumber(
                      summary.equity_sol
                    )} SOL`}
                    className="text-blue-300"
                  />

                  <Metric
                    label="Liquidità"
                    value={`${formatNumber(
                      summary
                        .cash_balance_sol
                    )} SOL`}
                  />

                  <Metric
                    label="Posizioni gestite"
                    value={String(
                      activePositions.length
                    )}
                  />

                  <Metric
                    label="Errori consecutivi"
                    value={`${policy.consecutive_errors}/${policy.max_consecutive_errors}`}
                  />

                  <Metric
                    label="Rendimento"
                    value={`${formatNumber(
                      summary
                        .total_return_percent,
                      2
                    )}%`}
                  />
                </section>

                <form
                  onSubmit={savePolicy}
                  className="space-y-6"
                >
                  {FIELD_GROUPS.map(
                    (group) => (
                      <section
                        key={
                          group.title
                        }
                        className="rounded-xl border border-slate-700 bg-slate-900 p-5"
                      >
                        <h2 className="text-xl font-bold">
                          {group.title}
                        </h2>

                        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                          {group.fields.map(
                            ([
                              field,
                              label,
                              kind,
                            ]) => (
                              <PolicyField
                                key={
                                  field
                                }
                                label={
                                  label
                                }
                                kind={
                                  kind
                                }
                                value={
                                  policyForm[
                                    field
                                  ]
                                }
                                onChange={(
                                  value
                                ) =>
                                  changeField(
                                    field,
                                    value
                                  )
                                }
                              />
                            )
                          )}
                        </div>
                      </section>
                    )
                  )}

                  <section className="grid gap-6 lg:grid-cols-2">
                    {[
                      [
                        "blocked_risk_flags",
                        "Risk flag bloccati",
                      ],
                      [
                        "excluded_token_mints",
                        "Token esclusi",
                      ],
                    ].map(
                      ([
                        field,
                        label,
                      ]) => (
                        <label
                          key={
                            field
                          }
                          className="rounded-xl border border-slate-700 bg-slate-900 p-5"
                        >
                          <span className="font-bold">
                            {label}
                          </span>

                          <textarea
                            rows={7}
                            value={
                              policyForm[
                                field
                              ]
                            }
                            onChange={(
                              event
                            ) =>
                              changeField(
                                field,
                                event
                                  .target
                                  .value
                              )
                            }
                            className="mt-4 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 font-mono text-sm"
                          />
                        </label>
                      )
                    )}
                  </section>

                  <div className="flex items-center gap-3">
                    <button
                      type="submit"
                      disabled={
                        !policyDirty
                        || busyAction
                        === "save"
                      }
                      className="rounded-lg bg-blue-600 px-5 py-3 font-semibold disabled:opacity-40"
                    >
                      {busyAction
                        === "save"
                        ? "Salvataggio..."
                        : "Salva politica completa"}
                    </button>

                    {policyDirty && (
                      <span className="text-sm text-yellow-300">
                        Modifiche non salvate
                      </span>
                    )}
                  </div>
                </form>

                <DataTable
                  title="Posizioni gestite"
                  empty="Nessuna posizione gestita."
                  columns={[
                    "Token",
                    "Stato",
                    "Entrata",
                    "Picco",
                    "Stop",
                    "Take profit",
                    "Scadenza",
                    "Uscita",
                  ]}
                  rows={
                    dashboard
                      .managed_positions
                      .map(
                        (item) => [
                          shortenAddress(
                            item.token_mint
                          ),
                          (
                            <StatusBadge
                              key={`position-${item.id}`}
                              status={
                                item.status
                              }
                            />
                          ),
                          formatNumber(
                            item
                              .entry_price_sol,
                            10
                          ),
                          formatNumber(
                            item
                              .peak_price_sol,
                            10
                          ),
                          formatNumber(
                            item
                              .stop_loss_price_sol,
                            10
                          ),
                          formatNumber(
                            item
                              .take_profit_price_sol,
                            10
                          ),
                          formatDate(
                            item
                              .max_holding_until
                          ),
                          item
                            .exit_reason
                          ?? "-",
                        ]
                      )
                  }
                />

                <DataTable
                  title="Ultime esecuzioni"
                  empty="Nessuna esecuzione."
                  columns={[
                    "Stato",
                    "Trigger",
                    "Segnali",
                    "Entrate",
                    "Uscite",
                    "Errori",
                    "Inizio",
                    "Fine",
                  ]}
                  rows={
                    dashboard.runs.map(
                      (item) => [
                        (
                          <StatusBadge
                            key={`run-${item.id}`}
                            status={
                              item.status
                            }
                          />
                        ),
                        item.trigger,
                        item
                          .signals_evaluated,
                        item
                          .entries_opened,
                        item
                          .exits_closed,
                        item
                          .errors_count,
                        formatDate(
                          item.started_at
                        ),
                        formatDate(
                          item.finished_at
                        ),
                      ]
                    )
                  }
                />

                <DataTable
                  title="Registro decisioni"
                  empty="Nessuna decisione registrata."
                  columns={[
                    "Azione",
                    "Token",
                    "Codice",
                    "Score",
                    "Evidence",
                    "Buyer",
                    "Valore SOL",
                    "Data",
                  ]}
                  rows={
                    dashboard
                      .decisions
                      .map(
                        (item) => [
                          item.action,
                          shortenAddress(
                            item.token_mint
                          ),
                          item
                            .reason_code,
                          item
                            .signal_score
                          ?? "-",
                          item
                            .evidence_score
                          ?? "-",
                          item.buyers
                          ?? "-",
                          item.value_sol
                          == null
                            ? "-"
                            : formatNumber(
                                item
                                  .value_sol
                              ),
                          formatDate(
                            item.created_at
                          ),
                        ]
                      )
                  }
                />
              </>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}


export default PaperAutopilot; 