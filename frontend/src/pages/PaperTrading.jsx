import {
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  buyPaperToken,
  createPaperAccount,
  getPaperAccount,
  getPaperAccounts,
  markPaperPosition,
  resetPaperAccount,
  sellPaperToken,
  updatePaperAccount,
} from "../services/api";


const ACCESS_KEY_STORAGE =
  "smartmoney-paper-access-key";


const EMPTY_CREATE_FORM = {
  name: "Conto principale",
  starting_balance_sol: "10",
  max_position_size_sol: "0.5",
  max_open_positions: "3",
  daily_loss_limit_sol: "1",
};


const EMPTY_BUY_FORM = {
  token_mint: "",
  value_sol: "0.1",
  market_price_sol: "",
  slippage_percent: "0.5",
  fee_percent: "0.25",
  signal_score: "",
  reason: "",
};


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
      maximumFractionDigits: digits,
    }
  );
}


function formatDate(value) {
  if (!value) {
    return "-";
  }

  return new Date(value)
    .toLocaleString("it-IT");
}


function shortenAddress(
  address,
  start = 8,
  end = 7
) {
  const normalized = String(
    address ?? ""
  );

  if (
    normalized.length
    <= start + end + 3
  ) {
    return normalized || "-";
  }

  return `${normalized.slice(
    0,
    start
  )}...${normalized.slice(-end)}`;
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


function MetricCard({
  label,
  value,
  subtitle = "",
  valueClassName = "",
}) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-5">
      <p className="text-sm text-slate-400">
        {label}
      </p>

      <p
        className={`mt-2 text-2xl font-bold ${valueClassName}`}
      >
        {value}
      </p>

      {subtitle && (
        <p className="mt-2 text-xs text-slate-500">
          {subtitle}
        </p>
      )}
    </div>
  );
}


function StatusBadge({ status }) {
  const classes = {
    ACTIVE:
      "border-green-700 bg-green-900/40 text-green-300",
    PAUSED:
      "border-yellow-700 bg-yellow-900/40 text-yellow-300",
    STOPPED:
      "border-red-700 bg-red-900/40 text-red-300",
    OPEN:
      "border-blue-700 bg-blue-900/40 text-blue-300",
    CLOSED:
      "border-slate-600 bg-slate-700 text-slate-300",
    FILLED:
      "border-green-700 bg-green-900/40 text-green-300",
    REJECTED:
      "border-red-700 bg-red-900/40 text-red-300",
  };

  return (
    <span
      className={`rounded-full border px-3 py-1 text-xs font-semibold ${
        classes[status]
        ?? classes.CLOSED
      }`}
    >
      {status}
    </span>
  );
}


function PaperTrading() {
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

  const [detail, setDetail] =
    useState(null);

  const [createForm, setCreateForm] =
    useState(EMPTY_CREATE_FORM);

  const [settingsForm, setSettingsForm] =
    useState(null);

  const [buyForm, setBuyForm] =
    useState(EMPTY_BUY_FORM);

  const [
    positionDrafts,
    setPositionDrafts,
  ] = useState({});

  const [loading, setLoading] =
    useState(false);

  const [busyAction, setBusyAction] =
    useState("");

  const [error, setError] =
    useState("");

  const [message, setMessage] =
    useState("");


  function handleRequestError(
    requestError
  ) {
    const status =
      requestError?.response?.status;

    if (status === 401) {
      sessionStorage.removeItem(
        ACCESS_KEY_STORAGE
      );

      setAccessKey("");
      setKeyInput("");
      setAccounts([]);
      setDetail(null);

      setError(
        "Chiave di accesso non valida."
      );

      return;
    }

    setError(
      parseApiError(requestError)
    );
  }


  async function loadDetail(
    key,
    accountId
  ) {
    const response =
      await getPaperAccount(
        key,
        accountId
      );

    setDetail(response.data);

    const account =
      response.data.account;

    setSettingsForm({
      name: account.name,
      max_position_size_sol:
        String(
          account
            .max_position_size_sol
        ),
      max_open_positions:
        String(
          account
            .max_open_positions
        ),
      daily_loss_limit_sol:
        String(
          account
            .daily_loss_limit_sol
        ),
    });

    const nextDrafts = {};

    for (
      const position
      of response.data.positions
    ) {
      nextDrafts[position.id] = {
        market_price_sol:
          position.last_price_sol > 0
            ? String(
                position
                  .last_price_sol
              )
            : "",
        quantity: "",
      };
    }

    setPositionDrafts(nextDrafts);
  }


  async function loadAccounts(
    key,
    preferredAccountId = null
  ) {
    setLoading(true);
    setError("");

    try {
      const response =
        await getPaperAccounts(key);

      const accountRows =
        response.data.accounts ?? [];

      setAccounts(accountRows);

      const existingIds = new Set(
        accountRows.map(
          (row) => row.account.id
        )
      );

      const preferredId = Number(
        preferredAccountId
        ?? selectedAccountId
      );

      const nextAccountId =
        existingIds.has(preferredId)
          ? preferredId
          : accountRows[0]
              ?.account
              ?.id
            ?? null;

      setSelectedAccountId(
        nextAccountId
      );

      if (nextAccountId) {
        await loadDetail(
          key,
          nextAccountId
        );
      } else {
        setDetail(null);
        setSettingsForm(null);
      }
    } catch (requestError) {
      handleRequestError(
        requestError
      );
    } finally {
      setLoading(false);
    }
  }


  useEffect(() => {
    if (accessKey) {
      loadAccounts(accessKey);
    }
  }, [accessKey]);


  const openPositions = useMemo(
    () =>
      detail?.positions?.filter(
        (position) =>
          position.status === "OPEN"
      ) ?? [],
    [detail]
  );


  async function runAction(
    actionName,
    operation,
    successMessage,
    preferredAccountId =
      selectedAccountId
  ) {
    setBusyAction(actionName);
    setError("");
    setMessage("");

    try {
      await operation();

      setMessage(successMessage);

      await loadAccounts(
        accessKey,
        preferredAccountId
      );
    } catch (requestError) {
      handleRequestError(
        requestError
      );
    } finally {
      setBusyAction("");
    }
  }


  function connectConsole(event) {
    event.preventDefault();

    const normalizedKey =
      keyInput.trim();

    if (!normalizedKey) {
      setError(
        "Inserisci la chiave di accesso."
      );

      return;
    }

    sessionStorage.setItem(
      ACCESS_KEY_STORAGE,
      normalizedKey
    );

    setError("");
    setAccessKey(normalizedKey);
  }


  function disconnectConsole() {
    sessionStorage.removeItem(
      ACCESS_KEY_STORAGE
    );

    setAccessKey("");
    setKeyInput("");
    setAccounts([]);
    setDetail(null);
    setMessage("");
    setError("");
  }


  async function selectAccount(
    accountId
  ) {
    setSelectedAccountId(accountId);
    setLoading(true);
    setError("");

    try {
      await loadDetail(
        accessKey,
        accountId
      );
    } catch (requestError) {
      handleRequestError(
        requestError
      );
    } finally {
      setLoading(false);
    }
  }


  function updateCreateForm(
    field,
    value
  ) {
    setCreateForm(
      (current) => ({
        ...current,
        [field]: value,
      })
    );
  }


  async function submitCreateAccount(
    event
  ) {
    event.preventDefault();

    let createdAccountId = null;

    await runAction(
      "create-account",
      async () => {
        const response =
          await createPaperAccount(
            accessKey,
            {
              name: createForm.name,
              starting_balance_sol:
                Number(
                  createForm
                    .starting_balance_sol
                ),
              max_position_size_sol:
                Number(
                  createForm
                    .max_position_size_sol
                ),
              max_open_positions:
                Number(
                  createForm
                    .max_open_positions
                ),
              daily_loss_limit_sol:
                Number(
                  createForm
                    .daily_loss_limit_sol
                ),
            }
          );

        createdAccountId =
          response.data.account.id;

        setCreateForm(
          EMPTY_CREATE_FORM
        );
      },
      "Conto virtuale creato.",
      createdAccountId
    );

    if (createdAccountId) {
      await loadAccounts(
        accessKey,
        createdAccountId
      );
    }
  }


  async function submitSettings(
    event
  ) {
    event.preventDefault();

    if (
      !selectedAccountId
      || !settingsForm
    ) {
      return;
    }

    await runAction(
      "settings",
      () =>
        updatePaperAccount(
          accessKey,
          selectedAccountId,
          {
            name:
              settingsForm.name,
            max_position_size_sol:
              Number(
                settingsForm
                  .max_position_size_sol
              ),
            max_open_positions:
              Number(
                settingsForm
                  .max_open_positions
              ),
            daily_loss_limit_sol:
              Number(
                settingsForm
                  .daily_loss_limit_sol
              ),
          }
        ),
      "Impostazioni aggiornate."
    );
  }


  async function changeStatus(status) {
    await runAction(
      `status-${status}`,
      () =>
        updatePaperAccount(
          accessKey,
          selectedAccountId,
          { status }
        ),
      `Conto impostato su ${status}.`
    );
  }


  async function submitBuy(event) {
    event.preventDefault();

    await runAction(
      "buy",
      () =>
        buyPaperToken(
          accessKey,
          selectedAccountId,
          {
            token_mint:
              buyForm.token_mint,
            value_sol:
              Number(
                buyForm.value_sol
              ),
            market_price_sol:
              Number(
                buyForm
                  .market_price_sol
              ),
            slippage_percent:
              Number(
                buyForm
                  .slippage_percent
              ),
            fee_percent:
              Number(
                buyForm.fee_percent
              ),
            signal_score:
              buyForm.signal_score
                ? Number(
                    buyForm
                      .signal_score
                  )
                : null,
            reason:
              buyForm.reason || null,
          }
        ),
      "Acquisto virtuale eseguito."
    );

    setBuyForm(EMPTY_BUY_FORM);
  }


  function updatePositionDraft(
    positionId,
    field,
    value
  ) {
    setPositionDrafts(
      (current) => ({
        ...current,
        [positionId]: {
          ...current[positionId],
          [field]: value,
        },
      })
    );
  }


  async function markPosition(
    position
  ) {
    const draft =
      positionDrafts[position.id];

    await runAction(
      `mark-${position.id}`,
      () =>
        markPaperPosition(
          accessKey,
          selectedAccountId,
          {
            token_mint:
              position.token_mint,
            market_price_sol:
              Number(
                draft
                  ?.market_price_sol
              ),
          }
        ),
      "Prezzo della posizione aggiornato."
    );
  }


  async function sellPosition(
    position
  ) {
    const draft =
      positionDrafts[position.id];

    await runAction(
      `sell-${position.id}`,
      () =>
        sellPaperToken(
          accessKey,
          selectedAccountId,
          {
            token_mint:
              position.token_mint,
            market_price_sol:
              Number(
                draft
                  ?.market_price_sol
              ),
            quantity:
              draft?.quantity
                ? Number(
                    draft.quantity
                  )
                : null,
            slippage_percent: 0.5,
            fee_percent: 0.25,
            reason:
              "Vendita dalla Paper Trading Console",
          }
        ),
      draft?.quantity
        ? "Vendita parziale eseguita."
        : "Posizione chiusa."
    );
  }


  async function resetAccount() {
    const accountName =
      detail?.account?.name;

    const confirmation =
      window.prompt(
        "Per azzerare conto, ordini e "
        + "posizioni, scrivi esattamente:\n"
        + accountName
      );

    if (confirmation === null) {
      return;
    }

    await runAction(
      "reset",
      () =>
        resetPaperAccount(
          accessKey,
          selectedAccountId,
          confirmation
        ),
      "Conto virtuale azzerato."
    );
  }


  if (!accessKey) {
    return (
      <main className="min-h-screen bg-slate-950 p-4 text-white sm:p-8">
        <div className="mx-auto flex min-h-[70vh] max-w-xl items-center">
          <form
            onSubmit={connectConsole}
            className="w-full rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-xl sm:p-8"
          >
            <p className="text-sm font-semibold uppercase tracking-wider text-blue-300">
              Accesso protetto
            </p>

            <h1 className="mt-2 text-3xl font-bold">
              Paper Trading Console
            </h1>

            <p className="mt-3 text-slate-400">
              Inserisci la chiave configurata
              sul backend. La chiave rimane
              nella sessione del browser e
              non viene inserita nella build.
            </p>

            {error && (
              <div className="mt-5 rounded-lg border border-red-700 bg-red-950/40 p-4 text-red-300">
                {error}
              </div>
            )}

            <label className="mt-6 block">
              <span className="text-sm text-slate-300">
                Chiave Paper Trading
              </span>

              <input
                type="password"
                value={keyInput}
                onChange={(event) =>
                  setKeyInput(
                    event.target.value
                  )
                }
                autoComplete="current-password"
                className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-4 py-3 outline-none focus:border-blue-500"
              />
            </label>

            <button
              type="submit"
              className="mt-5 w-full rounded-lg bg-blue-600 px-5 py-3 font-semibold hover:bg-blue-700"
            >
              Accedi alla console
            </button>
          </form>
        </div>
      </main>
    );
  }


  const account = detail?.account;
  const summary = detail?.summary;


  return (
    <main className="min-h-screen bg-slate-950 p-4 text-white sm:p-8">
      <div className="mx-auto max-w-7xl">
        <header className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wider text-blue-300">
              Simulazione protetta
            </p>

            <h1 className="mt-2 text-3xl font-bold">
              Paper Trading Console
            </h1>

            <p className="mt-2 text-slate-400">
              Nessuna chiave privata e nessun
              fondo reale vengono utilizzati.
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() =>
                loadAccounts(
                  accessKey,
                  selectedAccountId
                )
              }
              disabled={loading}
              className="rounded-lg border border-blue-700 bg-blue-950/40 px-4 py-2 text-blue-300 disabled:opacity-50"
            >
              {loading
                ? "Aggiornamento..."
                : "Aggiorna"}
            </button>

            <button
              type="button"
              onClick={disconnectConsole}
              className="rounded-lg border border-slate-600 px-4 py-2 text-slate-300 hover:bg-slate-800"
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

        <div className="mt-8 grid gap-6 xl:grid-cols-[320px_1fr]">
          <aside className="space-y-6">
            <section className="rounded-xl border border-slate-700 bg-slate-900 p-5">
              <h2 className="text-lg font-bold">
                Conti virtuali
              </h2>

              <div className="mt-4 space-y-3">
                {accounts.length === 0 ? (
                  <p className="text-sm text-slate-400">
                    Nessun conto creato.
                  </p>
                ) : (
                  accounts.map((row) => {
                    const selected =
                      row.account.id
                      === selectedAccountId;

                    return (
                      <button
                        type="button"
                        key={row.account.id}
                        onClick={() =>
                          selectAccount(
                            row.account.id
                          )
                        }
                        className={`w-full rounded-xl border p-4 text-left transition ${
                          selected
                            ? "border-blue-500 bg-blue-950/40"
                            : "border-slate-700 bg-slate-950 hover:border-slate-600"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <p className="font-semibold">
                            {row.account.name}
                          </p>

                          <StatusBadge
                            status={
                              row.account
                                .status
                            }
                          />
                        </div>

                        <p className="mt-3 text-sm text-slate-400">
                          Equity
                        </p>

                        <p className="font-bold">
                          {formatNumber(
                            row.summary
                              .equity_sol
                          )}{" "}
                          SOL
                        </p>

                        <p
                          className={`mt-1 text-sm ${
                            row.summary
                              .total_return_percent
                            >= 0
                              ? "text-green-300"
                              : "text-red-300"
                          }`}
                        >
                          {formatNumber(
                            row.summary
                              .total_return_percent,
                            2
                          )}
                          %
                        </p>
                      </button>
                    );
                  })
                )}
              </div>
            </section>

            <form
              onSubmit={submitCreateAccount}
              className="rounded-xl border border-slate-700 bg-slate-900 p-5"
            >
              <h2 className="text-lg font-bold">
                Nuovo conto
              </h2>

              <div className="mt-4 space-y-3">
                {Object.entries({
                  name: "Nome",
                  starting_balance_sol:
                    "Saldo iniziale SOL",
                  max_position_size_sol:
                    "Massimo per posizione",
                  max_open_positions:
                    "Posizioni massime",
                  daily_loss_limit_sol:
                    "Perdita giornaliera massima",
                }).map(
                  ([field, label]) => (
                    <label
                      key={field}
                      className="block"
                    >
                      <span className="text-xs text-slate-400">
                        {label}
                      </span>

                      <input
                        type={
                          field === "name"
                            ? "text"
                            : "number"
                        }
                        step="any"
                        value={
                          createForm[field]
                        }
                        onChange={(event) =>
                          updateCreateForm(
                            field,
                            event.target
                              .value
                          )
                        }
                        className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 outline-none focus:border-blue-500"
                      />
                    </label>
                  )
                )}
              </div>

              <button
                type="submit"
                disabled={
                  busyAction
                  === "create-account"
                }
                className="mt-4 w-full rounded-lg bg-blue-600 px-4 py-2 font-semibold hover:bg-blue-700 disabled:opacity-50"
              >
                Crea conto
              </button>
            </form>
          </aside>

          <div className="min-w-0">
            {!account || !summary ? (
              <div className="rounded-xl border border-slate-700 bg-slate-900 p-10 text-center text-slate-400">
                Crea o seleziona un conto.
              </div>
            ) : (
              <div className="space-y-6">
                <section className="rounded-xl border border-slate-700 bg-slate-900 p-6">
                  <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-3">
                        <h2 className="text-2xl font-bold">
                          {account.name}
                        </h2>

                        <StatusBadge
                          status={account.status}
                        />
                      </div>

                      <p className="mt-2 text-sm text-slate-400">
                        Conto #{account.id} ·
                        creato{" "}
                        {formatDate(
                          account.created_at
                        )}
                      </p>
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          changeStatus(
                            "ACTIVE"
                          )
                        }
                        className="rounded-lg border border-green-700 px-3 py-2 text-sm text-green-300"
                      >
                        Attiva
                      </button>

                      <button
                        type="button"
                        onClick={() =>
                          changeStatus(
                            "PAUSED"
                          )
                        }
                        className="rounded-lg border border-yellow-700 px-3 py-2 text-sm text-yellow-300"
                      >
                        Pausa
                      </button>

                      <button
                        type="button"
                        onClick={() =>
                          changeStatus(
                            "STOPPED"
                          )
                        }
                        className="rounded-lg border border-red-700 px-3 py-2 text-sm text-red-300"
                      >
                        Ferma
                      </button>

                      <button
                        type="button"
                        onClick={resetAccount}
                        className="rounded-lg bg-red-700 px-3 py-2 text-sm font-semibold hover:bg-red-800"
                      >
                        Azzera
                      </button>
                    </div>
                  </div>
                </section>

                <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                  <MetricCard
                    label="Equity"
                    value={`${formatNumber(
                      summary.equity_sol
                    )} SOL`}
                    valueClassName="text-blue-300"
                  />

                  <MetricCard
                    label="Saldo disponibile"
                    value={`${formatNumber(
                      summary
                        .cash_balance_sol
                    )} SOL`}
                  />

                  <MetricCard
                    label="PnL realizzato"
                    value={`${formatNumber(
                      summary
                        .realized_pnl_sol
                    )} SOL`}
                    valueClassName={
                      summary
                        .realized_pnl_sol
                      >= 0
                        ? "text-green-300"
                        : "text-red-300"
                    }
                  />

                  <MetricCard
                    label="PnL non realizzato"
                    value={`${formatNumber(
                      summary
                        .unrealized_pnl_sol
                    )} SOL`}
                    valueClassName={
                      summary
                        .unrealized_pnl_sol
                      >= 0
                        ? "text-green-300"
                        : "text-red-300"
                    }
                  />

                  <MetricCard
                    label="Rendimento"
                    value={`${formatNumber(
                      summary
                        .total_return_percent,
                      2
                    )}%`}
                    valueClassName={
                      summary
                        .total_return_percent
                      >= 0
                        ? "text-green-300"
                        : "text-red-300"
                    }
                  />

                  <MetricCard
                    label="Valore posizioni"
                    value={`${formatNumber(
                      summary
                        .market_value_sol
                    )} SOL`}
                  />

                  <MetricCard
                    label="Posizioni"
                    value={`${summary.open_positions}/${summary.max_open_positions}`}
                  />

                  <MetricCard
                    label="Perdita giornaliera"
                    value={`${formatNumber(
                      summary
                        .daily_loss_used_sol
                    )} / ${formatNumber(
                      summary
                        .daily_loss_limit_sol
                    )} SOL`}
                  />
                </section>

                <div className="grid gap-6 lg:grid-cols-2">
                  <form
                    onSubmit={submitSettings}
                    className="rounded-xl border border-slate-700 bg-slate-900 p-5"
                  >
                    <h2 className="text-xl font-bold">
                      Controlli di rischio
                    </h2>

                    {settingsForm && (
                      <div className="mt-4 grid gap-4 sm:grid-cols-2">
                        {Object.entries({
                          name: "Nome",
                          max_position_size_sol:
                            "Massimo per posizione",
                          max_open_positions:
                            "Posizioni massime",
                          daily_loss_limit_sol:
                            "Perdita giornaliera massima",
                        }).map(
                          ([field, label]) => (
                            <label
                              key={field}
                              className="block"
                            >
                              <span className="text-xs text-slate-400">
                                {label}
                              </span>

                              <input
                                type={
                                  field
                                  === "name"
                                    ? "text"
                                    : "number"
                                }
                                step="any"
                                value={
                                  settingsForm[
                                    field
                                  ]
                                }
                                onChange={(
                                  event
                                ) =>
                                  setSettingsForm(
                                    (
                                      current
                                    ) => ({
                                      ...current,
                                      [field]:
                                        event
                                          .target
                                          .value,
                                    })
                                  )
                                }
                                className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 outline-none focus:border-blue-500"
                              />
                            </label>
                          )
                        )}
                      </div>
                    )}

                    <button
                      type="submit"
                      className="mt-4 rounded-lg bg-blue-600 px-4 py-2 font-semibold hover:bg-blue-700"
                    >
                      Salva limiti
                    </button>
                  </form>

                  <form
                    onSubmit={submitBuy}
                    className="rounded-xl border border-slate-700 bg-slate-900 p-5"
                  >
                    <h2 className="text-xl font-bold">
                      Acquisto virtuale
                    </h2>

                    <div className="mt-4 grid gap-4 sm:grid-cols-2">
                      {Object.entries({
                        token_mint:
                          "Token mint",
                        value_sol:
                          "Importo SOL",
                        market_price_sol:
                          "Prezzo token in SOL",
                        slippage_percent:
                          "Slippage %",
                        fee_percent:
                          "Commissione %",
                        signal_score:
                          "Signal score",
                        reason:
                          "Motivazione",
                      }).map(
                        ([field, label]) => (
                          <label
                            key={field}
                            className={
                              field
                              === "token_mint"
                              || field
                              === "reason"
                                ? "block sm:col-span-2"
                                : "block"
                            }
                          >
                            <span className="text-xs text-slate-400">
                              {label}
                            </span>

                            <input
                              type={
                                [
                                  "token_mint",
                                  "reason",
                                ].includes(
                                  field
                                )
                                  ? "text"
                                  : "number"
                              }
                              step="any"
                              value={
                                buyForm[field]
                              }
                              onChange={(
                                event
                              ) =>
                                setBuyForm(
                                  (
                                    current
                                  ) => ({
                                    ...current,
                                    [field]:
                                      event
                                        .target
                                        .value,
                                  })
                                )
                              }
                              className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 outline-none focus:border-blue-500"
                            />
                          </label>
                        )
                      )}
                    </div>

                    <button
                      type="submit"
                      disabled={
                        account.status
                        !== "ACTIVE"
                      }
                      className="mt-4 rounded-lg bg-green-600 px-4 py-2 font-semibold hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      Simula acquisto
                    </button>
                  </form>
                </div>

                <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-900">
                  <div className="border-b border-slate-700 p-5">
                    <h2 className="text-xl font-bold">
                      Posizioni
                    </h2>

                    <p className="mt-1 text-sm text-slate-400">
                      {openPositions.length} posizioni
                      attualmente aperte
                    </p>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[1250px]">
                      <thead className="bg-slate-800">
                        <tr>
                          <th className="p-4 text-left">
                            Token
                          </th>
                          <th className="p-4">
                            Stato
                          </th>
                          <th className="p-4 text-right">
                            Quantità
                          </th>
                          <th className="p-4 text-right">
                            Costo
                          </th>
                          <th className="p-4 text-right">
                            Prezzo
                          </th>
                          <th className="p-4 text-right">
                            Valore
                          </th>
                          <th className="p-4 text-right">
                            PnL
                          </th>
                          <th className="p-4">
                            Nuovo prezzo
                          </th>
                          <th className="p-4">
                            Quantità vendita
                          </th>
                          <th className="p-4">
                            Azioni
                          </th>
                        </tr>
                      </thead>

                      <tbody>
                        {detail.positions.length
                          === 0 ? (
                          <tr>
                            <td
                              colSpan={10}
                              className="p-10 text-center text-slate-400"
                            >
                              Nessuna posizione.
                            </td>
                          </tr>
                        ) : (
                          detail.positions.map(
                            (position) => (
                              <tr
                                key={
                                  position.id
                                }
                                className="border-t border-slate-700"
                              >
                                <td
                                  className="p-4 font-mono text-sm"
                                  title={
                                    position
                                      .token_mint
                                  }
                                >
                                  {shortenAddress(
                                    position
                                      .token_mint
                                  )}
                                </td>

                                <td className="p-4 text-center">
                                  <StatusBadge
                                    status={
                                      position
                                        .status
                                    }
                                  />
                                </td>

                                <td className="p-4 text-right">
                                  {formatNumber(
                                    position
                                      .quantity,
                                    8
                                  )}
                                </td>

                                <td className="p-4 text-right">
                                  {formatNumber(
                                    position
                                      .cost_basis_sol
                                  )}
                                </td>

                                <td className="p-4 text-right">
                                  {formatNumber(
                                    position
                                      .last_price_sol,
                                    8
                                  )}
                                </td>

                                <td className="p-4 text-right">
                                  {formatNumber(
                                    position
                                      .market_value_sol
                                  )}
                                </td>

                                <td
                                  className={`p-4 text-right font-semibold ${
                                    position
                                      .unrealized_pnl_sol
                                    >= 0
                                      ? "text-green-300"
                                      : "text-red-300"
                                  }`}
                                >
                                  {formatNumber(
                                    position
                                      .unrealized_pnl_sol
                                  )}
                                </td>

                                <td className="p-4">
                                  {position.status
                                  === "OPEN" ? (
                                    <input
                                      type="number"
                                      step="any"
                                      value={
                                        positionDrafts[
                                          position
                                            .id
                                        ]
                                          ?.market_price_sol
                                        ?? ""
                                      }
                                      onChange={(
                                        event
                                      ) =>
                                        updatePositionDraft(
                                          position.id,
                                          "market_price_sol",
                                          event
                                            .target
                                            .value
                                        )
                                      }
                                      className="w-32 rounded border border-slate-600 bg-slate-950 px-2 py-1"
                                    />
                                  ) : (
                                    "-"
                                  )}
                                </td>

                                <td className="p-4">
                                  {position.status
                                  === "OPEN" ? (
                                    <input
                                      type="number"
                                      step="any"
                                      placeholder="Tutto"
                                      value={
                                        positionDrafts[
                                          position
                                            .id
                                        ]
                                          ?.quantity
                                        ?? ""
                                      }
                                      onChange={(
                                        event
                                      ) =>
                                        updatePositionDraft(
                                          position.id,
                                          "quantity",
                                          event
                                            .target
                                            .value
                                        )
                                      }
                                      className="w-32 rounded border border-slate-600 bg-slate-950 px-2 py-1"
                                    />
                                  ) : (
                                    "-"
                                  )}
                                </td>

                                <td className="p-4">
                                  {position.status
                                  === "OPEN" && (
                                    <div className="flex gap-2">
                                      <button
                                        type="button"
                                        onClick={() =>
                                          markPosition(
                                            position
                                          )
                                        }
                                        className="rounded border border-blue-700 px-3 py-1 text-blue-300"
                                      >
                                        Aggiorna
                                      </button>

                                      <button
                                        type="button"
                                        onClick={() =>
                                          sellPosition(
                                            position
                                          )
                                        }
                                        className="rounded border border-red-700 px-3 py-1 text-red-300"
                                      >
                                        Vendi
                                      </button>
                                    </div>
                                  )}
                                </td>
                              </tr>
                            )
                          )
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>

                <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-900">
                  <div className="border-b border-slate-700 p-5">
                    <h2 className="text-xl font-bold">
                      Storico ordini
                    </h2>

                    <p className="mt-1 text-sm text-slate-400">
                      Ultimi{" "}
                      {detail.orders.length}
                      {" "}ordini simulati
                    </p>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[1050px]">
                      <thead className="bg-slate-800">
                        <tr>
                          <th className="p-4">
                            Side
                          </th>
                          <th className="p-4 text-left">
                            Token
                          </th>
                          <th className="p-4 text-right">
                            Quantità
                          </th>
                          <th className="p-4 text-right">
                            Prezzo
                          </th>
                          <th className="p-4 text-right">
                            Valore
                          </th>
                          <th className="p-4 text-right">
                            Fee
                          </th>
                          <th className="p-4 text-right">
                            PnL
                          </th>
                          <th className="p-4">
                            Data
                          </th>
                        </tr>
                      </thead>

                      <tbody>
                        {detail.orders.length
                          === 0 ? (
                          <tr>
                            <td
                              colSpan={8}
                              className="p-10 text-center text-slate-400"
                            >
                              Nessun ordine.
                            </td>
                          </tr>
                        ) : (
                          detail.orders.map(
                            (order) => (
                              <tr
                                key={order.id}
                                className="border-t border-slate-700"
                              >
                                <td className="p-4 text-center">
                                  <span
                                    className={`rounded-full px-3 py-1 text-xs font-bold ${
                                      order.side
                                      === "BUY"
                                        ? "bg-green-950 text-green-300"
                                        : "bg-red-950 text-red-300"
                                    }`}
                                  >
                                    {order.side}
                                  </span>
                                </td>

                                <td
                                  className="p-4 font-mono text-sm"
                                  title={
                                    order
                                      .token_mint
                                  }
                                >
                                  {shortenAddress(
                                    order
                                      .token_mint
                                  )}
                                </td>

                                <td className="p-4 text-right">
                                  {formatNumber(
                                    order.quantity,
                                    8
                                  )}
                                </td>

                                <td className="p-4 text-right">
                                  {formatNumber(
                                    order
                                      .execution_price_sol,
                                    8
                                  )}
                                </td>

                                <td className="p-4 text-right">
                                  {formatNumber(
                                    order
                                      .gross_value_sol
                                  )}
                                </td>

                                <td className="p-4 text-right">
                                  {formatNumber(
                                    order.fee_sol
                                  )}
                                </td>

                                <td
                                  className={`p-4 text-right ${
                                    order
                                      .realized_pnl_sol
                                    >= 0
                                      ? "text-green-300"
                                      : "text-red-300"
                                  }`}
                                >
                                  {formatNumber(
                                    order
                                      .realized_pnl_sol
                                  )}
                                </td>

                                <td className="p-4 text-center text-sm text-slate-400">
                                  {formatDate(
                                    order
                                      .executed_at
                                    ?? order
                                      .created_at
                                  )}
                                </td>
                              </tr>
                            )
                          )
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}


export default PaperTrading; 