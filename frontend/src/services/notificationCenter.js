const PREFERENCES_KEY =
  "smartmoney_notification_preferences";

const HISTORY_KEY =
  "smartmoney_notification_history";

const SEEN_KEY =
  "smartmoney_notification_seen";

const BASELINE_KEY =
  "smartmoney_notification_baseline_ready";

const EVENT_NAME =
  "smartmoney:notification-center-update";

export const DEFAULT_NOTIFICATION_PREFERENCES = {
  enabled: false,
  minScore: 70,
  minConfidence: "MEDIUM",
  includeAlerts: true,
  includeSignals: true,
  pollSeconds: 30,
};

function canUseStorage() {
  return (
    typeof window !== "undefined" &&
    typeof window.localStorage !== "undefined"
  );
}

function readJson(key, fallback) {
  if (!canUseStorage()) {
    return fallback;
  }

  try {
    const storedValue =
      window.localStorage.getItem(key);

    if (!storedValue) {
      return fallback;
    }

    return JSON.parse(storedValue);
  } catch (error) {
    console.error(
      `Errore lettura localStorage: ${key}`,
      error
    );

    return fallback;
  }
}

function writeJson(key, value) {
  if (!canUseStorage()) {
    return;
  }

  try {
    window.localStorage.setItem(
      key,
      JSON.stringify(value)
    );
  } catch (error) {
    console.error(
      `Errore scrittura localStorage: ${key}`,
      error
    );
  }
}

function emitUpdate() {
  if (typeof window === "undefined") {
    return;
  }

  window.dispatchEvent(
    new CustomEvent(EVENT_NAME)
  );
}

export function getNotificationPreferences() {
  const storedPreferences = readJson(
    PREFERENCES_KEY,
    {}
  );

  return {
    ...DEFAULT_NOTIFICATION_PREFERENCES,
    ...storedPreferences,
  };
}

export function saveNotificationPreferences(
  preferences
) {
  const nextPreferences = {
    ...DEFAULT_NOTIFICATION_PREFERENCES,
    ...getNotificationPreferences(),
    ...preferences,
  };

  nextPreferences.minScore = Math.min(
    100,
    Math.max(
      0,
      Number(nextPreferences.minScore) || 0
    )
  );

  nextPreferences.pollSeconds = Math.max(
    15,
    Number(nextPreferences.pollSeconds) || 30
  );

  writeJson(
    PREFERENCES_KEY,
    nextPreferences
  );

  emitUpdate();

  return nextPreferences;
}

export function getNotificationHistory() {
  const history = readJson(HISTORY_KEY, []);

  return Array.isArray(history)
    ? history
    : [];
}

export function addNotificationHistory(
  notification
) {
  const history = getNotificationHistory();

  const alreadyExists = history.some(
    (item) => item.id === notification.id
  );

  if (alreadyExists) {
    return false;
  }

  const nextHistory = [
    {
      ...notification,
      read: false,
      createdAt:
        notification.createdAt ??
        new Date().toISOString(),
    },
    ...history,
  ].slice(0, 150);

  writeJson(HISTORY_KEY, nextHistory);
  emitUpdate();

  return true;
}

export function markNotificationRead(
  notificationId
) {
  const history = getNotificationHistory();

  const nextHistory = history.map((item) =>
    item.id === notificationId
      ? {
          ...item,
          read: true,
        }
      : item
  );

  writeJson(HISTORY_KEY, nextHistory);
  emitUpdate();
}

export function markAllNotificationsRead() {
  const history = getNotificationHistory();

  const nextHistory = history.map((item) => ({
    ...item,
    read: true,
  }));

  writeJson(HISTORY_KEY, nextHistory);
  emitUpdate();
}

export function clearNotificationHistory() {
  writeJson(HISTORY_KEY, []);
  emitUpdate();
}

export function getUnreadNotificationCount() {
  return getNotificationHistory().filter(
    (item) => !item.read
  ).length;
}

export function getSeenNotificationIds() {
  const seenIds = readJson(SEEN_KEY, []);

  return Array.isArray(seenIds)
    ? seenIds
    : [];
}

export function saveSeenNotificationIds(ids) {
  const uniqueIds = [...new Set(ids)].slice(
    -500
  );

  writeJson(SEEN_KEY, uniqueIds);
}

export function isNotificationBaselineReady() {
  if (!canUseStorage()) {
    return false;
  }

  return (
    window.localStorage.getItem(BASELINE_KEY) ===
    "true"
  );
}

export function setNotificationBaselineReady(
  ready
) {
  if (!canUseStorage()) {
    return;
  }

  window.localStorage.setItem(
    BASELINE_KEY,
    String(Boolean(ready))
  );
}

export function resetNotificationBaseline() {
  if (!canUseStorage()) {
    return;
  }

  window.localStorage.removeItem(SEEN_KEY);
  window.localStorage.removeItem(BASELINE_KEY);

  emitUpdate();
}

export function subscribeNotificationCenter(
  listener
) {
  if (typeof window === "undefined") {
    return () => {};
  }

  function handleStorage(event) {
    const relevantKeys = [
      PREFERENCES_KEY,
      HISTORY_KEY,
      SEEN_KEY,
      BASELINE_KEY,
    ];

    if (
      event.key === null ||
      relevantKeys.includes(event.key)
    ) {
      listener();
    }
  }

  window.addEventListener(
    EVENT_NAME,
    listener
  );

  window.addEventListener(
    "storage",
    handleStorage
  );

  return () => {
    window.removeEventListener(
      EVENT_NAME,
      listener
    );

    window.removeEventListener(
      "storage",
      handleStorage
    );
  };
} 