import axios from "axios";

const API_URL = "http://127.0.0.1:8000";

export function getDiscoveredWallets() {
  return axios.get(`${API_URL}/discovered-wallets`);
}

export function getWalletRanking() {
  return axios.get(`${API_URL}/trades/ranking`);
}

export function getWalletProfile(walletAddress) {
  return axios.get(`${API_URL}/trades/profile/${walletAddress}`);
}

export function getWallet(walletAddress) {
  return axios.get(`${API_URL}/discovered-wallets/${walletAddress}`);
}

export function getWalletTrades(walletAddress) {
  return axios.get(`${API_URL}/trades/wallet/${walletAddress}`);
}

export function getWalletNetwork(walletAddress) {
  return axios.get(`${API_URL}/trades/network/${walletAddress}`);
}

export function runDiscovery(walletAddress, maxTokens = 3, maxWalletsPerToken = 3) {
  return axios.post(
    `${API_URL}/trades/discovery/full/${walletAddress}`,
    null,
    {
      params: {
        max_tokens: maxTokens,
        max_wallets_per_token: maxWalletsPerToken,
      },
    }
  );
} 