import { pathToFileURL } from "node:url";


const DEFAULT_MAX_TOKENS = 3;

const DEFAULT_MAX_WALLETS_PER_TOKEN = 3;

const DEFAULT_TIMEOUT_MS =
  10 * 60 * 1000;

const DEFAULT_DELAY_MS = 2000;

const DEFAULT_DISCOVERY_INTERVAL_HOURS =
  6;


export function requireEnvironmentVariable(
  name,
  environment = process.env
) {
  const value = String(
    environment[name] ?? ""
  ).trim();

  if (!value) {
    throw new Error(
      `Variabile obbligatoria mancante: ${name}`
    );
  }

  return value;
}


export function readInteger(
  name,
  defaultValue,
  minimum,
  maximum,
  environment = process.env
) {
  const rawValue =
    environment[name];

  if (
    rawValue === undefined
    || String(rawValue).trim() === ""
  ) {
    return defaultValue;
  }

  const parsedValue =
    Number.parseInt(
      String(rawValue),
      10
    );

  if (
    !Number.isInteger(
      parsedValue
    )
  ) {
    throw new Error(
      `${name} deve essere un numero intero.`
    );
  }

  return Math.min(
    maximum,
    Math.max(
      minimum,
      parsedValue
    )
  );
}


export function readBoolean(
  name,
  defaultValue,
  environment = process.env
) {
  const rawValue =
    environment[name];

  if (
    rawValue === undefined
    || String(rawValue).trim() === ""
  ) {
    return defaultValue;
  }

  const normalized = String(
    rawValue
  ).trim().toLowerCase();

  if (
    [
      "1",
      "true",
      "yes",
      "on",
    ].includes(normalized)
  ) {
    return true;
  }

  if (
    [
      "0",
      "false",
      "no",
      "off",
    ].includes(normalized)
  ) {
    return false;
  }

  throw new Error(
    `${name} deve essere true oppure false.`
  );
}


export function normalizeBackendUrl(
  value
) {
  return String(
    value
  ).replace(
    /\/+$/,
    ""
  );
}


export function parseSeedWallets(
  value
) {
  const wallets = String(
    value ?? ""
  )
    .split(",")
    .map(
      (wallet) =>
        wallet.trim()
    )
    .filter(Boolean);

  return [
    ...new Set(wallets),
  ];
}


export function isDiscoveryDue(
  date,
  intervalHours
) {
  if (intervalHours <= 1) {
    return true;
  }

  return (
    date.getUTCHours()
    % intervalHours
    === 0
  );
}


function sleep(
  milliseconds
) {
  return new Promise(
    (resolve) => {
      setTimeout(
        resolve,
        milliseconds
      );
    }
  );
}


export function redactSecrets(
  value
) {
  return String(value ?? "")
    .replace(
      /(api-key=)[^&\s'"]+/gi,
      "$1REDACTED"
    )
    .replace(
      /(x-automation-key[=:]\s*)[^&\s'"]+/gi,
      "$1REDACTED"
    );
}


export async function requestJson(
  url,
  {
    method = "GET",
    timeoutMs =
      DEFAULT_TIMEOUT_MS,
    headers = {},
  } = {}
) {
  const controller =
    new AbortController();

  const timeoutId =
    setTimeout(
      () => {
        controller.abort();
      },
      timeoutMs
    );

  try {
    const response =
      await fetch(
        url,
        {
          method,
          headers: {
            Accept:
              "application/json",
            "User-Agent":
              "SmartMoney-Automation/2.0",
            ...headers,
          },
          signal:
            controller.signal,
        }
      );

    const responseText =
      await response.text();

    let responseBody = null;

    if (responseText) {
      try {
        responseBody =
          JSON.parse(
            responseText
          );
      } catch {
        responseBody =
          responseText;
      }
    }

    if (!response.ok) {
      const errorDetails =
        typeof responseBody
          === "string"
          ? responseBody
          : JSON.stringify(
              responseBody
            );

      throw new Error(
        `HTTP ${response.status}: ${redactSecrets(errorDetails)}`
      );
    }

    return responseBody;
  } catch (error) {
    if (
      error instanceof Error
      && error.name
      === "AbortError"
    ) {
      throw new Error(
        `Richiesta scaduta dopo ${timeoutMs} ms`
      );
    }

    throw error;
  } finally {
    clearTimeout(
      timeoutId
    );
  }
}


export function buildDiscoveryUrl(
  backendUrl,
  wallet,
  maxTokens,
  maxWalletsPerToken
) {
  const url = new URL(
    `/trades/discovery/automation/${encodeURIComponent(
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
    String(
      maxWalletsPerToken
    )
  );

  return url;
}


export function buildAutopilotUrl(
  backendUrl
) {
  return new URL(
    "/paper-autopilot/automation/run",
    backendUrl
  );
}


export function summarizeDiscoveryResult(
  wallet,
  result
) {
  const rawStatus = String(
    result?.status ?? "COMPLETED"
  ).toUpperCase();

  const status = [
    "COMPLETED",
    "PARTIAL",
    "FAILED",
  ].includes(rawStatus)
    ? rawStatus
    : "PARTIAL";

  return {
    wallet,
    status,

    seedSyncStatus:
      result?.seed_sync_status
      ?? null,

    seedTradesImported:
      result?.seed_trades_imported
      ?? null,

    seedTokensFound:
      result?.seed_tokens_found
      ?? null,

    tokensAttempted:
      result?.tokens_attempted
      ?? result?.tokens_processed
      ?? 0,

    tokensProcessed:
      result?.tokens_processed
      ?? 0,

    tokensFailed:
      result?.tokens_failed
      ?? 0,

    walletsDiscovered:
      result?.wallets_discovered
      ?? 0,

    walletsAnalyzed:
      result?.wallets_analyzed
      ?? (
        Array.isArray(result?.ranking)
          ? result.ranking.length
          : 0
      ),

    walletsFailed:
      result?.wallets_failed
      ?? 0,

    rankingEntries:
      Array.isArray(result?.ranking)
        ? result.ranking.length
        : 0,

    errors:
      Array.isArray(result?.errors)
        ? result.errors
        : [],
  };
}


export function summarizeAutopilotResult(
  result
) {
  return {
    processedAccounts:
      Number(
        result?.processed_accounts
        ?? 0
      ),

    successfulRuns:
      Number(
        result?.successful_runs
        ?? 0
      ),

    failedRuns:
      Number(
        result?.failed_runs
        ?? 0
      ),

    results:
      Array.isArray(result?.results)
        ? result.results
        : [],
  };
}


export function classifyDiscoverySummary(
  summary
) {
  const warnings = [];

  if (!summary?.due) {
    return warnings;
  }

  const partialRuns =
    summary?.partialRuns?.length
    ?? 0;

  const failedRuns =
    summary?.failedRuns?.length
    ?? 0;

  if (partialRuns > 0) {
    warnings.push(
      "Discovery completate parzialmente: "
      + String(partialRuns)
      + "."
    );
  }

  if (failedRuns > 0) {
    warnings.push(
      "Discovery non completate: "
      + String(failedRuns)
      + "."
    );
  }

  return warnings;
}


export function classifyAutopilotSummary(
  summary
) {
  const warnings = [];
  const criticalFailures = [];

  if (!summary) {
    return {
      warnings,
      criticalFailures,
    };
  }

  const processed =
    Number(summary.processedAccounts ?? 0);
  const successful =
    Number(summary.successfulRuns ?? 0);
  const failed =
    Number(summary.failedRuns ?? 0);

  if (
    processed > 0
    && successful === 0
    && failed > 0
  ) {
    criticalFailures.push(
      "Autopilot completamente fallito: "
      + `${failed} esecuzioni fallite.`
    );
  } else if (failed > 0) {
    warnings.push(
      "Autopilot completato parzialmente: "
      + `${failed} esecuzioni fallite.`
    );
  }

  if (processed === 0) {
    warnings.push(
      "Autopilot completato senza account da processare."
    );
  }

  return {
    warnings,
    criticalFailures,
  };
}


async function runDiscovery({
  backendUrl,
  automationApiKey,
  seedWallets,
  maxTokens,
  maxWalletsPerToken,
  timeoutMs,
  delayMs,
}) {
  const successfulRuns = [];
  const partialRuns = [];
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

      const result =
        await requestJson(
          discoveryUrl,
          {
            method: "POST",
            timeoutMs,
            headers: {
              "X-Automation-Key":
                automationApiKey,
            },
          }
        );

      const summary =
        summarizeDiscoveryResult(
          wallet,
          result
        );

      if (summary.status === "FAILED") {
        failedRuns.push(summary);
        console.error(
          JSON.stringify({
            event: "discovery_failed",
            ...summary,
          })
        );
      } else if (
        summary.status === "PARTIAL"
      ) {
        partialRuns.push(summary);
        console.warn(
          JSON.stringify({
            event: "discovery_partial",
            ...summary,
          })
        );
      } else {
        successfulRuns.push(summary);
        console.log(
          JSON.stringify({
            event: "discovery_completed",
            ...summary,
          })
        );
      }
    } catch (error) {
      const failure = {
        wallet,
        status: "FAILED",
        error:
          redactSecrets(
            error instanceof Error
              ? error.message
              : String(error)
          ),
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

    if (
      hasAnotherWallet
      && delayMs > 0
    ) {
      await sleep(delayMs);
    }
  }

  return {
    successfulRuns,
    partialRuns,
    failedRuns,
  };
}


async function runAutopilot({
  backendUrl,
  automationApiKey,
  timeoutMs,
}) {
  console.log(
    JSON.stringify({
      event: "autopilot_started",
      timestamp: new Date().toISOString(),
    })
  );

  const result =
    await requestJson(
      buildAutopilotUrl(backendUrl),
      {
        method: "POST",
        timeoutMs,
        headers: {
          "X-Automation-Key":
            automationApiKey,
        },
      }
    );

  const summary =
    summarizeAutopilotResult(result);

  console.log(
    JSON.stringify({
      event: "autopilot_completed",
      ...summary,
    })
  );

  return summary;
}


export async function main(
  environment = process.env
) {
  const startedAt = new Date();

  const backendUrl =
    normalizeBackendUrl(
      requireEnvironmentVariable(
        "BACKEND_URL",
        environment
      )
    );

  const automationApiKey =
    requireEnvironmentVariable(
      "AUTOMATION_API_KEY",
      environment
    );

  const discoveryEnabled =
    readBoolean(
      "DISCOVERY_ENABLED",
      true,
      environment
    );

  const autopilotEnabled =
    readBoolean(
      "AUTOPILOT_ENABLED",
      true,
      environment
    );

  if (
    !discoveryEnabled
    && !autopilotEnabled
  ) {
    throw new Error(
      "DISCOVERY_ENABLED e "
      + "AUTOPILOT_ENABLED non "
      + "possono essere entrambi false."
    );
  }

  const discoveryIntervalHours =
    readInteger(
      "DISCOVERY_INTERVAL_HOURS",
      DEFAULT_DISCOVERY_INTERVAL_HOURS,
      1,
      24,
      environment
    );

  const discoveryDue =
    discoveryEnabled
    && isDiscoveryDue(
      startedAt,
      discoveryIntervalHours
    );

  const seedWallets =
    parseSeedWallets(
      environment.SEED_WALLETS
    );

  const maxTokens =
    readInteger(
      "MAX_TOKENS",
      DEFAULT_MAX_TOKENS,
      1,
      10,
      environment
    );

  const maxWalletsPerToken =
    readInteger(
      "MAX_WALLETS_PER_TOKEN",
      DEFAULT_MAX_WALLETS_PER_TOKEN,
      1,
      10,
      environment
    );

  const timeoutMs =
    readInteger(
      "REQUEST_TIMEOUT_MS",
      DEFAULT_TIMEOUT_MS,
      30_000,
      30 * 60 * 1000,
      environment
    );

  const delayMs =
    readInteger(
      "SEED_DELAY_MS",
      DEFAULT_DELAY_MS,
      0,
      60_000,
      environment
    );

  console.log(
    JSON.stringify({
      event: "automation_started",
      timestamp: startedAt.toISOString(),
      authentication: "x-automation-key",
      discoveryEnabled,
      discoveryDue,
      discoveryIntervalHours,
      seedWallets: seedWallets.length,
      maxTokens,
      maxWalletsPerToken,
      autopilotEnabled,
    })
  );

  const readiness =
    await requestJson(
      new URL("/ready", backendUrl),
      {
        timeoutMs: 60_000,
      }
    );

  if (readiness?.status !== "ready") {
    throw new Error(
      "Backend non pronto: "
      + JSON.stringify(readiness)
    );
  }

  console.log(
    JSON.stringify({
      event: "backend_ready",
      database:
        readiness?.dependencies?.database
        ?? "unknown",
    })
  );

  const warnings = [];
  const criticalFailures = [];

  let discoverySummary = {
    due: discoveryDue,
    successfulRuns: [],
    partialRuns: [],
    failedRuns: [],
  };

  if (discoveryDue) {
    if (seedWallets.length === 0) {
      const message =
        "SEED_WALLETS non contiene wallet validi.";

      discoverySummary.failedRuns.push({
        wallet: null,
        status: "FAILED",
        error: message,
      });

      criticalFailures.push(message);

      console.error(
        JSON.stringify({
          event: "discovery_failed",
          wallet: null,
          error: message,
        })
      );
    } else {
      const result =
        await runDiscovery({
          backendUrl,
          automationApiKey,
          seedWallets,
          maxTokens,
          maxWalletsPerToken,
          timeoutMs,
          delayMs,
        });

      discoverySummary = {
        due: true,
        ...result,
      };

      warnings.push(
        ...classifyDiscoverySummary(
          discoverySummary
        )
      );
    }
  } else {
    console.log(
      JSON.stringify({
        event: "discovery_skipped",
        reason:
          discoveryEnabled
            ? "INTERVAL_NOT_DUE"
            : "DISABLED",
        intervalHours:
          discoveryEnabled
            ? discoveryIntervalHours
            : null,
      })
    );
  }

  let autopilotSummary = null;

  if (autopilotEnabled) {
    try {
      autopilotSummary =
        await runAutopilot({
          backendUrl,
          automationApiKey,
          timeoutMs,
        });

      const classification =
        classifyAutopilotSummary(
          autopilotSummary
        );

      warnings.push(
        ...classification.warnings
      );
      criticalFailures.push(
        ...classification.criticalFailures
      );
    } catch (error) {
      const message =
        redactSecrets(
          error instanceof Error
            ? error.message
            : String(error)
        );

      criticalFailures.push(
        "Autopilot non completato: "
        + message
      );

      console.error(
        JSON.stringify({
          event: "autopilot_failed",
          error: message,
        })
      );
    }
  } else {
    console.log(
      JSON.stringify({
        event: "autopilot_skipped",
        reason: "DISABLED",
      })
    );
  }

  const finishedAt = new Date();
  const status =
    criticalFailures.length > 0
      ? "FAILED"
      : warnings.length > 0
        ? "DEGRADED"
        : "COMPLETED";

  const discoveryResults = [
    ...discoverySummary.successfulRuns,
    ...discoverySummary.partialRuns,
    ...discoverySummary.failedRuns,
  ];

  const report = {
    event: "automation_completed",
    status,
    startedAt: startedAt.toISOString(),
    finishedAt: finishedAt.toISOString(),
    durationSeconds:
      Math.round(
        (
          finishedAt.getTime()
          - startedAt.getTime()
        ) / 1000
      ),
    discovery: {
      due: discoverySummary.due,
      successfulRuns:
        discoverySummary.successfulRuns.length,
      partialRuns:
        discoverySummary.partialRuns.length,
      failedRuns:
        discoverySummary.failedRuns.length,
      results: discoveryResults,
    },
    autopilot: autopilotSummary,
    warnings,
    criticalFailures,
  };

  console.log(JSON.stringify(report));

  if (criticalFailures.length > 0) {
    throw new Error(
      criticalFailures.join(" | ")
    );
  }

  return report;
}


const executedDirectly =
  Boolean(process.argv[1])
  && import.meta.url
  === pathToFileURL(
    process.argv[1]
  ).href;


if (executedDirectly) {
  main().catch(
    (error) => {
      console.error(
        JSON.stringify({
          event: "automation_crashed",
          timestamp: new Date().toISOString(),
          error:
            redactSecrets(
              error instanceof Error
                ? error.message
                : String(error)
            ),
        })
      );

      process.exitCode = 1;
    }
  );
}
