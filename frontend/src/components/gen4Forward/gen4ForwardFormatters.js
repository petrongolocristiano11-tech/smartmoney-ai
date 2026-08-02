export const GEN4_FORWARD_ACCESS_KEY_STORAGE =
  "smartmoney-gen4-forward-automation-key";

export const GEN4_FORWARD_AUTO_REFRESH_MS = 15_000;

export const GEN4_FORWARD_LANES = [
  {
    key: "STRICT_GEN4_FORWARD",
    label: "Strict Gen4",
    shortLabel: "Strict",
    description:
      "Consenso forward fra wallet congelati e cluster indipendenti.",
    tone: "cyan",
  },
  {
    key: "SIGNAL_ONLY_FORWARD",
    label: "Signal-only proxy",
    shortLabel: "Proxy",
    description:
      "Consenso temporale senza tutte le garanzie strict.",
    tone: "violet",
  },
  {
    key: "SIMPLE_COPY_FORWARD_BASELINE",
    label: "Simple copy baseline",
    shortLabel: "Baseline",
    description:
      "Copia semplice usata come confronto economico.",
    tone: "amber",
  },
];

export function formatGen4Number(value, digits = 2) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "N/D";
  }

  return parsed.toLocaleString("it-IT", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatGen4Percent(value, digits = 2) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "N/D";
  }

  return `${formatGen4Number(parsed, digits)}%`;
}

export function formatGen4Sol(value, digits = 6) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "N/D";
  }

  return `${formatGen4Number(parsed, digits)} SOL`;
}

export function formatGen4Date(value, options = {}) {
  if (!value) {
    return "N/D";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return String(value);
  }

  return parsed.toLocaleString("it-IT", {
    dateStyle: options.dateStyle ?? "short",
    timeStyle: options.timeStyle ?? "medium",
  });
}

export function formatGen4Duration(milliseconds) {
  const safe = Math.max(0, Number(milliseconds) || 0);
  const totalMinutes = Math.floor(safe / 60_000);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;

  if (days > 0) {
    return `${days}g ${hours}h`;
  }

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }

  return `${minutes}m`;
}

export function shortenGen4Address(value, head = 6, tail = 5) {
  const normalized = String(value ?? "").trim();
  if (normalized.length <= head + tail + 3) {
    return normalized || "N/D";
  }

  return `${normalized.slice(0, head)}…${normalized.slice(-tail)}`;
}

export function parseGen4ApiError(error) {
  const detail = error?.response?.data?.detail;

  if (typeof detail === "string") {
    return detail;
  }

  if (detail && typeof detail === "object") {
    return detail.message || detail.code || "Richiesta Gen4 non riuscita.";
  }

  return error?.message || "Richiesta Gen4 non riuscita.";
}

export function getGen4StatusTone(value) {
  const normalized = String(value ?? "").toUpperCase();

  if (
    ["ACTIVE", "CLOSED", "COMPLETED", "PROFITABLE_EVIDENCE"].includes(
      normalized
    )
  ) {
    return "positive";
  }

  if (
    ["COLLECTING", "OPEN", "PENDING_ENTRY", "WAITING_SAFETY"].includes(
      normalized
    )
  ) {
    return "warning";
  }

  if (
    ["REJECTED", "EXPIRED", "NEGATIVE_EVIDENCE", "ERROR"].includes(
      normalized
    )
  ) {
    return "danger";
  }

  return "neutral";
}

export function getLaneDefinition(lane) {
  return (
    GEN4_FORWARD_LANES.find((item) => item.key === lane) ?? {
      key: lane,
      label: lane || "Corsia sconosciuta",
      shortLabel: lane || "N/D",
      description: "",
      tone: "slate",
    }
  );
}

export function computeGen4Progress(campaign, now = new Date()) {
  if (!campaign) {
    return {
      observationDays: 0,
      observationTarget: 0,
      observationPercent: 0,
      strictClosed: 0,
      closedTarget: 0,
      closedPercent: 0,
      remainingObservationMs: 0,
    };
  }

  const anchor = new Date(campaign.anchor_at);
  const minimumComplete = new Date(campaign.minimum_complete_at);
  const observationMs = Math.max(0, now.getTime() - anchor.getTime());
  const targetMs = Math.max(1, minimumComplete.getTime() - anchor.getTime());
  const strictClosed = Number(campaign.strict_closed_trade_count ?? 0);
  const closedTarget = Math.max(1, Number(campaign.minimum_closed_trades ?? 30));

  return {
    observationDays: observationMs / 86_400_000,
    observationTarget: Number(campaign.minimum_observation_days ?? 21),
    observationPercent: Math.min(100, (observationMs / targetMs) * 100),
    strictClosed,
    closedTarget,
    closedPercent: Math.min(100, (strictClosed / closedTarget) * 100),
    remainingObservationMs: Math.max(0, minimumComplete.getTime() - now.getTime()),
  };
}

export function buildGen4EquitySeries(decisions) {
  const closed = (decisions ?? [])
    .filter(
      (row) =>
        row.status === "CLOSED" &&
        row.portfolio_accepted &&
        Number.isFinite(Number(row.pnl_sol))
    )
    .sort((left, right) => {
      const leftTime = new Date(left.exit_at || left.decision_at).getTime();
      const rightTime = new Date(right.exit_at || right.decision_at).getTime();
      return leftTime - rightTime;
    });

  const totals = Object.fromEntries(
    GEN4_FORWARD_LANES.map((lane) => [lane.key, 0])
  );

  return closed.map((row, index) => {
    totals[row.lane] =
      (totals[row.lane] ?? 0) + Number(row.pnl_sol ?? 0);

    return {
      index: index + 1,
      at: row.exit_at || row.decision_at,
      label: new Date(row.exit_at || row.decision_at).toLocaleDateString(
        "it-IT",
        { day: "2-digit", month: "2-digit" }
      ),
      strict: Number(totals.STRICT_GEN4_FORWARD.toFixed(8)),
      proxy: Number(totals.SIGNAL_ONLY_FORWARD.toFixed(8)),
      baseline: Number(
        totals.SIMPLE_COPY_FORWARD_BASELINE.toFixed(8)
      ),
    };
  });
}
