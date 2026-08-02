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
