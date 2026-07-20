import { api } from "./api";


function getLiveTradingConfig(accessKey) {
  return {
    headers: {
      "X-Live-Trading-Key": String(
        accessKey ?? ""
      ).trim(),
    },
  };
}


export function getLiveTradingStatus(
  accessKey
) {
  return api.get(
    "/live-trading/status",
    getLiveTradingConfig(accessKey)
  );
}


export function getLiveTradingPolicy(
  accessKey
) {
  return api.get(
    "/live-trading/policy",
    getLiveTradingConfig(accessKey)
  );
}


export function updateLiveTradingPolicy(
  accessKey,
  payload
) {
  return api.patch(
    "/live-trading/policy",
    payload,
    getLiveTradingConfig(accessKey)
  );
}


export function resetLiveTradingDryRun(
  accessKey,
  payload
) {
  return api.post(
    "/live-trading/dry-run/reset",
    payload,
    getLiveTradingConfig(accessKey)
  );
}


export function engageLiveTradingKillSwitch(
  accessKey
) {
  return api.post(
    "/live-trading/kill-switch",
    null,
    getLiveTradingConfig(accessKey)
  );
}


export function releaseLiveTradingKillSwitch(
  accessKey,
  confirmation
) {
  return api.post(
    "/live-trading/kill-switch/release",
    {
      confirmation,
    },
    getLiveTradingConfig(accessKey)
  );
}


export function executeLiveTradingSourceTrade(
  accessKey,
  tradeId
) {
  return api.post(
    `/live-trading/execute/trades/${encodeURIComponent(
      tradeId
    )}`,
    null,
    getLiveTradingConfig(accessKey)
  );
}


export function closeLiveTradingDryRunPosition(
  accessKey,
  positionId
) {
  return api.post(
    `/live-trading/positions/${encodeURIComponent(
      positionId
    )}/close-dry-run`,
    {
      confirmation: "CLOSE DRY RUN POSITION",
    },
    getLiveTradingConfig(accessKey)
  );
}


export function getLiveTradingOrders(
  accessKey,
  {
    limit = 100,
    status = "",
    mode = "",
    scope = "ACTIVE",
  } = {}
) {
  return api.get(
    "/live-trading/orders",
    {
      ...getLiveTradingConfig(accessKey),
      params: {
        limit,
        status: status || undefined,
        mode: mode || undefined,
        scope,
      },
    }
  );
}


export function getLiveTradingPositions(
  accessKey,
  {
    status = "",
    mode = "",
    scope = "ACTIVE",
  } = {}
) {
  return api.get(
    "/live-trading/positions",
    {
      ...getLiveTradingConfig(accessKey),
      params: {
        status: status || undefined,
        mode: mode || undefined,
        scope,
      },
    }
  );
}


export function getLiveTradingEvents(
  accessKey,
  limit = 200,
  scope = "ACTIVE"
) {
  return api.get(
    "/live-trading/events",
    {
      ...getLiveTradingConfig(accessKey),
      params: {
        limit,
        scope,
      },
    }
  );
} 

export function getLivePlatformConfig(
  accessKey
) {
  return api.get(
    "/live-trading/platform/config",
    getLiveTradingConfig(accessKey)
  );
}


export function updateLivePlatformConfig(
  accessKey,
  payload
) {
  return api.patch(
    "/live-trading/platform/config",
    payload,
    getLiveTradingConfig(accessKey)
  );
}


export function getLiveTradingAnalytics(
  accessKey,
  {
    days = 30,
    mode = "DRY_RUN",
    generation,
  } = {}
) {
  return api.get(
    "/live-trading/platform/analytics",
    {
      ...getLiveTradingConfig(accessKey),
      params: {
        days,
        mode,
        generation,
      },
    }
  );
}


export function downloadLiveTradingAnalyticsCsv(
  accessKey,
  {
    days = 30,
    mode = "DRY_RUN",
    generation,
  } = {}
) {
  return api.get(
    "/live-trading/platform/analytics/export.csv",
    {
      ...getLiveTradingConfig(accessKey),
      params: {
        days,
        mode,
        generation,
      },
      responseType: "blob",
    }
  );
}


export function getLiveWalletRanking(
  accessKey
) {
  return api.get(
    "/live-trading/platform/wallet-ranking",
    getLiveTradingConfig(accessKey)
  );
}


export function refreshLiveWalletRanking(
  accessKey
) {
  return api.post(
    "/live-trading/platform/wallet-ranking/refresh",
    null,
    getLiveTradingConfig(accessKey)
  );
}


export function applyLiveTradingWalletRanking(
  accessKey,
  payload
) {
  return api.post(
    "/live-trading/platform/wallet-ranking/apply",
    payload,
    getLiveTradingConfig(accessKey)
  );
}


export function getLiveTokenSafety(
  accessKey,
  limit = 100
) {
  return api.get(
    "/live-trading/platform/token-safety",
    {
      ...getLiveTradingConfig(accessKey),
      params: { limit },
    }
  );
}


export function refreshLiveTokenSafety(
  accessKey,
  tokenMint
) {
  return api.post(
    `/live-trading/platform/token-safety/${encodeURIComponent(
      tokenMint
    )}/refresh`,
    null,
    getLiveTradingConfig(accessKey)
  );
}


export function getLiveTradingReadiness(
  accessKey
) {
  return api.get(
    "/live-trading/platform/readiness",
    getLiveTradingConfig(accessKey)
  );
}


export function armLiveTrading(
  accessKey,
  confirmation
) {
  return api.post(
    "/live-trading/platform/live/arm",
    { confirmation },
    getLiveTradingConfig(accessKey)
  );
}


export function disarmLiveTrading(
  accessKey
) {
  return api.post(
    "/live-trading/platform/live/disarm",
    null,
    getLiveTradingConfig(accessKey)
  );
}
