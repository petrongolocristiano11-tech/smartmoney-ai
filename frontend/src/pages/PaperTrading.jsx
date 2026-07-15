import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  buyPaperToken,
  createPaperAccount,
  getPaperAccount,
  getPaperAccounts,
  getPaperTokenPrice,
  refreshPaperAccountPrices,
  resetPaperAccount,
  sellPaperToken,
  updatePaperAccount,
} from "../services/api";


const ACCESS_KEY_STORAGE =
  "smartmoney-paper-access-key";

const AUTO_REFRESH_MS = 30_000;


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

  const [
    pricePreview,
    setPricePreview,
  ] = useState(null);

  const [
    pricingWarning,
    setPricingWarning,
  ] = useState("");

  const [
    lastPriceRefresh,
    setLastPriceRefresh,
  ] = useState(null);

  const [loading, setLoading] =
    useState(false);

  const [busyAction, setBusyAction] =
    useState("");

  const [error, setError] =
    useState("");

  const [message, setMessage] =
    useState("");


  const handleRequestError =
    useCallback(
      (requestError) => {
        const status =
          requestError?.response
            ?.status;

        if (status === 401) {
          sessionStorage.removeItem(
            ACCESS_KEY_STORAGE
          );

          setAccessKey("");
          setKeyInput("");
          setAccounts([]);
          setDetail(null);

          setError(
            "Chiave di accesso "
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


  const applyDetail =
    useCallback(
      (nextDetail) => {
        setDetail(nextDetail);

        const account =
          nextDetail.account;

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
          of nextDetail.positions
        ) {
          nextDrafts[
            position.id
          ] = {
            quantity: "",
          };
        }

        setPositionDrafts(
          nextDrafts
        );
      },
      []
    );


  const loadAccountDetail =
    useCallback(
      async (
        key,
        accountId
      ) => {
        const response =
          await getPaperAccount(
            key,
            accountId
          );

        applyDetail(
          response.data
        );
      },
      [applyDetail]
    );


  const refreshPrices =
    useCallback(
      async (
        key,
        accountId,
        forceRefresh = false
      ) => {
        const response =
          await refreshPaperAccountPrices(
            key,
            accountId,
            forceRefresh
          );

        const missing =
          response.data
            .missing_token_mints
          ?? [];

        if (missing.length > 0) {
          setPricingWarning(
            "Jupiter non ha "
            + "restituito un prezzo "
            + "affidabile per: "
            + missing
              .map((mint) =>
                shortenAddress(
                  mint
                )
              )
              .join(", ")
          );
        } else {
          setPricingWarning("");
        }

        setLastPriceRefresh(
          response.data
            .refreshed_at
        );

        return response.data;
      },
      []
    );


  const loadAccounts =
    useCallback(
      async (
        key,
        preferredAccountId =
          null,
        refreshSelected = true
      ) => {
        setLoading(true);
        setError("");

        try {
          let response =
            await getPaperAccounts(
              key
            );

          let accountRows =
            response.data
              .accounts
            ?? [];

          const existingIds =
            new Set(
              accountRows.map(
                (row) =>
                  row.account.id
              )
            );

          const preferredId =
            Number(
              preferredAccountId
            );

          const nextAccountId =
            existingIds.has(
              preferredId
            )
              ? preferredId
              : accountRows[0]
                  ?.account
                  ?.id
                ?? null;

          setSelectedAccountId(
            nextAccountId
          );

          if (nextAccountId) {
            if (refreshSelected) {
              await refreshPrices(
                key,
                nextAccountId
              );

              response =
                await getPaperAccounts(
                  key
                );

              accountRows =
                response.data
                  .accounts
                ?? [];
            }

            setAccounts(
              accountRows
            );

            await loadAccountDetail(
              key,
              nextAccountId
            );
          } else {
            setAccounts([]);
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
      },
      [
        handleRequestError,
        loadAccountDetail,
        refreshPrices,
      ]
    );


  useEffect(() => {
    if (accessKey) {
      loadAccounts(
        accessKey,
        selectedAccountId,
        true
      );
    }
  }, [accessKey]);


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
            await refreshPrices(
              accessKey,
              selectedAccountId,
              false
            );

            await loadAccountDetail(
              accessKey,
              selectedAccountId
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
            handleRequestError(
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
    handleRequestError,
    loadAccountDetail,
    refreshPrices,
  ]);


  const openPositions =
    useMemo(
      () =>
        detail?.positions
          ?.filter(
            (position) =>
              position.status
              === "OPEN"
          )
        ?? [],
      [detail]
    );


  async function runAction(
    actionName,
    operation,
    successMessage
  ) {
    setBusyAction(actionName);
    setError("");
    setMessage("");

    try {
      const result =
        await operation();

      setMessage(successMessage);

      const targetAccountId =
        result?.accountId
        ?? selectedAccountId;

      await loadAccounts(
        accessKey,
        targetAccountId,
        true
      );

      return result;
    } catch (requestError) {
      handleRequestError(
        requestError
      );

      return null;
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
        "Inserisci la chiave "
        + "di accesso."
      );

      return;
    }

    sessionStorage.setItem(
      ACCESS_KEY_STORAGE,
      normalizedKey
    );

    setError("");
    setAccessKey(
      normalizedKey
    );
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
    setPricingWarning("");
  }


  async function selectAccount(
    accountId
  ) {
    setSelectedAccountId(
      accountId
    );

    await loadAccounts(
      accessKey,
      accountId,
      true
    );
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


  function updateBuyForm(
    field,
    value
  ) {
    setBuyForm(
      (current) => ({
        ...current,
        [field]: value,
      })
    );

    if (field === "token_mint") {
      setPricePreview(null);
    }
  }


  async function submitCreateAccount(
    event
  ) {
    event.preventDefault();

    await runAction(
      "create-account",
      async () => {
        const response =
          await createPaperAccount(
            accessKey,
            {
              name:
                createForm.name,
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

        setCreateForm(
          EMPTY_CREATE_FORM
        );

        return {
          accountId:
            response.data
              .account
              .id,
        };
      },
      "Conto virtuale creato."
    );
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


  async function changeStatus(
    status
  ) {
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


  async function verifyPrice() {
    const tokenMint =
      buyForm.token_mint.trim();

    if (!tokenMint) {
      setError(
        "Inserisci prima "
        + "il token mint."
      );

      return;
    }

    setBusyAction(
      "verify-price"
    );

    setError("");
    setPricePreview(null);

    try {
      const response =
        await getPaperTokenPrice(
          accessKey,
          tokenMint,
          true
        );

      setPricePreview(
        response.data
      );
    } catch (requestError) {
      handleRequestError(
        requestError
      );
    } finally {
      setBusyAction("");
    }
  }


  async function submitBuy(event) {
    event.preventDefault();

    const result =
      await runAction(
        "buy",
        () =>
          buyPaperToken(
            accessKey,
            selectedAccountId,
            {
              token_mint:
                buyForm
                  .token_mint,
              value_sol:
                Number(
                  buyForm
                    .value_sol
                ),
              slippage_percent:
                Number(
                  buyForm
                    .slippage_percent
                ),
              fee_percent:
                Number(
                  buyForm
                    .fee_percent
                ),
              signal_score:
                buyForm
                  .signal_score
                  ? Number(
                      buyForm
                        .signal_score
                    )
                  : null,
              reason:
                buyForm.reason
                || null,
            }
          ),
        "Acquisto virtuale "
        + "eseguito con prezzo "
        + "Jupiter."
      );

    if (result !== null) {
      setBuyForm(
        EMPTY_BUY_FORM
      );

      setPricePreview(null);
    }
  }


  function updatePositionDraft(
    positionId,
    value
  ) {
    setPositionDrafts(
      (current) => ({
        ...current,
        [positionId]: {
          quantity: value,
        },
      })
    );
  }


  async function sellPosition(
    position
  ) {
    const draft =
      positionDrafts[
        position.id
      ];

    await runAction(
      `sell-${position.id}`,
      () =>
        sellPaperToken(
          accessKey,
          selectedAccountId,
          {
            token_mint:
              position.token_mint,
            quantity:
              draft?.quantity
                ? Number(
                    draft.quantity
                  )
                : null,
            slippage_percent:
              0.5,
            fee_percent:
              0.25,
            reason:
              "Vendita dalla "
              + "Paper Trading Console",
          }
        ),
      draft?.quantity
        ? "Vendita parziale "
          + "eseguita con prezzo "
          + "Jupiter."
        : "Posizione chiusa "
          + "con prezzo Jupiter."
    );
  }


  async function refreshNow() {
    setBusyAction(
      "refresh-prices"
    );

    setError("");

    try {
      await refreshPrices(
        accessKey,
        selectedAccountId,
        true
      );

      await loadAccountDetail(
        accessKey,
        selectedAccountId
      );

      const response =
        await getPaperAccounts(
          accessKey
        );

      setAccounts(
        response.data.accounts
        ?? []
      );

      setMessage(
        "Prezzi aggiornati "
        + "da Jupiter."
      );
    } catch (requestError) {
      handleRequestError(
        requestError
      );
    } finally {
      setBusyAction("");
    }
  }


  async function resetAccount() {
    const accountName =
      detail?.account?.name;

    const confirmation =
      window.prompt(
        "Per azzerare conto, "
        + "ordini e posizioni, "
        + "scrivi esattamente:\n"
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
              Inserisci la chiave Paper
              Trading configurata nel backend.
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


  const account =
    detail?.account;

  const summary =
    detail?.summary;


  return (
    <main className="min-h-screen bg-slate-950 p-4 text-white sm:p-8">
      <div className="mx-auto max-w-7xl">
        <header className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wider text-blue-300">
              Prezzi reali Jupiter
            </p>

            <h1 className="mt-2 text-3xl font-bold">
              Paper Trading Console
            </h1>

            <p className="mt-2 text-slate-400">
              Operazioni virtuali con prezzi
              recuperati e verificati dal
              backend.
            </p>

            {lastPriceRefresh && (
              <p className="mt-2 text-xs text-slate-500">
                Ultimo aggiornamento:{" "}
                {formatDate(
                  lastPriceRefresh
                )}
              </p>
            )}
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={refreshNow}
              disabled={
                !selectedAccountId
                || busyAction
                === "refresh-prices"
              }
              className="rounded-lg border border-blue-700 bg-blue-950/40 px-4 py-2 text-blue-300 disabled:opacity-50"
            >
              {busyAction
                === "refresh-prices"
                ? "Aggiornamento..."
                : "Aggiorna prezzi"}
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

        {pricingWarning && (
          <div className="mt-6 rounded-lg border border-yellow-700 bg-yellow-950/40 p-4 text-yellow-300">
            {pricingWarning}
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
              onSubmit={
                submitCreateAccount
              }
              className="rounded-xl border border-slate-700 bg-slate-900 p-5"
            >
              <h2 className="text-lg font-bold">
                Nuovo conto
              </h2>

              <label className="mt-4 block">
                <span className="text-xs text-slate-400">
                  Nome
                </span>

                <input
                  value={createForm.name}
                  onChange={(event) =>
                    updateCreateForm(
                      "name",
                      event.target.value
                    )
                  }
                  className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                />
              </label>

              <label className="mt-3 block">
                <span className="text-xs text-slate-400">
                  Saldo iniziale SOL
                </span>

                <input
                  type="number"
                  step="any"
                  value={
                    createForm
                      .starting_balance_sol
                  }
                  onChange={(event) =>
                    updateCreateForm(
                      "starting_balance_sol",
                      event.target.value
                    )
                  }
                  className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                />
              </label>

              <label className="mt-3 block">
                <span className="text-xs text-slate-400">
                  Massimo per posizione
                </span>

                <input
                  type="number"
                  step="any"
                  value={
                    createForm
                      .max_position_size_sol
                  }
                  onChange={(event) =>
                    updateCreateForm(
                      "max_position_size_sol",
                      event.target.value
                    )
                  }
                  className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                />
              </label>

              <label className="mt-3 block">
                <span className="text-xs text-slate-400">
                  Posizioni massime
                </span>

                <input
                  type="number"
                  value={
                    createForm
                      .max_open_positions
                  }
                  onChange={(event) =>
                    updateCreateForm(
                      "max_open_positions",
                      event.target.value
                    )
                  }
                  className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                />
              </label>

              <label className="mt-3 block">
                <span className="text-xs text-slate-400">
                  Perdita giornaliera
                  massima
                </span>

                <input
                  type="number"
                  step="any"
                  value={
                    createForm
                      .daily_loss_limit_sol
                  }
                  onChange={(event) =>
                    updateCreateForm(
                      "daily_loss_limit_sol",
                      event.target.value
                    )
                  }
                  className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                />
              </label>

              <button
                type="submit"
                disabled={
                  busyAction
                  === "create-account"
                }
                className="mt-4 w-full rounded-lg bg-blue-600 px-4 py-2 font-semibold disabled:opacity-50"
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
                          status={
                            account.status
                          }
                        />
                      </div>

                      <p className="mt-2 text-sm text-slate-400">
                        Conto #{account.id}
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
                        onClick={
                          resetAccount
                        }
                        className="rounded-lg bg-red-700 px-3 py-2 text-sm font-semibold"
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
                    onSubmit={
                      submitSettings
                    }
                    className="rounded-xl border border-slate-700 bg-slate-900 p-5"
                  >
                    <h2 className="text-xl font-bold">
                      Controlli di rischio
                    </h2>

                    {settingsForm && (
                      <div className="mt-4 space-y-3">
                        <input
                          value={
                            settingsForm
                              .name
                          }
                          onChange={(event) =>
                            setSettingsForm(
                              (current) => ({
                                ...current,
                                name:
                                  event
                                    .target
                                    .value,
                              })
                            )
                          }
                          className="w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                          placeholder="Nome"
                        />

                        <input
                          type="number"
                          step="any"
                          value={
                            settingsForm
                              .max_position_size_sol
                          }
                          onChange={(event) =>
                            setSettingsForm(
                              (current) => ({
                                ...current,
                                max_position_size_sol:
                                  event
                                    .target
                                    .value,
                              })
                            )
                          }
                          className="w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                          placeholder="Massimo per posizione"
                        />

                        <input
                          type="number"
                          value={
                            settingsForm
                              .max_open_positions
                          }
                          onChange={(event) =>
                            setSettingsForm(
                              (current) => ({
                                ...current,
                                max_open_positions:
                                  event
                                    .target
                                    .value,
                              })
                            )
                          }
                          className="w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                          placeholder="Posizioni massime"
                        />

                        <input
                          type="number"
                          step="any"
                          value={
                            settingsForm
                              .daily_loss_limit_sol
                          }
                          onChange={(event) =>
                            setSettingsForm(
                              (current) => ({
                                ...current,
                                daily_loss_limit_sol:
                                  event
                                    .target
                                    .value,
                              })
                            )
                          }
                          className="w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                          placeholder="Perdita giornaliera"
                        />
                      </div>
                    )}

                    <button
                      type="submit"
                      className="mt-4 rounded-lg bg-blue-600 px-4 py-2 font-semibold"
                    >
                      Salva limiti
                    </button>
                  </form>

                  <form
                    onSubmit={submitBuy}
                    className="rounded-xl border border-slate-700 bg-slate-900 p-5"
                  >
                    <h2 className="text-xl font-bold">
                      Acquisto con prezzo
                      Jupiter
                    </h2>

                    <label className="mt-4 block">
                      <span className="text-xs text-slate-400">
                        Token mint
                      </span>

                      <input
                        value={
                          buyForm.token_mint
                        }
                        onChange={(event) =>
                          updateBuyForm(
                            "token_mint",
                            event.target.value
                          )
                        }
                        className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                      />
                    </label>

                    <button
                      type="button"
                      onClick={verifyPrice}
                      disabled={
                        busyAction
                        === "verify-price"
                      }
                      className="mt-3 rounded-lg border border-blue-700 px-4 py-2 text-sm text-blue-300 disabled:opacity-50"
                    >
                      Verifica prezzo
                    </button>

                    {pricePreview && (
                      <div className="mt-4 rounded-lg border border-blue-800 bg-blue-950/30 p-4">
                        <p className="text-sm text-slate-400">
                          Prezzo corrente
                        </p>

                        <p className="mt-1 text-xl font-bold text-blue-300">
                          {formatNumber(
                            pricePreview
                              .sol_price,
                            10
                          )}{" "}
                          SOL
                        </p>

                        <p className="mt-1 text-sm text-slate-400">
                          $
                          {formatNumber(
                            pricePreview
                              .usd_price,
                            8
                          )}
                          {" · "}24h{" "}
                          {formatNumber(
                            pricePreview
                              .price_change_24h,
                            2
                          )}
                          %
                        </p>
                      </div>
                    )}

                    <div className="mt-4 grid grid-cols-2 gap-3">
                      <input
                        type="number"
                        step="any"
                        value={
                          buyForm.value_sol
                        }
                        onChange={(event) =>
                          updateBuyForm(
                            "value_sol",
                            event.target.value
                          )
                        }
                        className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                        placeholder="Importo SOL"
                      />

                      <input
                        type="number"
                        step="any"
                        value={
                          buyForm
                            .signal_score
                        }
                        onChange={(event) =>
                          updateBuyForm(
                            "signal_score",
                            event.target.value
                          )
                        }
                        className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                        placeholder="Signal score"
                      />

                      <input
                        type="number"
                        step="any"
                        value={
                          buyForm
                            .slippage_percent
                        }
                        onChange={(event) =>
                          updateBuyForm(
                            "slippage_percent",
                            event.target.value
                          )
                        }
                        className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                        placeholder="Slippage %"
                      />

                      <input
                        type="number"
                        step="any"
                        value={
                          buyForm
                            .fee_percent
                        }
                        onChange={(event) =>
                          updateBuyForm(
                            "fee_percent",
                            event.target.value
                          )
                        }
                        className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                        placeholder="Fee %"
                      />
                    </div>

                    <input
                      value={buyForm.reason}
                      onChange={(event) =>
                        updateBuyForm(
                          "reason",
                          event.target.value
                        )
                      }
                      className="mt-3 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2"
                      placeholder="Motivazione"
                    />

                    <button
                      type="submit"
                      disabled={
                        account.status
                        !== "ACTIVE"
                        || busyAction
                        === "buy"
                      }
                      className="mt-4 rounded-lg bg-green-600 px-4 py-2 font-semibold disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      Compra al prezzo corrente
                    </button>

                    {account.status
                      !== "ACTIVE" && (
                      <p className="mt-3 text-sm text-yellow-300">
                        Riattiva il conto per
                        eseguire acquisti.
                      </p>
                    )}
                  </form>
                </div>

                <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-900">
                  <div className="border-b border-slate-700 p-5">
                    <h2 className="text-xl font-bold">
                      Posizioni
                    </h2>

                    <p className="mt-1 text-sm text-slate-400">
                      Aggiornamento automatico
                      ogni 30 secondi
                    </p>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[1150px]">
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
                            Prezzo medio
                          </th>
                          <th className="p-4 text-right">
                            Prezzo attuale
                          </th>
                          <th className="p-4 text-right">
                            Valore
                          </th>
                          <th className="p-4 text-right">
                            PnL non realizzato
                          </th>
                          <th className="p-4">
                            Quantità vendita
                          </th>
                          <th className="p-4">
                            Azione
                          </th>
                        </tr>
                      </thead>

                      <tbody>
                        {detail.positions.length
                          === 0 ? (
                          <tr>
                            <td
                              colSpan={9}
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
                                      .average_entry_price_sol,
                                    10
                                  )}
                                </td>

                                <td className="p-4 text-right">
                                  {formatNumber(
                                    position
                                      .last_price_sol,
                                    10
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
                                    <button
                                      type="button"
                                      onClick={() =>
                                        sellPosition(
                                          position
                                        )
                                      }
                                      disabled={
                                        busyAction
                                        === `sell-${position.id}`
                                      }
                                      className="rounded border border-red-700 px-3 py-1 text-red-300 disabled:opacity-50"
                                    >
                                      Vendi al prezzo corrente
                                    </button>
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
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[1000px]">
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

                                <td className="p-4 font-mono text-sm">
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
                                    10
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

                <p className="text-sm text-slate-500">
                  Posizioni aperte:{" "}
                  {openPositions.length}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}


export default PaperTrading; 