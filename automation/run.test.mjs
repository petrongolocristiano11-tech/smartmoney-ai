import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAutopilotUrl,
  classifyAutopilotSummary,
  classifyDiscoverySummary,
  isDiscoveryDue,
  main,
  parseSeedWallets,
  readBoolean,
  readInteger,
  redactSecrets,
  summarizeAutopilotResult,
  summarizeDiscoveryResult,
} from "./run.mjs";


test(
  "parseSeedWallets normalizza e rimuove duplicati",
  () => {
    assert.deepEqual(
      parseSeedWallets(" A, B, A, ,C "),
      ["A", "B", "C"]
    );
  }
);


test(
  "readBoolean accetta valori standard",
  () => {
    assert.equal(
      readBoolean(
        "FLAG",
        false,
        { FLAG: "true" }
      ),
      true
    );

    assert.equal(
      readBoolean(
        "FLAG",
        true,
        { FLAG: "off" }
      ),
      false
    );
  }
);


test(
  "readInteger rispetta i limiti",
  () => {
    assert.equal(
      readInteger(
        "LIMIT",
        3,
        1,
        10,
        { LIMIT: "99" }
      ),
      10
    );
  }
);


test(
  "Discovery usa le ore UTC previste",
  () => {
    assert.equal(
      isDiscoveryDue(
        new Date("2026-07-17T12:00:00Z"),
        6
      ),
      true
    );

    assert.equal(
      isDiscoveryDue(
        new Date("2026-07-17T13:00:00Z"),
        6
      ),
      false
    );
  }
);


test(
  "URL e riepilogo Autopilot sono corretti",
  () => {
    assert.equal(
      buildAutopilotUrl(
        "https://backend.example"
      ).toString(),
      (
        "https://backend.example/"
        + "paper-autopilot/"
        + "automation/run"
      )
    );

    assert.deepEqual(
      summarizeAutopilotResult({
        processed_accounts: 2,
        successful_runs: 1,
        failed_runs: 1,
        results: [{ success: true }],
      }),
      {
        processedAccounts: 2,
        successfulRuns: 1,
        failedRuns: 1,
        results: [{ success: true }],
      }
    );
  }
);


test(
  "Discovery PARTIAL viene riepilogata senza trasformarla in crash",
  () => {
    const summary = summarizeDiscoveryResult(
      "wallet-1",
      {
        status: "PARTIAL",
        tokens_attempted: 3,
        tokens_processed: 2,
        tokens_failed: 1,
        wallets_discovered: 5,
        wallets_analyzed: 4,
        wallets_failed: 1,
        errors: [
          {
            error_code: "HELIUS_RETRY_EXHAUSTED",
          },
        ],
      }
    );

    assert.equal(summary.status, "PARTIAL");
    assert.equal(summary.tokensFailed, 1);
    assert.equal(summary.walletsFailed, 1);

    assert.deepEqual(
      classifyDiscoverySummary({
        due: true,
        successfulRuns: [],
        partialRuns: [summary],
        failedRuns: [],
      }),
      ["Discovery completate parzialmente: 1."]
    );
  }
);


test(
  "fallimenti Discovery sono warning e non critical failure",
  () => {
    const warnings = classifyDiscoverySummary({
      due: true,
      successfulRuns: [],
      partialRuns: [],
      failedRuns: [
        {
          wallet: "wallet-1",
        },
      ],
    });

    assert.deepEqual(
      warnings,
      ["Discovery non completate: 1."]
    );
  }
);


test(
  "Autopilot parziale degrada ma non fa crashare il cron",
  () => {
    const result = classifyAutopilotSummary({
      processedAccounts: 2,
      successfulRuns: 1,
      failedRuns: 1,
    });

    assert.equal(result.criticalFailures.length, 0);
    assert.equal(result.warnings.length, 1);
  }
);


test(
  "Autopilot totalmente fallito resta un errore critico",
  () => {
    const result = classifyAutopilotSummary({
      processedAccounts: 2,
      successfulRuns: 0,
      failedRuns: 2,
    });

    assert.equal(result.warnings.length, 0);
    assert.equal(result.criticalFailures.length, 1);
  }
);


test(
  "redactSecrets elimina chiavi da URL e messaggi",
  () => {
    const exposed = (
      "https://api.helius.xyz/test?api-key=secret-value "
      + "x-automation-key: another-secret"
    );
    const sanitized = redactSecrets(exposed);

    assert.equal(sanitized.includes("secret-value"), false);
    assert.equal(sanitized.includes("another-secret"), false);
    assert.equal(sanitized.includes("REDACTED"), true);
  }
);


test(
  "main termina DEGRADED con Discovery fallita e Autopilot riuscito",
  async () => {
    const originalFetch = globalThis.fetch;
    const originalLog = console.log;
    const originalWarn = console.warn;
    const originalError = console.error;
    const responses = [
      {
        status: "ready",
        dependencies: { database: "connected" },
      },
      {
        status: "FAILED",
        seed_sync_status: "FAILED",
        tokens_attempted: 0,
        tokens_processed: 0,
        tokens_failed: 0,
        wallets_discovered: 0,
        wallets_analyzed: 0,
        wallets_failed: 0,
        errors: [
          {
            provider: "HELIUS",
            error_code: "HELIUS_RETRY_EXHAUSTED",
          },
        ],
      },
      {
        processed_accounts: 1,
        successful_runs: 1,
        failed_runs: 0,
        results: [{ success: true }],
      },
    ];

    globalThis.fetch = async () => {
      const body = responses.shift();
      return new Response(
        JSON.stringify(body),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        }
      );
    };
    console.log = () => {};
    console.warn = () => {};
    console.error = () => {};

    try {
      const report = await main({
        BACKEND_URL: "https://backend.example",
        AUTOMATION_API_KEY: "automation-secret",
        DISCOVERY_ENABLED: "true",
        AUTOPILOT_ENABLED: "true",
        DISCOVERY_INTERVAL_HOURS: "1",
        SEED_WALLETS: "wallet-1",
        MAX_TOKENS: "1",
        MAX_WALLETS_PER_TOKEN: "1",
        REQUEST_TIMEOUT_MS: "30000",
        SEED_DELAY_MS: "0",
      });

      assert.equal(report.status, "DEGRADED");
      assert.equal(report.discovery.failedRuns, 1);
      assert.equal(report.autopilot.successfulRuns, 1);
      assert.equal(report.criticalFailures.length, 0);
      assert.equal(report.warnings.length, 1);
    } finally {
      globalThis.fetch = originalFetch;
      console.log = originalLog;
      console.warn = originalWarn;
      console.error = originalError;
    }
  }
);
