import {
  useEffect,
  useMemo,
  useState,
} from "react";
import { Link } from "react-router-dom";

import {
  addNotificationHistory,
  clearNotificationHistory,
  getNotificationHistory,
  getNotificationPreferences,
  markAllNotificationsRead,
  markNotificationRead,
  resetNotificationBaseline,
  saveNotificationPreferences,
  subscribeNotificationCenter,
} from "../services/notificationCenter";

function formatTimestamp(value) {
  if (!value) {
    return "-";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return date.toLocaleString("it-IT");
}

function getPermissionStatus() {
  if (
    typeof window === "undefined" ||
    !("Notification" in window)
  ) {
    return "unsupported";
  }

  return Notification.permission;
}

function getPermissionLabel(permission) {
  switch (permission) {
    case "granted":
      return "Autorizzate";

    case "denied":
      return "Bloccate";

    case "default":
      return "Da autorizzare";

    default:
      return "Non supportate";
  }
}

function getPermissionClasses(permission) {
  switch (permission) {
    case "granted":
      return "border-green-700 bg-green-900/40 text-green-300";

    case "denied":
      return "border-red-700 bg-red-900/40 text-red-300";

    default:
      return "border-yellow-700 bg-yellow-900/40 text-yellow-300";
  }
}

function getTypeClasses(type) {
  switch (type) {
    case "alert":
      return "border-red-700 bg-red-900/40 text-red-300";

    case "signal":
      return "border-blue-700 bg-blue-900/40 text-blue-300";

    default:
      return "border-purple-700 bg-purple-900/40 text-purple-300";
  }
}

function getConfidenceClasses(confidence) {
  switch (confidence) {
    case "HIGH":
      return "text-green-300";

    case "MEDIUM":
      return "text-yellow-300";

    default:
      return "text-slate-400";
  }
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

function Notifications() {
  const [
    preferences,
    setPreferences,
  ] = useState(
    getNotificationPreferences
  );

  const [history, setHistory] = useState(
    getNotificationHistory
  );

  const [permission, setPermission] =
    useState(getPermissionStatus);

  const [message, setMessage] = useState("");

  useEffect(() => {
    return subscribeNotificationCenter(() => {
      setPreferences(
        getNotificationPreferences()
      );

      setHistory(
        getNotificationHistory()
      );

      setPermission(
        getPermissionStatus()
      );
    });
  }, []);

  const unreadCount = useMemo(
    () =>
      history.filter((item) => !item.read)
        .length,
    [history]
  );

  function updatePreferences(changes) {
    const nextPreferences =
      saveNotificationPreferences({
        ...preferences,
        ...changes,
      });

    setPreferences(nextPreferences);
  }

  async function enableNotifications() {
    setMessage("");

    if (!("Notification" in window)) {
      setMessage(
        "Questo browser non supporta le notifiche."
      );

      return;
    }

    let nextPermission =
      Notification.permission;

    if (nextPermission !== "granted") {
      nextPermission =
        await Notification.requestPermission();
    }

    setPermission(nextPermission);

    if (nextPermission === "granted") {
      updatePreferences({
        enabled: true,
      });

      setMessage(
        "Notification Center attivato correttamente."
      );
    } else {
      updatePreferences({
        enabled: false,
      });

      setMessage(
        "Permesso non concesso. Controlla le impostazioni del browser."
      );
    }
  }

  function disableNotifications() {
    updatePreferences({
      enabled: false,
    });

    setMessage(
      "Notification Center disattivato."
    );
  }

  function sendTestNotification() {
    setMessage("");

    if (
      !("Notification" in window) ||
      Notification.permission !== "granted"
    ) {
      setMessage(
        "Autorizza prima le notifiche browser."
      );

      return;
    }

    const createdAt =
      new Date().toISOString();

    const testItem = {
      id: `test-${Date.now()}`,
      type: "test",
      title: "SmartMoney AI",
      message:
        "Notifica di prova ricevuta correttamente.",
      score: 100,
      confidence: "HIGH",
      token: "",
      route: "/notifications",
      createdAt,
    };

    addNotificationHistory(testItem);

    const notification = new Notification(
      testItem.title,
      {
        body: testItem.message,
        tag: testItem.id,
      }
    );

    notification.onclick = () => {
      window.focus();
      window.location.assign(
        "/notifications"
      );
      notification.close();
    };

    setMessage(
      "Notifica di prova inviata."
    );
  }

  function handleMarkAllRead() {
    markAllNotificationsRead();

    setMessage(
      "Tutte le notifiche sono state segnate come lette."
    );
  }

  function handleClearHistory() {
    const confirmed = window.confirm(
      "Vuoi cancellare tutta la cronologia delle notifiche?"
    );

    if (!confirmed) {
      return;
    }

    clearNotificationHistory();

    setMessage(
      "Cronologia notifiche cancellata."
    );
  }

  function handleResetBaseline() {
    const confirmed = window.confirm(
      "Vuoi azzerare gli elementi già rilevati? Al prossimo controllo verrà creata una nuova baseline."
    );

    if (!confirmed) {
      return;
    }

    resetNotificationBaseline();

    setMessage(
      "Baseline notifiche azzerata."
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <header className="border-b border-slate-700">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 p-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-3xl font-bold">
              Notification Center
            </h1>

            <p className="mt-2 text-slate-400">
              Alert browser e cronologia dei nuovi
              segnali Smart Money
            </p>
          </div>

          <span
            className={`w-fit rounded-full border px-5 py-2 font-bold ${
              preferences.enabled
                ? "border-green-700 bg-green-900/40 text-green-300"
                : "border-slate-600 bg-slate-800 text-slate-300"
            }`}
          >
            {preferences.enabled
              ? "Sistema attivo"
              : "Sistema disattivato"}
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-7xl p-4 sm:p-8">
        {message && (
          <div className="mb-6 rounded-lg border border-blue-700 bg-blue-900/30 p-4 text-blue-300">
            {message}
          </div>
        )}

        <section className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <MetricCard
            label="Stato browser"
            value={getPermissionLabel(
              permission
            )}
            valueClassName={
              permission === "granted"
                ? "text-green-300"
                : permission === "denied"
                  ? "text-red-300"
                  : "text-yellow-300"
            }
          />

          <MetricCard
            label="Notifiche non lette"
            value={unreadCount}
            valueClassName="text-red-300"
          />

          <MetricCard
            label="Cronologia"
            value={history.length}
            subtitle="Massimo 150 elementi"
            valueClassName="text-blue-300"
          />

          <MetricCard
            label="Score minimo"
            value={preferences.minScore}
            subtitle={`Confidence ${preferences.minConfidence}`}
            valueClassName="text-purple-300"
          />
        </section>

        <section className="mb-8 grid grid-cols-1 gap-6 xl:grid-cols-2">
          <div className="rounded-xl border border-slate-700 bg-slate-800 p-6">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-xl font-bold">
                  Notifiche browser
                </h2>

                <p className="mt-1 text-sm text-slate-400">
                  Permesso necessario per mostrare
                  notifiche sul computer
                </p>
              </div>

              <span
                className={`w-fit rounded-full border px-4 py-2 text-sm font-bold ${getPermissionClasses(
                  permission
                )}`}
              >
                {getPermissionLabel(
                  permission
                )}
              </span>
            </div>

            <div className="mt-6 flex flex-wrap gap-3">
              {!preferences.enabled ? (
                <button
                  type="button"
                  onClick={enableNotifications}
                  disabled={
                    permission ===
                    "unsupported"
                  }
                  className="rounded-lg bg-green-600 px-5 py-3 font-semibold hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Attiva notifiche
                </button>
              ) : (
                <button
                  type="button"
                  onClick={disableNotifications}
                  className="rounded-lg bg-red-600 px-5 py-3 font-semibold hover:bg-red-700"
                >
                  Disattiva notifiche
                </button>
              )}

              <button
                type="button"
                onClick={sendTestNotification}
                className="rounded-lg border border-blue-700 bg-blue-900/40 px-5 py-3 font-semibold text-blue-300 hover:bg-blue-900/70"
              >
                Invia test
              </button>
            </div>

            {permission === "denied" && (
              <p className="mt-5 text-sm text-red-300">
                Il browser ha bloccato le
                notifiche. Devi riattivarle dalle
                impostazioni del sito.
              </p>
            )}
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-800 p-6">
            <h2 className="text-xl font-bold">
              Filtri
            </h2>

            <p className="mt-1 text-sm text-slate-400">
              Scegli quali eventi devono generare
              una notifica
            </p>

            <div className="mt-6 space-y-5">
              <label className="block">
                <span className="text-sm text-slate-300">
                  Score minimo
                </span>

                <div className="mt-2 flex items-center gap-4">
                  <input
                    type="range"
                    min="0"
                    max="100"
                    step="1"
                    value={
                      preferences.minScore
                    }
                    onChange={(event) =>
                      updatePreferences({
                        minScore: Number(
                          event.target.value
                        ),
                      })
                    }
                    className="min-w-0 flex-1 accent-blue-600"
                  />

                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={
                      preferences.minScore
                    }
                    onChange={(event) =>
                      updatePreferences({
                        minScore: Number(
                          event.target.value
                        ),
                      })
                    }
                    className="w-24 rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-center outline-none focus:border-blue-500"
                  />
                </div>
              </label>

              <label className="block">
                <span className="text-sm text-slate-300">
                  Confidence minima
                </span>

                <select
                  value={
                    preferences.minConfidence
                  }
                  onChange={(event) =>
                    updatePreferences({
                      minConfidence:
                        event.target.value,
                    })
                  }
                  className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-blue-500"
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

              <label className="block">
                <span className="text-sm text-slate-300">
                  Frequenza controllo
                </span>

                <select
                  value={
                    preferences.pollSeconds
                  }
                  onChange={(event) =>
                    updatePreferences({
                      pollSeconds: Number(
                        event.target.value
                      ),
                    })
                  }
                  className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-3 outline-none focus:border-blue-500"
                >
                  <option value="15">
                    Ogni 15 secondi
                  </option>

                  <option value="30">
                    Ogni 30 secondi
                  </option>

                  <option value="60">
                    Ogni minuto
                  </option>

                  <option value="120">
                    Ogni 2 minuti
                  </option>
                </select>
              </label>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="flex items-center gap-3 rounded-lg border border-slate-600 bg-slate-900 p-4">
                  <input
                    type="checkbox"
                    checked={
                      preferences.includeAlerts
                    }
                    onChange={(event) =>
                      updatePreferences({
                        includeAlerts:
                          event.target.checked,
                      })
                    }
                    className="h-5 w-5 accent-red-600"
                  />

                  <span>Smart Alerts</span>
                </label>

                <label className="flex items-center gap-3 rounded-lg border border-slate-600 bg-slate-900 p-4">
                  <input
                    type="checkbox"
                    checked={
                      preferences.includeSignals
                    }
                    onChange={(event) =>
                      updatePreferences({
                        includeSignals:
                          event.target.checked,
                      })
                    }
                    className="h-5 w-5 accent-blue-600"
                  />

                  <span>Token Signals</span>
                </label>
              </div>
            </div>
          </div>
        </section>

        <div className="mb-8 rounded-xl border border-yellow-800 bg-yellow-950/20 p-4 text-sm text-yellow-200">
          Le notifiche funzionano mentre SmartMoney
          AI è aperto nel browser. Per riceverle anche
          con il sito completamente chiuso serviranno
          successivamente un service worker e un sistema
          push lato backend.
        </div>

        <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
          <div className="flex flex-col gap-4 border-b border-slate-700 p-5 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="text-xl font-bold">
                Cronologia notifiche
              </h2>

              <p className="mt-1 text-sm text-slate-400">
                {unreadCount} non lette su{" "}
                {history.length}
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={handleMarkAllRead}
                disabled={history.length === 0}
                className="rounded-lg border border-blue-700 bg-blue-900/40 px-4 py-2 text-sm font-semibold text-blue-300 hover:bg-blue-900/70 disabled:opacity-50"
              >
                Segna tutte come lette
              </button>

              <button
                type="button"
                onClick={handleResetBaseline}
                className="rounded-lg border border-yellow-700 bg-yellow-900/40 px-4 py-2 text-sm font-semibold text-yellow-300 hover:bg-yellow-900/70"
              >
                Azzera baseline
              </button>

              <button
                type="button"
                onClick={handleClearHistory}
                disabled={history.length === 0}
                className="rounded-lg border border-red-700 bg-red-900/40 px-4 py-2 text-sm font-semibold text-red-300 hover:bg-red-900/70 disabled:opacity-50"
              >
                Cancella cronologia
              </button>
            </div>
          </div>

          <div className="divide-y divide-slate-700">
            {history.length === 0 ? (
              <div className="p-12 text-center">
                <p className="text-lg font-semibold text-slate-300">
                  Nessuna notifica
                </p>

                <p className="mt-2 text-sm text-slate-500">
                  I nuovi alert e segnali compatibili
                  con i filtri compariranno qui.
                </p>
              </div>
            ) : (
              history.map((item) => (
                <article
                  key={item.id}
                  className={`p-5 ${
                    item.read
                      ? "bg-slate-800"
                      : "bg-blue-950/20"
                  }`}
                >
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-3">
                        <span
                          className={`rounded-full border px-3 py-1 text-xs font-bold uppercase ${getTypeClasses(
                            item.type
                          )}`}
                        >
                          {item.type}
                        </span>

                        {!item.read && (
                          <span className="rounded-full bg-blue-600 px-3 py-1 text-xs font-bold text-white">
                            Nuova
                          </span>
                        )}

                        <span
                          className={`text-sm font-semibold ${getConfidenceClasses(
                            item.confidence
                          )}`}
                        >
                          {item.confidence}
                        </span>
                      </div>

                      <h3 className="mt-3 text-lg font-bold">
                        {item.title}
                      </h3>

                      <p className="mt-2 text-slate-300">
                        {item.message}
                      </p>

                      <p className="mt-3 text-xs text-slate-500">
                        {formatTimestamp(
                          item.createdAt
                        )}
                      </p>
                    </div>

                    <div className="flex shrink-0 flex-wrap gap-3">
                      {item.route && (
                        <Link
                          to={item.route}
                          onClick={() =>
                            markNotificationRead(
                              item.id
                            )
                          }
                          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold hover:bg-blue-700"
                        >
                          Apri
                        </Link>
                      )}

                      {!item.read && (
                        <button
                          type="button"
                          onClick={() =>
                            markNotificationRead(
                              item.id
                            )
                          }
                          className="rounded-lg border border-slate-600 bg-slate-900 px-4 py-2 text-sm font-semibold hover:bg-slate-700"
                        >
                          Segna letta
                        </button>
                      )}
                    </div>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

export default Notifications; 