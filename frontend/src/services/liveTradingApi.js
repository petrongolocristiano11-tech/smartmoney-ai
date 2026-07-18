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


export function getLiveTradingOrders(
  accessKey,
  {
    limit = 100,
    status = "",
    mode = "",
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
      },
    }
  );
}


export function getLiveTradingPositions(
  accessKey,
  {
    status = "",
    mode = "",
  } = {}
) {
  return api.get(
    "/live-trading/positions",
    {
      ...getLiveTradingConfig(accessKey),
      params: {
        status: status || undefined,
        mode: mode || undefined,
      },
    }
  );
}


export function getLiveTradingEvents(
  accessKey,
  limit = 200
) {
  return api.get(
    "/live-trading/events",
    {
      ...getLiveTradingConfig(accessKey),
      params: {
        limit,
      },
    }
  );
} 