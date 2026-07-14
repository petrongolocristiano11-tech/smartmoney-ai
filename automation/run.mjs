const DEFAULT_MAX_TOKENS = 3;
const DEFAULT_MAX_WALLETS_PER_TOKEN = 3;
const DEFAULT_TIMEOUT_MS = 10 * 60 * 1000;
const DEFAULT_DELAY_MS = 2000;

function requireEnvironmentVariable(name) {
  const value = String(
    process.env[name] ?? ""
  ).trim();

  if (!value) {
    throw new Error(
      `Variabile obbligatoria mancante: ${name}`
    );
  }

  return value;
}

function readInteger(
  name,
  defaultValue,
  minimum,
  maximum
) {
  const rawValue = process.env[name];

  if (
    rawValue === undefined ||
    String(rawValue).trim() === ""
  ) {
    return defaultValue;
  }

  const parsedValue = Number.parseInt(
    rawValue,
    10
  );

  if (!Number.isInteger(parsedValue)) {
    throw new Error(
      `${name} deve essere un numero intero.`
    );
  }

  return Math.min(
    maximum,
    Math.max(minimum, parsedValue)
  );
}

function normalizeBackendUrl(value) {
  return value.replace(/\/+$/, "");
}

function parseSeedWallets(value) {
  const wallets = value
    .split(",")
    .map((wallet) => wallet.trim())
    .filter(Boolean);

  return [...new Set(wallets)];
}

function sleep(milliseconds) {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

async function requestJson(
  url,
  {
    method = "GET",
    timeoutMs = DEFAULT_TIMEOUT_MS,
  } = {}
) {
  const controller = new AbortController();

  const timeoutId = setTimeout(() => {
    controller.abort();
  }, timeoutMs);

  try {
    const response = await fetch(url, {
      method,
      headers: {
        Accept: "application/json",
        "User-Agent":
          "SmartMoney-Automation/1.0",
      },
      signal: controller.signal,
    });

    const responseText =
      await response.text();

    let responseBody = null;

    if (responseText) {
      try {
        responseBody =
          JSON.parse(responseText);
      } catch {
        responseBody = responseText;
      }
    }

    if (!response.ok) {
      const errorDetails =
        typeof responseBody === "string"
          ? responseBody
          : JSON.stringify(responseBody);

      throw new Error(
        `HTTP ${response.status}: ${errorDetails}`
      );
    }

    return responseBody;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(
        `Richiesta scaduta dopo ${timeoutMs} ms`
      );
    }

    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

function buildDiscoveryUrl(
  backendUrl,
  wallet,
  maxTokens,
  maxWalletsPerToken
) {
  const url = new URL(
    `/trades/discovery/full/${encodeURIComponent(
      wallet
    )}`,
    backendUrl
  );

  url.searchParams.set(
    "max_tokens",
    String(maxTokens)
  );

  url.searchParams.set(
    "max_wallets_per_token",
    String(maxWalletsPerToken)
  );

  return url;
}

function summarizeResult(wallet, result) {
  return {
    wallet,
    seedTradesImported:
      result?.seed_trades_imported ?? null,
    seedTokensFound:
      result?.seed_tokens_found ?? null,
    tokensProcessed:
      result?.tokens_processed ?? 0,
    walletsDiscovered:
      result?.wallets_discovered ?? 0,
    rankingEntries:
      Array.isArray(result?.ranking)
        ? result.ranking.length
        : 0,
  };
}

async function main() {
  const startedAt = new Date();

  const backendUrl = normalizeBackendUrl(
    requireEnvironmentVariable(
      "BACKEND_URL"
    )
  );

  const seedWallets = parseSeedWallets(
    requireEnvironmentVariable(
      "SEED_WALLETS"
    )
  );

  if (seedWallets.length === 0) {
    throw new Error(
      "SEED_WALLETS non contiene wallet validi."
    );
  }

  const maxTokens = readInteger(
    "MAX_TOKENS",
    DEFAULT_MAX_TOKENS,
    1,
    10
  );

  const maxWalletsPerToken = readInteger(
    "MAX_WALLETS_PER_TOKEN",
    DEFAULT_MAX_WALLETS_PER_TOKEN,
    1,
    10
  );

  const timeoutMs = readInteger(
    "REQUEST_TIMEOUT_MS",
    DEFAULT_TIMEOUT_MS,
    30_000,
    30 * 60 * 1000
  );

  const delayMs = readInteger(
    "SEED_DELAY_MS",
    DEFAULT_DELAY_MS,
    0,
    60_000
  );

  console.log(
    JSON.stringify({
      event: "automation_started",
      timestamp: startedAt.toISOString(),
      seedWallets: seedWallets.length,
      maxTokens,
      maxWalletsPerToken,
    })
  );

  const readinessUrl = new URL(
    "/ready",
    backendUrl
  );

  const readiness = await requestJson(
    readinessUrl,
    {
      timeoutMs: 60_000,
    }
  );

  if (readiness?.status !== "ready") {
    throw new Error(
      `Backend non pronto: ${JSON.stringify(
        readiness
      )}`
    );
  }

  console.log(
    JSON.stringify({
      event: "backend_ready",
      database:
        readiness?.dependencies?.database ??
        "unknown",
    })
  );

  const successfulRuns = [];
  const failedRuns = [];

  for (
    let index = 0;
    index < seedWallets.length;
    index += 1
  ) {
    const wallet = seedWallets[index];

    console.log(
      JSON.stringify({
        event: "discovery_started",
        wallet,
        position: index + 1,
        total: seedWallets.length,
      })
    );

    try {
      const discoveryUrl =
        buildDiscoveryUrl(
          backendUrl,
          wallet,
          maxTokens,
          maxWalletsPerToken
        );

      const result = await requestJson(
        discoveryUrl,
        {
          method: "POST",
          timeoutMs,
        }
      );

      const summary = summarizeResult(
        wallet,
        result
      );

      successfulRuns.push(summary);

      console.log(
        JSON.stringify({
          event: "discovery_completed",
          ...summary,
        })
      );
    } catch (error) {
      const failure = {
        wallet,
        error:
          error instanceof Error
            ? error.message
            : String(error),
      };

      failedRuns.push(failure);

      console.error(
        JSON.stringify({
          event: "discovery_failed",
          ...failure,
        })
      );
    }

    const hasAnotherWallet =
      index < seedWallets.length - 1;

    if (hasAnotherWallet && delayMs > 0) {
      await sleep(delayMs);
    }
  }

  const finishedAt = new Date();

  console.log(
    JSON.stringify({
      event: "automation_completed",
      startedAt: startedAt.toISOString(),
      finishedAt: finishedAt.toISOString(),
      durationSeconds: Math.round(
        (finishedAt.getTime() -
          startedAt.getTime()) /
          1000
      ),
      successfulRuns:
        successfulRuns.length,
      failedRuns: failedRuns.length,
      results: successfulRuns,
    })
  );

  if (successfulRuns.length === 0) {
    throw new Error(
      "Nessuna Discovery completata."
    );
  }
}

main().catch((error) => {
  console.error(
    JSON.stringify({
      event: "automation_crashed",
      timestamp: new Date().toISOString(),
      error:
        error instanceof Error
          ? error.message
          : String(error),
    })
  );

  process.exitCode = 1;
}); 