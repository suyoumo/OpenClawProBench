from __future__ import annotations

import unittest

from harness.live_harness import OpenClawLiveHarness


class LiveHarnessAgentIdTests(unittest.TestCase):
    def test_make_agent_id_matches_openclaw_normalized_model_slug(self) -> None:
        harness = OpenClawLiveHarness()

        agent_id = harness._make_agent_id("codex-cli/gpt-5.4")

        self.assertRegex(agent_id, r"^ocb6-codex-cli-gpt-5-4-[0-9a-f]{12}$")
        self.assertNotIn(".", agent_id)

    def test_make_pool_agent_id_matches_normalized_model_slug(self) -> None:
        harness = OpenClawLiveHarness(openclaw_state_dir="/tmp/openclaw-bench-example")

        agent_id = harness._make_pool_agent_id("codex-cli/gpt-5.4", 1)

        self.assertRegex(agent_id, r"^ocb6-codex-cli-gpt-5-4-pool-[0-9a-f]{8}-1$")
        self.assertNotIn(".", agent_id)


if __name__ == "__main__":
    unittest.main()
