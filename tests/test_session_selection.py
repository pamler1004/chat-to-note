import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract_transcript.py"


def claude_transcript(topic):
    return json.dumps({"type": "user", "message": {"role": "user", "content": topic}}) + "\n"


def codex_transcript(topic):
    return json.dumps({"type": "response_item", "payload": {
        "type": "message", "role": "user", "content": [{"text": topic}]
    }}) + "\n"


class SessionSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.claude = self.home / ".claude/projects/project/session-a.jsonl"
        self.codex_id = "12345678-abcd-1234-abcd-1234567890ab"
        self.codex = self.home / f".codex/sessions/2026/10/rollout-2026-10-27T11-30-15-{self.codex_id}.jsonl"
        self.claude.parent.mkdir(parents=True)
        self.codex.parent.mkdir(parents=True)
        self.claude.write_text(claude_transcript("CLAUDE_TOPIC"), encoding="utf-8")
        self.codex.write_text(codex_transcript("CODEX_TOPIC"), encoding="utf-8")
        self.env = os.environ.copy()
        self.env["HOME"] = str(self.home)
        for key in ("CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID", "CODEX_ROLLOUT_ID"):
            self.env.pop(key, None)

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=self.env,
                              text=True, capture_output=True, check=False)

    def test_ambiguous_current_session_does_not_fall_back_to_mtime(self):
        # Make one candidate much newer: it must still not be treated as current.
        os.utime(self.codex, (2_000_000_000, 2_000_000_000))
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertIn("无法核验当前会话身份", result.stderr)
        self.assertNotIn("PATH:", result.stderr)

    def test_explicit_path_and_exact_session_id_select_expected_transcript(self):
        by_path = self.run_script("--path", str(self.codex))
        self.assertEqual(by_path.returncode, 0, by_path.stderr)
        self.assertIn("CODEX_TOPIC", Path(by_path.stdout.strip()).read_text(encoding="utf-8"))

        by_id = self.run_script("--session-id", "session-a", "--tool", "claude")
        self.assertEqual(by_id.returncode, 0, by_id.stderr)
        self.assertIn("CLAUDE_TOPIC", Path(by_id.stdout.strip()).read_text(encoding="utf-8"))

        by_codex_uuid = self.run_script("--session-id", self.codex_id, "--tool", "codex")
        self.assertEqual(by_codex_uuid.returncode, 0, by_codex_uuid.stderr)
        self.assertIn("CODEX_TOPIC", Path(by_codex_uuid.stdout.strip()).read_text(encoding="utf-8"))

    def test_duplicate_session_id_requires_explicit_path(self):
        duplicate = self.home / f".codex/archived_sessions/rollout-2026-10-27T09-00-00-{self.codex_id}.jsonl"
        duplicate.parent.mkdir(parents=True)
        duplicate.write_text(codex_transcript("DUPLICATE_TOPIC"), encoding="utf-8")
        result = self.run_script("--session-id", self.codex_id)
        self.assertEqual(result.returncode, 2)
        self.assertIn("匹配 2 个文件", result.stderr)

    def test_duplicate_claude_id_is_not_silently_selected(self):
        duplicate = self.home / ".claude/projects/another-project/session-a.jsonl"
        duplicate.parent.mkdir(parents=True)
        duplicate.write_text(claude_transcript("OTHER_CLAUDE_TOPIC"), encoding="utf-8")
        self.env["CLAUDE_CODE_SESSION_ID"] = "session-a"
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertIn("无法核验当前会话身份", result.stderr)
        by_id = self.run_script("--session-id", "session-a", "--tool", "claude")
        self.assertEqual(by_id.returncode, 2)
        self.assertIn("匹配 2 个文件", by_id.stderr)

    def test_partial_session_id_does_not_match(self):
        result = self.run_script("--session-id", self.codex_id[:8], "--tool", "codex")
        self.assertEqual(result.returncode, 2)
        self.assertIn("匹配 0 个文件", result.stderr)

    def test_short_codex_suffix_does_not_match(self):
        result = self.run_script("--session-id", "12345678", "--tool", "codex")
        self.assertEqual(result.returncode, 2)
        self.assertIn("匹配 0 个文件", result.stderr)

    def test_claude_id_is_literal_not_a_glob_pattern(self):
        result = self.run_script("--session-id", "*", "--tool", "claude")
        self.assertEqual(result.returncode, 2)
        self.assertIn("匹配 0 个文件", result.stderr)


if __name__ == "__main__":
    unittest.main()
