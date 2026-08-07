import { api } from "./api";

const GEN4_FORWARD_BASE = "/integrity/parser-gen4-forward";

function getAutomationConfig(accessKey) {
  return {
    headers: {
      "X-Automation-Key": String(accessKey ?? "").trim(),
    },
  };
}

export function getGen4ForwardStatus(accessKey) {
  return api.get(
    `${GEN4_FORWARD_BASE}/status`,
    getAutomationConfig(accessKey)
  );
}

export function getGen4ForwardCampaign(
  accessKey,
  campaignId,
  {
    includeDecisions = true,
    decisionLimit = 1000,
  } = {}
) {
  return api.get(
    `${GEN4_FORWARD_BASE}/campaigns/${encodeURIComponent(campaignId)}`,
    {
      ...getAutomationConfig(accessKey),
      params: {
        include_decisions: includeDecisions,
        decision_limit: decisionLimit,
      },
    }
  );
}

export function runGen4ForwardCycle(
  accessKey,
  campaignId,
  observedAt = null
) {
  return api.post(
    `${GEN4_FORWARD_BASE}/cycle`,
    {
      campaign_id: campaignId,
      confirmation: "RUN_GEN4_STRICT_FORWARD_CYCLE",
      observed_at: observedAt,
    },
    getAutomationConfig(accessKey)
  );
}

export function getGen4ForwardFeedStatus(accessKey) {
  return api.get(
    `${GEN4_FORWARD_BASE}/feed/status`,
    getAutomationConfig(accessKey)
  );
}

export function runGen4ForwardFeedPoll(
  accessKey,
  campaignId,
  observedAt = null
) {
  return api.post(
    `${GEN4_FORWARD_BASE}/feed/poll`,
    {
      campaign_id: campaignId,
      confirmation: "RUN_GEN4_FORWARD_FEED_POLL",
      observed_at: observedAt,
    },
    getAutomationConfig(accessKey)
  );
}

const GEN4_COPYABILITY_BASE = "/integrity/parser-gen4-copyability";

export function getGen4CopyabilityStatus(
  accessKey,
  recentLimit = 100,
  campaignId = null
) {
  return api.get(
    `${GEN4_COPYABILITY_BASE}/status`,
    {
      ...getAutomationConfig(accessKey),
      params: {
        recent_limit: recentLimit,
        campaign_id: campaignId || undefined,
      },
    }
  );
}

export function startGen4QualifiedCandidate(
  accessKey,
  candidateWallets,
  selectionSnapshot,
  note = null
) {
  return api.post(
    `${GEN4_COPYABILITY_BASE}/start-qualified-candidate`,
    {
      confirmation: "START_GEN4_QUALIFIED_CANDIDATE_COPYABILITY",
      candidate_wallets: candidateWallets,
      selection_snapshot: selectionSnapshot,
      actor_label: "M61_QUALIFIED_CANDIDATE",
      note,
      anchor_at: null,
    },
    getAutomationConfig(accessKey)
  );
}

export function processGen4CopyabilityQueue(accessKey, batchSize = 20) {
  return api.post(
    `${GEN4_COPYABILITY_BASE}/process`,
    {
      confirmation: "PROCESS_GEN4_COPYABILITY_QUEUE",
      batch_size: batchSize,
      observed_at: null,
    },
    getAutomationConfig(accessKey)
  );
}
