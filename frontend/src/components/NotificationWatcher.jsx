import {
  useEffect,
  useState,
} from "react";

import { getDashboard } from "../services/api";

import {
  addNotificationHistory,
  getNotificationPreferences,
  getSeenNotificationIds,
  isNotificationBaselineReady,
  saveSeenNotificationIds,
  setNotificationBaselineReady,
  subscribeNotificationCenter,
} from "../services/notificationCenter";

const CONFIDENCE_LEVELS = {
  LOW: 1,
  MEDIUM: 2,
  HIGH: 3,
};

function firstArray(possibleArrays) {
  return (
    possibleArrays.find(
      (value) => Array.isArray(value)
    ) ?? []
  );
}

function toNumber(value) {
  const number = Number(value);

  return Number.isFinite(number)
    ? number
    : 0;
}

function normalizeConfidence(value) {
  const confidence = String(
    value ?? "LOW"
  ).toUpperCase();

  return CONFIDENCE_LEVELS[confidence]
    ? confidence
    : "LOW";
}

function shortenAddress(
  value,
  start = 8,
  end = 6
) {
  if (!value) {
    return "Token sconosciuto";
  }

  if (value.length <= start + end + 3) {
    return value;
  }

  return `${value.slice(0, start)}...${value.slice(
    -end
  )}`;
}

function createHash(value) {
  let hash = 0;

  for (
    let index = 0;
    index < value.length;
    index += 1
  ) {
    hash =
      (hash << 5) -
      hash +
      value.charCodeAt(index);

    hash |= 0;
  }

  return Math.abs(hash).toString(36);
}

function normalizeDashboardItem(
  item,
  type
) {
  const token = String(
    item.token ??
      item.token_mint ??
      item.mint ??
      ""
  );

  const score = toNumber(
    item.signal_score ??
      item.token_score ??
      item.score
  );

  const confidence = normalizeConfidence(
    item.confidence
  );

  const leaderWallet = String(
    item.leader_wallet ??
      item.wallet ??
      ""
  );

  const buyers = toNumber(
    item.buyers ??
      item.smart_wallets ??
      item.unique_buyers
  );

  const timestamp = String(
    item.timestamp ??
      item.created_at ??
      item.detected_at ??
      item.last_trade_at ??
      ""
  );

  const fingerprint = [
    type,
    token,
    leaderWallet,
    score,
    confidence,
    buyers,
    timestamp,
  ].join("|");

  const id = `${type}-${createHash(
    fingerprint
  )}`;

  const title =
    type === "alert"
      ? "Nuovo Smart Alert"
      : "Nuovo Token Signal";

  const message = [
    shortenAddress(token),
    `score ${score}`,
    confidence,
    buyers > 0
      ? `${buyers} buyer`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return {
    id,
    type,
    title,
    message,
    token,
    score,
    confidence,
    leaderWallet,
    buyers,
    route: token
      ? `/token/${token}`
      : type === "alert"
        ? "/alerts"
        : "/signals",
    createdAt:
      timestamp || new Date().toISOString(),
  };
}

function extractCandidates(payload) {
  const nestedData =
    payload?.data &&
    typeof payload.data === "object"
      ? payload.data
      : {};

  const alerts = firstArray([
    payload?.alerts,
    payload?.latest_alerts,
    nestedData?.alerts,
    nestedData?.latest_alerts,
  ]);

  const signals = firstArray([
    payload?.signals,
    payload?.top_signals,
    nestedData?.signals,
    nestedData?.top_signals,
  ]);

  return [
    ...alerts.map((item) =>
      normalizeDashboardItem(item, "alert")
    ),
    ...signals.map((item) =>
      normalizeDashboardItem(item, "signal")
    ),
  ];
}

function passesPreferences(
  candidate,
  preferences
) {
  if (
    candidate.type === "alert" &&
    !preferences.includeAlerts
  ) {
    return false;
  }

  if (
    candidate.type === "signal" &&
    !preferences.includeSignals
  ) {
    return false;
  }

  if (
    candidate.score <
    Number(preferences.minScore)
  ) {
    return false;
  }

  const candidateLevel =
    CONFIDENCE_LEVELS[
      candidate.confidence
    ] ?? 1;

  const minimumLevel =
    CONFIDENCE_LEVELS[
      preferences.minConfidence
    ] ?? 1;

  return candidateLevel >= minimumLevel;
}

function showBrowserNotification(candidate) {
  if (
    typeof window === "undefined" ||
    !("Notification" in window) ||
    Notification.permission !== "granted"
  ) {
    return;
  }

  const notification = new Notification(
    candidate.title,
    {
      body: candidate.message,
      tag: candidate.id,
      renotify: false,
    }
  );

  notification.onclick = () => {
    window.focus();

    if (candidate.route) {
      window.location.assign(candidate.route);
    }

    notification.close();
  };
}

function NotificationWatcher() {
  const [
    preferences,
    setPreferences,
  ] = useState(
    getNotificationPreferences
  );

  useEffect(() => {
    return subscribeNotificationCenter(() => {
      setPreferences(
        getNotificationPreferences()
      );
    });
  }, []);

  useEffect(() => {
    if (!preferences.enabled) {
      return undefined;
    }

    let cancelled = false;
    let timerId = null;

    async function runWatcher() {
      try {
        const response = await getDashboard();

        if (cancelled) {
          return;
        }

        const candidates =
          extractCandidates(response.data);

        const previousIds =
          getSeenNotificationIds();

        const previousIdSet = new Set(
          previousIds
        );

        const nextIds = new Set(
          previousIds
        );

        candidates.forEach((candidate) => {
          nextIds.add(candidate.id);
        });

        saveSeenNotificationIds([
          ...nextIds,
        ]);

        if (
          !isNotificationBaselineReady()
        ) {
          setNotificationBaselineReady(true);
          return;
        }

        let browserNotificationsShown = 0;

        for (const candidate of candidates) {
          if (
            previousIdSet.has(candidate.id)
          ) {
            continue;
          }

          if (
            !passesPreferences(
              candidate,
              preferences
            )
          ) {
            continue;
          }

          const added =
            addNotificationHistory(candidate);

          if (
            added &&
            browserNotificationsShown < 4
          ) {
            showBrowserNotification(candidate);
            browserNotificationsShown += 1;
          }
        }
      } catch (error) {
        console.warn(
          "Notification Center: controllo fallito.",
          error
        );
      } finally {
        if (!cancelled) {
          timerId = window.setTimeout(
            runWatcher,
            Math.max(
              15,
              Number(
                preferences.pollSeconds
              ) || 30
            ) * 1000
          );
        }
      }
    }

    runWatcher();

    return () => {
      cancelled = true;

      if (timerId) {
        window.clearTimeout(timerId);
      }
    };
  }, [
    preferences.enabled,
    preferences.includeAlerts,
    preferences.includeSignals,
    preferences.minConfidence,
    preferences.minScore,
    preferences.pollSeconds,
  ]);

  return null;
}

export default NotificationWatcher; 