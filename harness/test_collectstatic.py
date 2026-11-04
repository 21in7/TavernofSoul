"""Exercise the real Makefile using only a disposable, fake interpreter."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class CollectstaticMakeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="collectstatic make ")
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        source = Path(__file__).resolve().parents[1] / "Makefile"
        shutil.copyfile(source, self.repo / "Makefile")
        self.app = self.repo / "TavernofSoul"
        interpreter = self.app / "itos" / "3.8" / "bin" / "python"
        interpreter.parent.mkdir(parents=True)
        interpreter.write_text(
            '#!/bin/sh\n'
            '{\n'
            '    pwd -P\n'
            '    printf "%s\\n" "$#" "$@"\n'
            '} >> "$COLLECTSTATIC_LOG"\n'
            'exit "${COLLECTSTATIC_EXIT_CODE:-0}"\n',
            encoding="utf-8",
        )
        interpreter.chmod(0o755)
        self.log = self.repo / "calls.log"
        # Exclude inherited make flags and interpreter/startup settings.
        self.env = {
            "PATH": os.defpath,
            "LC_ALL": "C",
            "COLLECTSTATIC_LOG": str(self.log),
        }

    def make(self, *arguments):
        return subprocess.run(
            ["make", "--no-print-directory", *arguments],
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def calls(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def expected_call(self):
        return [str(self.app.resolve()), "3", "manage_itos.py", "collectstatic", "--noinput"]

    def test_explicit_calls_use_fixed_interpreter_and_are_phony(self):
        # An existing target file must not suppress either explicit invocation.
        (self.repo / "collectstatic-itos").touch()
        for invocation in range(1, 3):
            with self.subTest(invocation=invocation):
                result = self.make("collectstatic-itos", "PYTHON=/unused/interpreter")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.calls(), self.expected_call() * invocation)
                self.assertNotIn("--clear", self.calls())

    def test_child_failure_makes_make_fail(self):
        self.env["COLLECTSTATIC_EXIT_CODE"] = "23"
        result = self.make("collectstatic-itos")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls(), self.expected_call())
        self.assertIn("Error 23", result.stderr)

    def test_default_help_and_check_do_not_collect(self):
        default = self.make()
        help_result = self.make("help")
        for result in (default, help_result):
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("collectstatic-itos", result.stdout)
            self.assertIn("manual production deployment only", result.stdout)
        self.assertEqual(default.stdout, help_result.stdout)
        self.assertEqual(self.calls(), [])

        # Dry-run check: inspect make's control flow without running the harness.
        check = self.make("-n", "check")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertIn("-m harness check", check.stdout)
        self.assertNotIn("collectstatic", check.stdout)
        self.assertNotIn("manage_itos.py", check.stdout)
        self.assertEqual(self.calls(), [])
