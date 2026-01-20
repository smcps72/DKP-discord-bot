import argparse
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path


SECTION_HEADER = "## Local worktree changes (not yet committed)"


def _load_env_from_file(path: Path) -> None:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        key = k.strip()
        val = v.strip().strip('"').strip("'")
        if not key:
            continue
        os.environ.setdefault(key, val)


def _load_env() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    paths = [
        repo_root / "secrets" / ".env.local",
        repo_root / ".env.local",
        repo_root / ".env",
    ]

    try:
        from dotenv import load_dotenv  # type: ignore

        for p in paths:
            if p.exists():
                load_dotenv(dotenv_path=p, override=False)
        return
    except Exception:
        for p in paths:
            if p.exists():
                _load_env_from_file(p)


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    m = re.match(r"^(\d+)", raw)
    if not m:
        return default
    try:
        return int(m.group(1))
    except ValueError:
        return default


def _run_git(args: list[str], cwd: Path, timeout: float = 5) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=timeout,
        )
    except Exception:
        return None

    if proc.returncode not in (0, 1):
        return None

    return proc.stdout


def _get_openai_config() -> tuple[str, str, str] | None:
    _load_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return api_key, base_url, model


def _sanitize_diff_for_ai(raw: str, max_chars: int = 80_000) -> str:
    drop_prefixes = (
        "diff --git ",
        "index ",
        "--- ",
        "+++ ",
        "new file mode ",
        "deleted file mode ",
        "rename from ",
        "rename to ",
        "similarity index ",
        "dissimilarity index ",
    )
    lines = [ln for ln in raw.splitlines() if not ln.startswith(drop_prefixes)]
    out = "\n".join(lines).strip()
    if len(out) <= max_chars:
        return out
    head = max_chars // 2
    tail = max_chars - head
    return (out[:head].rstrip() + "\n...\n" + out[-tail:].lstrip()).strip()


def _openai_chat_completion(prompt: str, timeout: float = 20) -> str | None:
    _load_env()
    cfg = _get_openai_config()
    if cfg is None:
        return None
    api_key, base_url, model = cfg

    is_o_series = model.lower().startswith("o")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert release note writer for a Discord bot. "
                    "Write in the same style as the project's 0.1.0-alpha.* changelog files: "
                    "use '##' headings, '-' bullets, short paragraphs, and occasional sub-bullets. "
                    "Do not mention filenames, file paths, branches, worktrees, commit hashes, or git commands. "
                    "Prefer describing user-visible behavior, permissions/visibility changes, UX changes, "
                    "raid/voice/timed DKP behavior, and QA/testing work."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }

    if is_o_series:
        payload["max_completion_tokens"] = _env_int("OPENAI_MAX_OUTPUT_TOKENS", 2000)
    else:
        payload["temperature"] = 0.2
        payload["max_tokens"] = _env_int("OPENAI_MAX_TOKENS", 1200)

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=f"{base_url}/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    try:
        obj = json.loads(raw)
        choices = obj.get("choices") or []
        msg = (choices[0].get("message") if choices else None) or {}
        content = (msg.get("content") or "").strip()
        return content or None
    except Exception:
        return None


def _feature_hint(area: str) -> str:
    hints = {
        "UI": "Interaction and panel UX work",
        "Raids": "Raid management, signup flows, and roster/voice tooling",
        "Bot": "Command behavior and bot logic updates",
        "Tests": "Unit/integration regression coverage",
        "E2E": "End-to-end/staging smoke coverage",
        "Docs": "User/admin documentation updates",
        "CI": "CI/staging automation improvements",
        "Dev tooling": "Local developer tooling and scripts",
        "Changelog": "Release notes and changelog maintenance",
        "Licensing": "License server / entitlement checks",
        "Dependencies": "Dependency and packaging updates",
        "Other": "Miscellaneous internal updates",
    }
    return hints.get(area, hints["Other"])


def _iter_worktrees(repo_root: Path) -> list[dict[str, str]]:
    raw = _run_git(["worktree", "list", "--porcelain"], cwd=repo_root)
    if not raw:
        return []

    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in raw.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(dict(current))
            current = {"path": line.split(" ", 1)[1].strip()}
            continue
        if line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1].strip()
            continue
        if line.startswith("HEAD "):
            current["head"] = line.split(" ", 1)[1].strip()
            continue

    if current:
        worktrees.append(dict(current))

    return worktrees


def _extract_path_from_porcelain_line(line: str) -> str:
    if len(line) <= 3:
        return ""
    path = line[3:].strip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1].strip()
    if path.startswith('"') and path.endswith('"') and len(path) >= 2:
        path = path[1:-1]
    return path


def _categorize_path(path: str) -> str:
    p = path.replace("\\", "/")
    if p == "CHANGELOG.md" or p.startswith("changelog/"):
        return "Changelog"
    if p.startswith("discord_bot/ui/"):
        return "UI"
    if p.startswith("discord_bot/cogs/raid") or p.startswith("discord_bot/cogs/raid_"):
        return "Raids"
    if p.startswith("discord_bot/cogs/"):
        return "Bot"
    if p.startswith("discord_bot/"):
        return "Bot"
    if p.startswith("tests/"):
        return "Tests"
    if p.startswith("js-e2e/"):
        return "E2E"
    if p.startswith("Documentation/") or p == "mkdocs.yml":
        return "Docs"
    if p.startswith(".github/"):
        return "CI"
    if p.startswith("scripts/"):
        return "Dev tooling"
    if p.startswith("licensing_server/"):
        return "Licensing"
    if p.startswith("requirements"):
        return "Dependencies"
    return "Other"


def _untracked_files(repo_root: Path, cwd: Path) -> list[str]:
    raw = _run_git(["ls-files", "--others", "--exclude-standard"], cwd=cwd)
    if raw is None:
        return []
    paths = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    return paths


def _worktree_uncommitted_diff_text(repo_root: Path, cwd: Path) -> str:
    parts: list[str] = []
    staged = _run_git(["diff", "--cached", "--no-color", "-U3"], cwd=cwd, timeout=20)
    if staged:
        parts.append(staged)
    unstaged = _run_git(["diff", "--no-color", "-U3"], cwd=cwd, timeout=20)
    if unstaged:
        parts.append(unstaged)

    for rel in _untracked_files(repo_root, cwd)[:20]:
        abs_path = (cwd / rel)
        try:
            if abs_path.is_file() and abs_path.stat().st_size > 80_000:
                continue
        except OSError:
            continue

        raw = _run_git(["diff", "--no-color", "-U3", "--no-index", "/dev/null", rel], cwd=cwd, timeout=20)
        if raw:
            parts.append(raw)

    return "\n\n".join([p.strip() for p in parts if p and p.strip()]).strip()


def _gather_worktree_changes(repo_root: Path) -> tuple[dict[str, int], list[str], str]:
    worktrees = _iter_worktrees(repo_root)
    if not worktrees:
        return {}, [], ""

    combined_counts: dict[str, int] = {}
    diff_parts: list[str] = []

    for wt in worktrees:
        path_str = wt.get("path")
        if not path_str:
            continue

        path = Path(path_str)
        status_raw = _run_git(["status", "--porcelain=v1"], cwd=path)
        if status_raw is None:
            continue

        status_lines = [ln.rstrip() for ln in status_raw.splitlines() if ln.strip()]
        if not status_lines:
            continue

        counts: dict[str, int] = {}
        for ln in status_lines:
            fp = _extract_path_from_porcelain_line(ln)
            if not fp:
                continue
            cat = _categorize_path(fp)
            counts[cat] = counts.get(cat, 0) + 1

        if not counts:
            continue

        for k, v in counts.items():
            combined_counts[k] = combined_counts.get(k, 0) + v

        diff_text = _worktree_uncommitted_diff_text(repo_root, path)
        if diff_text:
            diff_parts.append(diff_text)

    if not combined_counts:
        return {}, [], ""

    combined_categories = [
        cat
        for cat, _n in sorted(combined_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    diff_for_ai = _sanitize_diff_for_ai("\n\n".join(diff_parts)) if diff_parts else ""
    return combined_counts, combined_categories, diff_for_ai


def _render_worktree_status(repo_root: Path) -> str:
    if not (repo_root / ".git").exists():
        return ""

    combined_counts, combined_categories, _diff_for_ai = _gather_worktree_changes(repo_root)
    if not combined_counts:
        return ""

    lines: list[str] = []
    for cat in combined_categories:
        n = combined_counts.get(cat, 0)
        if not n:
            continue
        lines.append(f"### {cat}: {_feature_hint(cat)}")
        lines.append("")
        lines.append(f"- {n} file(s) changed")
        lines.append("")

    summary = "\n".join(lines).rstrip()
    return "\n".join([SECTION_HEADER, "", summary]).rstrip() + "\n"


def _render_unreleased_notes(repo_root: Path, base_notes: str) -> str | None:
    if not (repo_root / ".git").exists():
        return None

    _counts, _cats, diff_for_ai = _gather_worktree_changes(repo_root)
    if not diff_for_ai:
        return None
    if _get_openai_config() is None:
        return None

    task_list = (base_notes or "").strip()
    if not task_list:
        task_list = "No unreleased notes yet."

    prompt = (
        "Write the Unreleased changelog entry in the same style as 0.1.0-alpha.* files. "
        "Use '##' headings, '-' bullets, short paragraphs, and sub-bullets when helpful. "
        "Do not mention filenames, file paths, branches, worktrees, commit hashes, or git commands. "
        "Focus on user-visible behavior and raid/DKP/permission details. "
        "If something is mentioned in the task list but not clearly implemented yet, mark it as 'In progress' or 'Needs testing'.\n\n"
        "Task list / requirements (use as required topics):\n"
        f"{task_list}\n\n"
        "Uncommitted changes (source of truth for what is implemented):\n"
        f"{diff_for_ai}"
    )
    return _openai_chat_completion(prompt)


def _strip_existing_generated_section(raw: str) -> str:
    lines = raw.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == SECTION_HEADER:
            return "\n".join(lines[:i]).rstrip() + "\n"
    return raw.rstrip() + "\n"


def _update_unreleased_file(unreleased_path: Path, generated: str, new_base: str | None = None) -> bool:
    try:
        existing = unreleased_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    base = _strip_existing_generated_section(existing)

    if new_base is not None and new_base.strip():
        base = new_base.rstrip() + "\n"

    if generated:
        out = base.rstrip() + "\n\n" + generated
    else:
        out = base

    if out == existing:
        return False

    try:
        unreleased_path.write_text(out, encoding="utf-8")
    except OSError:
        return False

    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--all-worktrees",
        action="store_true",
        help="Update changelog/Unreleased.md in every worktree (default).",
    )
    parser.add_argument(
        "--current-only",
        action="store_true",
        help="Only update changelog/Unreleased.md in the current worktree.",
    )
    args = parser.parse_args()

    _load_env()

    repo_root = Path(__file__).resolve().parents[1]
    generated = ""

    worktree_paths: list[Path]
    if args.current_only:
        worktree_paths = [repo_root]
    else:
        worktree_paths = [Path(wt["path"]) for wt in _iter_worktrees(repo_root) if wt.get("path")]
        if not worktree_paths:
            worktree_paths = [repo_root]

    changed_any = False
    for wt_root in worktree_paths:
        unreleased_path = wt_root / "changelog" / "Unreleased.md"
        if not unreleased_path.exists():
            continue

        try:
            existing = unreleased_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            existing = ""
        base_notes = _strip_existing_generated_section(existing).strip()

        new_base = _render_unreleased_notes(wt_root, base_notes)
        if _update_unreleased_file(unreleased_path, generated, new_base=new_base):
            changed_any = True

    return 0 if changed_any else 0


if __name__ == "__main__":
    raise SystemExit(main())
