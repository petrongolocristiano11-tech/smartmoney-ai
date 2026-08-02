from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Anchor frontend mancante: {label}")
    return text.replace(old, new, 1)


def patch_api(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if "getGen4ForwardFeedStatus" in text:
        return False
    text = text.rstrip() + '''\n\nexport function getGen4ForwardFeedStatus(accessKey) {\n  return api.get(\n    `${GEN4_FORWARD_BASE}/feed/status`,\n    getAutomationConfig(accessKey)\n  );\n}\n\nexport function runGen4ForwardFeedPoll(\n  accessKey,\n  campaignId,\n  observedAt = null\n) {\n  return api.post(\n    `${GEN4_FORWARD_BASE}/feed/poll`,\n    {\n      campaign_id: campaignId,\n      confirmation: "RUN_GEN4_FORWARD_FEED_POLL",\n      observed_at: observedAt,\n    },\n    getAutomationConfig(accessKey)\n  );\n}\n'''
    path.write_text(text, encoding="utf-8")
    return True


def patch_page(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if "Gen4ForwardFeedPanel" in text:
        return False
    text = replace_once(
        text,
        'import Gen4ForwardLaneCard from "../components/gen4Forward/Gen4ForwardLaneCard";',
        'import Gen4ForwardLaneCard from "../components/gen4Forward/Gen4ForwardLaneCard";\nimport Gen4ForwardFeedPanel from "../components/gen4Forward/Gen4ForwardFeedPanel";',
        "feed panel import",
    )
    text = replace_once(
        text,
        '''  getGen4ForwardCampaign,\n  getGen4ForwardStatus,\n  runGen4ForwardCycle,''',
        '''  getGen4ForwardCampaign,\n  getGen4ForwardFeedStatus,\n  getGen4ForwardStatus,\n  runGen4ForwardCycle,\n  runGen4ForwardFeedPoll,''',
        "feed api imports",
    )
    text = replace_once(
        text,
        "  const [campaign, setCampaign] = useState(null);",
        "  const [campaign, setCampaign] = useState(null);\n  const [feed, setFeed] = useState(null);",
        "feed state",
    )
    text = replace_once(
        text,
        "  const [cycleBusy, setCycleBusy] = useState(false);",
        "  const [cycleBusy, setCycleBusy] = useState(false);\n  const [feedBusy, setFeedBusy] = useState(false);",
        "feed busy state",
    )
    text = replace_once(
        text,
        "    setCampaign(null);\n    setError(reason);",
        "    setCampaign(null);\n    setFeed(null);\n    setError(reason);",
        "clear feed state",
    )
    text = replace_once(
        text,
        "        const nextStatus = statusResponse.data;\n        setStatus(nextStatus);",
        "        const nextStatus = statusResponse.data;\n        setStatus(nextStatus);\n\n        const feedResponse = await getGen4ForwardFeedStatus(key);\n        setFeed(feedResponse.data);",
        "load feed status",
    )
    text = replace_once(
        text,
        "  async function runCycle() {\n",
        '''  async function runFeedPoll() {\n    if (!campaign?.campaign_id || campaign.status !== "ACTIVE") {\n      return;\n    }\n\n    setFeedBusy(true);\n    setError("");\n    setMessage("");\n\n    try {\n      const response = await runGen4ForwardFeedPoll(\n        accessKey,\n        campaign.campaign_id\n      );\n      const run = response.data?.run;\n      setMessage(\n        run\n          ? `Feed ${run.status}: ${run.helius_requests ?? 0} richieste Helius, ${run.trades_imported ?? 0} trade importati, ${run.new_decisions ?? 0} nuove decisioni.`\n          : "Poll feed completato."\n      );\n      await loadDashboard(false);\n    } catch (requestError) {\n      handleRequestError(requestError);\n    } finally {\n      setFeedBusy(false);\n    }\n  }\n\n  async function runCycle() {\n''',
        "manual feed poll handler",
    )
    text = replace_once(
        text,
        '''              <button\n                type="button"\n                onClick={runCycle}\n''',
        '''              <button\n                type="button"\n                onClick={runFeedPoll}\n                disabled={\n                  feedBusy ||\n                  campaign?.status !== "ACTIVE" ||\n                  feed?.runtime_enabled !== true\n                }\n                title="Acquisisce i nuovi swap dei wallet congelati e avvia subito un ciclo shadow."\n                className="rounded-xl border border-cyan-700 bg-cyan-950/50 px-4 py-2 text-sm font-black text-cyan-300 transition hover:bg-cyan-900/60 disabled:cursor-not-allowed disabled:opacity-50"\n              >\n                {feedBusy ? "Acquisizione..." : "Acquisisci ora"}\n              </button>\n              <button\n                type="button"\n                onClick={runCycle}\n''',
        "feed button",
    )
    text = replace_once(
        text,
        '''            <span>Modalità: manual cycle only</span>\n            <span>Nessun Helius / paper / LIVE</span>''',
        '''            <span>Feed automatico: {feed?.worker_running ? "RUNNING" : "STOPPED"}</span>\n            <span>Polling: {feed?.state?.interval_seconds ?? 0}s</span>\n            <span>Helius controllato / nessun paper / LIVE</span>''',
        "header feed status",
    )
    text = replace_once(
        text,
        '''          <>\n            <section className="grid gap-4''',
        '''          <>\n            <Gen4ForwardFeedPanel feed={feed} />\n\n            <section className="grid gap-4''',
        "feed panel placement",
    )
    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    api_path = root / "frontend/src/services/gen4ForwardApi.js"
    page_path = root / "frontend/src/pages/Gen4Forward.jsx"
    for path in (api_path, page_path):
        if not path.exists():
            raise RuntimeError(f"File frontend M54-M55 mancante: {path}")
    if args.check_only:
        # Validate the real M54-M55 files by applying the semantic patch to
        # temporary copies. This avoids brittle title/hash checks and proves
        # every required anchor before any project backup or modification.
        with tempfile.TemporaryDirectory(prefix="m56-m57-frontend-check-") as temp_dir:
            temp_root = Path(temp_dir)
            api_copy = temp_root / "gen4ForwardApi.js"
            page_copy = temp_root / "Gen4Forward.jsx"
            shutil.copy2(api_path, api_copy)
            shutil.copy2(page_path, page_copy)

            api_changed = patch_api(api_copy)
            page_changed = patch_page(page_copy)

            patched_api = api_copy.read_text(encoding="utf-8")
            patched_page = page_copy.read_text(encoding="utf-8")
            required_api_markers = (
                'const GEN4_FORWARD_BASE = "/integrity/parser-gen4-forward";',
                "getGen4ForwardStatus",
                "runGen4ForwardCycle",
                "getGen4ForwardFeedStatus",
                "runGen4ForwardFeedPoll",
                "RUN_GEN4_FORWARD_FEED_POLL",
            )
            required_page_markers = (
                "function Gen4Forward()",
                "Gen 4 Strict Forward",
                "Gen4ForwardFeedPanel",
                "runGen4ForwardFeedPoll",
                "Acquisisci ora",
            )
            missing_api = [marker for marker in required_api_markers if marker not in patched_api]
            missing_page = [marker for marker in required_page_markers if marker not in patched_page]
            if missing_api or missing_page:
                raise RuntimeError(
                    "Contratto frontend M54-M57 incompleto dopo dry-run: "
                    f"api={missing_api} page={missing_page}"
                )

        print("M56_M57_FRONTEND_PATCH_CHECK=OK")
        print(
            "DRY_RUN_CHANGES="
            + ",".join(
                name
                for name, changed in (("api", api_changed), ("page", page_changed))
                if changed
            )
            if api_changed or page_changed
            else "DRY_RUN_CHANGES=none_already_patched"
        )
        return 0
    changes = []
    if patch_api(api_path):
        changes.append("api")
    if patch_page(page_path):
        changes.append("page")
    print("M56_M57_FRONTEND_PATCH=OK")
    print("CHANGES=" + (",".join(changes) if changes else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
