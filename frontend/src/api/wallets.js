import client from "./client";

export async function getWallets() {
    const { data } = await client.get("/wallets/ranking");
    return data;
}

export async function getWallet(wallet) {
    const { data } = await client.get(`/wallets/profile/${wallet}`);
    return data;
} 