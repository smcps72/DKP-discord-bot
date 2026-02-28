#!/usr/bin/env python3
"""
Security scan script for the DKP Discord bot.
Runs bandit (static analysis) and pip-audit (dependency vulnerability scan).
"""

import subprocess
import sys
from pathlib import Path

def run_command(cmd, cwd=None):
    """Run a command and return True if it succeeds."""
    try:
        result = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {' '.join(str(part) for part in cmd)}")
        print(e.stdout)
        print(e.stderr)
        return False


def resolve_python_executable(repo_root: Path) -> Path:
    """Resolve a Python executable that exists on this platform.

    Preference order:
    1) ./venv (project default)
    2) ./.venv
    3) currently-running interpreter
    """
    exe_name = "python.exe" if sys.platform.startswith("win") else "python"
    venv_dir_name = "Scripts" if sys.platform.startswith("win") else "bin"

    candidates = [
        repo_root / "venv" / venv_dir_name / exe_name,
        repo_root / ".venv" / venv_dir_name / exe_name,
        Path(sys.executable),
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return Path(sys.executable)

def main():
    print("=== Running Security Scans ===\n")

    repo_root = Path(__file__).resolve().parent
    python_exe = resolve_python_executable(repo_root)

    # 1. Bandit static analysis
    print("1. Running bandit (static analysis)...")
    bandit_cmd = [
        str(python_exe),
        "-m",
        "bandit",
        "-r",
        "discord_bot",
        "-f",
        "json",
        "-o",
        "bandit-report.json",
    ]
    if not run_command(bandit_cmd, cwd=repo_root):
        print("Bandit found issues or failed. See bandit-report.json.")
    else:
        print("Bandit passed.\n")

    # 2. pip-audit for dependency vulnerabilities
    print("2. Running pip-audit (dependency vulnerability scan)...")
    audit_cmd = [
        str(python_exe),
        "-m",
        "pip_audit",
        "--format",
        "json",
        "--output",
        "audit-report.json",
    ]
    if not run_command(audit_cmd, cwd=repo_root):
        print("pip-audit found vulnerabilities or failed. See audit-report.json.")
    else:
        print("pip-audit passed.\n")

    print("=== Security scans complete ===")
    print("Reports: bandit-report.json, audit-report.json")

if __name__ == "__main__":
    sys.exit(main())
