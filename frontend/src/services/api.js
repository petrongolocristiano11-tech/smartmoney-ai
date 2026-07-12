import axios from "axios";

const API_URL = "http://127.0.0.1:8000";

export const api = axios.create({
  baseURL: API_URL,
  timeout: 120000,
});

// =========================
// DASHBOARD
// =========================

export function getDashboard() {
  return api.get("/scanner/dashboard");
}

// =========================
// DISCOVERED WALLETS
// =========================

export function getDiscoveredWallets(
  minScore = 0,
  limit = 100
) {
  return api.get("/discovered-wallets", {
    params: {
      min_score: minScore,
      limit,
    },
  });
}

export function getWallet(walletAddress) {
  return api.get(
    `/discovered-wallets/${encodeURIComponent(
      walletAddress
    )}`
  );
}

// =========================
// WALLET INTELLIGENCE
// =========================

export function getWalletRanking() {
  return api.get("/trades/ranking");
}

export function getWalletProfile(walletAddress) {
  return api.get(
    `/trades/profile/${encodeURIComponent(
      walletAddress
    )}`
  );
}

export function getWalletTrades(walletAddress) {
  return api.get(
    `/trades/wallet/${encodeURIComponent(
      walletAddress
    )}`
  );
}

export function getWalletNetwork(walletAddress) {
  return api.get(
    `/trades/network/${encodeURIComponent(
      walletAddress
    )}`
  );
}

// =========================
// TOKEN INTELLIGENCE
// =========================

export function getTokenIntelligence(tokenMint) {
  return api.get(
    `/tokens/${encodeURIComponent(tokenMint)}`
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
        max_wallets_per_token: maxWalletsPerToken,
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
        max_tokens_per_wallet: maxTokensPerWallet,
        max_wallets_per_token: maxWalletsPerToken,
        min_smart_score: minSmartScore,
      },
    }
  );
} 