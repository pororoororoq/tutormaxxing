"""Tests for install.py (runs against a throwaway CLAUDE_CONFIG_DIR, never the real ~/.claude)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / ".claude" / "skills" / "tutor"


def can_symlink():
    with tempfile.TemporaryDirectory() as d:
        try:
            os.symlink(d, Path(d) / "link", target_is_directory=True)
            return True
        except (OSError, NotImplementedError):
            return False


class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name)
        self.dest = self.cfg / "skills" / "tutor"
        self.settings = self.cfg / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self, *args, ok=True):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.cfg))
        p = subprocess.run([sys.executable, str(REPO / "install.py"), *args], capture_output=True, text=True,
                           env=env)
        if ok:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def allow(self):
        return json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]["allow"]

    @unittest.skipUnless(can_symlink(), "symlinks not available")
    def test_link_install_adds_rules_once_and_uninstalls_cleanly(self):
        self.settings.write_text(json.dumps({"model": "sonnet", "permissions": {"allow": ["Bash(ls *)"]}}),
                                 encoding="utf-8")
        self.run_install()
        self.assertTrue(self.dest.is_symlink())
        self.assertEqual(self.dest.resolve(), SRC.resolve())
        allow = self.allow()
        for rule in ("Skill(tutor)", "Edit(courses/**)", f'Bash(python3 "{self.dest}/scripts/*)'):
            self.assertIn(rule, allow)
        self.assertNotIn("Bash(python3 *)", allow)
        self.run_install()                                   # idempotent
        self.assertEqual(self.allow(), allow)
        self.run_install("--uninstall")
        self.assertFalse(self.dest.exists() or self.dest.is_symlink())
        data = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(data["permissions"]["allow"], ["Bash(ls *)"])   # the user's own rule survives
        self.assertEqual(data["model"], "sonnet")

    def test_copy_install_skips_caches(self):
        self.run_install("--copy")
        self.assertTrue(self.dest.is_dir() and not self.dest.is_symlink())
        self.assertTrue((self.dest / "SKILL.md").is_file())
        self.assertFalse(list(self.dest.rglob("__pycache__")))
        self.run_install("--copy")                           # replacing its own older copy is fine
        self.run_install("--uninstall")
        self.assertFalse(self.dest.exists())

    def test_allow_python_adds_the_broad_rule(self):
        self.run_install("--copy", "--allow-python")
        self.assertIn("Bash(python3 *)", self.allow())

    def test_refuses_to_replace_someone_elses_skill_without_force(self):
        self.dest.mkdir(parents=True)
        (self.dest / "SKILL.md").write_text("---\nname: tutor\ndescription: another one\n---\n", encoding="utf-8")
        p = self.run_install("--copy", ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--force", p.stderr)
        self.run_install("--copy", "--force")
        self.assertTrue((self.dest / "scripts" / "tutor_state.py").is_file())
        backups = list((self.cfg / "skill-backups").iterdir())
        self.assertEqual(len(backups), 1)                    # kept, outside skills/ so it isn't loaded

    def test_invalid_settings_are_left_alone(self):
        self.settings.write_text("{not json", encoding="utf-8")
        p = self.run_install("--copy", ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.settings.read_text(encoding="utf-8"), "{not json")

    def test_no_permissions_flag(self):
        self.run_install("--copy", "--no-permissions")
        self.assertFalse(self.settings.exists())


if __name__ == "__main__":
    unittest.main()
