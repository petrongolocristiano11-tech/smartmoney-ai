import axios from "axios";


const DEFAULT_API_URL =
  "http://127.0.0.1:8000";


function normalizeApiUrl(value) {
  const normalizedValue = String(
    value ?? ""
  ).trim();

  if (!normalizedValue) {
    return DEFAULT_API_URL;
  }

  return normalizedValue.replace(
    /\/+$/,
    ""
  );
}


export const API_URL =
  normalizeApiUrl(
    import.meta.env.VITE_API_URL
  );


export const api = axios.create({
  baseURL: API_URL,
  timeout: 120000,
  headers: {
    Accept: "application/json",
  },
});


// =========================
// DASHBOARD
// =========================

export function getDashboard() {
  return api.get(
    "/scanner/dashboard"
  );
}


// =========================
// DISCOVERED WALLETS
// =========================

export function getDiscoveredWallets(
  minScore = 0,
  limit = 100
) {
  return api.get(
    "/discovered-wallets",
    {
      params: {
        min_score: minScore,
        limit,
      },
    }
  );
}


export function getWallet(
  walletAddress
) {
  return api.get(
    `/discovered-wallets/${encodeURIComponent(
      walletAddress
    )}`
  );
}


export function refreshDiscoveredWalletActivity(
  limit = 250
) {
  return api.post(
    "/discovered-wallets/activity/refresh",
    null,
    {
      params: { limit },
    }
  );
}


export function refreshDiscoveredWalletQuality(
  limit = 250
) {
  return api.post(
    "/discovered-wallets/quality/refresh",
    null,
    {
      params: { limit },
    }
  );
}


export function runControlledDiscoveryHydration({
  maxWallets = 3,
  maxHeliusRequests = 3,
  lookbackDays = 7,
  transactionLimit = 100,
  minimumSmartScore = 0,
  force = false,
} = {}) {
  return api.post(
    "/discovered-wallets/hydration/run",
    null,
    {
      params: {
        max_wallets: maxWallets,
        max_helius_requests: maxHeliusRequests,
        lookback_days: lookbackDays,
        transaction_limit: transactionLimit,
        minimum_smart_score: minimumSmartScore,
        force,
      },
    }
  );
}


export function runExtendedCandidateHistoryBackfill({
  walletAddress,
  lookbackDays = 30,
  maxHeliusRequests = 5,
  pageSize = 100,
  force = false,
}) {
  return api.post(
    "/discovered-wallets/promotion/history/backfill",
    {
      wallet_address: walletAddress,
      lookback_days: lookbackDays,
      max_helius_requests: maxHeliusRequests,
      page_size: pageSize,
      force,
    }
  );
}


export function getLatestExtendedCandidateHistory(walletAddress) {
  return api.get(
    `/discovered-wallets/promotion/history/${encodeURIComponent(walletAddress)}/latest`
  );
}


export function runCandidatePromotionBacktest({
  walletAddress,
  lookbackDays = 30,
  warmupDays = 14,
  startingCapitalSol = 1,
  fixedBuySizeSol = 0.05,
  slippageBps = 100,
  feeBps = 10,
  copyDelaySeconds = 8,
  delayPenaltyBpsPerMinute = 25,
  maxOpenPositions = 5,
  checkJupiter = true,
  jupiterTokenLimit = 10,
  jupiterCacheTtlHours = 6,
  forceJupiterRefresh = false,
}) {
  return api.post(
    "/discovered-wallets/promotion/backtest",
    {
      wallet_address: walletAddress,
      lookback_days: lookbackDays,
      warmup_days: warmupDays,
      starting_capital_sol: startingCapitalSol,
      fixed_buy_size_sol: fixedBuySizeSol,
      slippage_bps: slippageBps,
      fee_bps: feeBps,
      copy_delay_seconds: copyDelaySeconds,
      delay_penalty_bps_per_minute: delayPenaltyBpsPerMinute,
      max_open_positions: maxOpenPositions,
      check_jupiter: checkJupiter,
      jupiter_token_limit: jupiterTokenLimit,
      jupiter_cache_ttl_hours: jupiterCacheTtlHours,
      force_jupiter_refresh: forceJupiterRefresh,
    }
  );
}


export function getLatestCandidatePromotionBacktest(walletAddress) {
  return api.get(
    `/discovered-wallets/promotion/${encodeURIComponent(walletAddress)}/latest`
  );
}


// =========================
// WALLET INTELLIGENCE
// =========================

export function getWalletRanking() {
  return api.get(
    "/trades/ranking"
  );
}


export function getWalletProfile(
  walletAddress
) {
  return api.get(
    `/trades/profile/${encodeURIComponent(
      walletAddress
    )}`
  );
}


export function getWalletSmartScore(
  walletAddress
) {
  return api.get(
    `/trades/smart-score/${encodeURIComponent(
      walletAddress
    )}`
  );
}


export function getWalletTrades(
  walletAddress
) {
  return api.get(
    `/trades/wallet/${encodeURIComponent(
      walletAddress
    )}`
  );
}


export function getWalletNetwork(
  walletAddress
) {
  return api.get(
    `/trades/network/${encodeURIComponent(
      walletAddress
    )}`
  );
}


export function getWalletPortfolio(
  walletAddress
) {
  return api.get(
    `/trades/portfolio/${encodeURIComponent(
      walletAddress
    )}`
  );
}


// =========================
// BACKTESTING
// =========================

export function getWalletBacktest(
  walletAddress
) {
  return api.get(
    `/trades/backtest/${encodeURIComponent(
      walletAddress
    )}`
  );
}


export function getCopyTradingSimulation(
  walletAddress,
  startingCapital = 10
) {
  return api.get(
    `/trades/copy/${encodeURIComponent(
      walletAddress
    )}`,
    {
      params: {
        starting_capital:
          startingCapital,
      },
    }
  );
}


// =========================
// TOKEN INTELLIGENCE
// =========================

export function getTokenIntelligence(
  tokenMint
) {
  return api.get(
    `/tokens/${encodeURIComponent(
      tokenMint
    )}`
  );
}


// =========================
// DISCOVERY
// =========================

export function runDiscovery(
  walletAddress,
  maxTokens = 3,
  maxWalletsPerToken = 3
) {
  return api.post(
    `/trades/discovery/full/${encodeURIComponent(
      walletAddress
    )}`,
    null,
    {
      params: {
        max_tokens: maxTokens,
        max_wallets_per_token:
          maxWalletsPerToken,
      },
    }
  );
}


export function runSmartDiscovery(
  walletAddress,
  maxDepth = 2,
  maxTokensPerWallet = 5,
  maxWalletsPerToken = 5,
  minSmartScore = 60
) {
  return api.post(
    `/trades/discovery/smart/${encodeURIComponent(
      walletAddress
    )}`,
    null,
    {
      params: {
        max_depth: maxDepth,
        max_tokens_per_wallet:
          maxTokensPerWallet,
        max_wallets_per_token:
          maxWalletsPerToken,
        min_smart_score:
          minSmartScore,
      },
    }
  );
}


// =========================
// PAPER TRADING
// =========================

function getPaperTradingConfig(
  accessKey
) {
  return {
    headers: {
      "X-Paper-Trading-Key":
        String(
          accessKey ?? ""
        ).trim(),
    },
  };
}


export function getPaperAccounts(
  accessKey
) {
  return api.get(
    "/paper-trading/accounts",
    getPaperTradingConfig(
      accessKey
    )
  );
}


export function createPaperAccount(
  accessKey,
  payload
) {
  return api.post(
    "/paper-trading/accounts",
    payload,
    getPaperTradingConfig(
      accessKey
    )
  );
}


export function getPaperAccount(
  accessKey,
  accountId
) {
  return api.get(
    `/paper-trading/accounts/${accountId}`,
    getPaperTradingConfig(
      accessKey
    )
  );
}


export function updatePaperAccount(
  accessKey,
  accountId,
  payload
) {
  return api.patch(
    `/paper-trading/accounts/${accountId}`,
    payload,
    getPaperTradingConfig(
      accessKey
    )
  );
}


export function resetPaperAccount(
  accessKey,
  accountId,
  confirmationName
) {
  return api.post(
    `/paper-trading/accounts/${accountId}/reset`,
    {
      confirmation_name:
        confirmationName,
    },
    getPaperTradingConfig(
      accessKey
    )
  );
}


export function getPaperTokenPrice(
  accessKey,
  tokenMint,
  forceRefresh = false
) {
  return api.get(
    `/paper-trading/prices/${encodeURIComponent(
      tokenMint
    )}`,
    {
      ...getPaperTradingConfig(
        accessKey
      ),
      params: {
        force_refresh:
          forceRefresh,
      },
    }
  );
}


export function refreshPaperAccountPrices(
  accessKey,
  accountId,
  forceRefresh = false
) {
  return api.post(
    `/paper-trading/accounts/${accountId}/refresh-prices`,
    null,
    {
      ...getPaperTradingConfig(
        accessKey
      ),
      params: {
        force_refresh:
          forceRefresh,
      },
    }
  );
}


export function buyPaperToken(
  accessKey,
  accountId,
  payload
) {
  return api.post(
    `/paper-trading/accounts/${accountId}/buy`,
    payload,
    getPaperTradingConfig(
      accessKey
    )
  );
}


export function sellPaperToken(
  accessKey,
  accountId,
  payload
) {
  return api.post(
    `/paper-trading/accounts/${accountId}/sell`,
    payload,
    getPaperTradingConfig(
      accessKey
    )
  );
}

// =========================
// PAPER AUTOPILOT
// =========================

export function getPaperAutopilot(
  accessKey,
  accountId
) {
  return api.get(
    `/paper-autopilot/accounts/${accountId}`,
    getPaperTradingConfig(
      accessKey
    )
  );
}


export function updatePaperAutopilotPolicy(
  accessKey,
  accountId,
  payload
) {
  return api.patch(
    `/paper-autopilot/accounts/${accountId}/policy`,
    payload,
    getPaperTradingConfig(
      accessKey
    )
  );
}


export function runPaperAutopilot(
  accessKey,
  accountId
) {
  return api.post(
    `/paper-autopilot/accounts/${accountId}/run`,
    null,
    getPaperTradingConfig(
      accessKey
    )
  );
}
