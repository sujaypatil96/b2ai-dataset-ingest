#!/usr/bin/env python3
"""Run the guard against a TSV of expected/command cases. Prints a pass/fail table."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
GUARD = os.path.join(HERE, "guard_data_dir.py")
env = dict(os.environ, CLAUDE_PROJECT_DIR=ROOT)

failures = 0
with open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "test_cases.tsv")) as fh:
    for line in fh:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        expected, command = line.split("\t", 1)
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
        out = subprocess.run([GUARD], input=payload, capture_output=True,
                             text=True, env=env).stdout.strip()
        actual = "block" if out else "allow"
        ok = actual == expected
        failures += not ok
        mark = "ok  " if ok else "FAIL"
        print(f"  {mark} {actual:5s} (want {expected:5s})  {command[:72]}")

print(f"\n{failures} failure(s)")
sys.exit(1 if failures else 0)
