import axios from "axios";

const API_URL = "http://127.0.0.1:8000";

export function getDiscoveredWallets() {
  return axios.get(`${API_URL}/discovered-wallets`);
}

export function runDiscovery(walletAddress) {
  return axios.post(
    `${API_URL}/trades/discovery/full/${walletAddress}`,
    null,
    {
      params: {
        max_tokens: 3,
        max_wallets_per_token: 3,
      },
    }
  );
} 