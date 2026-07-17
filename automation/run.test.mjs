import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAutopilotUrl,
  isDiscoveryDue,
  parseSeedWallets,
  readBoolean,
  readInteger,
  summarizeAutopilotResult,
} from "./run.mjs";


test(
  "parseSeedWallets normalizza e rimuove duplicati",
  () => {
    assert.deepEqual(
      parseSeedWallets(
        " A, B, A, ,C "
      ),
      [
        "A",
        "B",
        "C",
      ]
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
        {
          FLAG: "true",
        }
      ),
      true
    );

    assert.equal(
      readBoolean(
        "FLAG",
        true,
        {
          FLAG: "off",
        }
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
        {
          LIMIT: "99",
        }
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
        new Date(
          "2026-07-17T12:00:00Z"
        ),
        6
      ),
      true
    );

    assert.equal(
      isDiscoveryDue(
        new Date(
          "2026-07-17T13:00:00Z"
        ),
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
        results: [
          {
            success: true,
          },
        ],
      }),
      {
        processedAccounts: 2,
        successfulRuns: 1,
        failedRuns: 1,
        results: [
          {
            success: true,
          },
        ],
      }
    );
  }
); 