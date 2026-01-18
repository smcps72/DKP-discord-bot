import argparse
import subprocess
from pathlib import Path


SECTION_HEADER = "## Local worktree changes (not yet committed)"


def _run_git(args: list[str], cwd: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return None

    if proc.returncode != 0:
        return None

    return proc.stdout


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


def _render_worktree_status(repo_root: Path) -> str:
    if not (repo_root / ".git").exists():
        return ""

    worktrees = _iter_worktrees(repo_root)
    if not worktrees:
        return ""

    sections: list[str] = []
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

        branch = wt.get("branch") or "(detached)"
        if branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/") :]

        counts: dict[str, int] = {}
        for ln in status_lines:
            fp = _extract_path_from_porcelain_line(ln)
            if not fp:
                continue
            cat = _categorize_path(fp)
            counts[cat] = counts.get(cat, 0) + 1

        if not counts:
            continue

        categories = [cat for cat, _n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

        rendered: list[str] = []
        rendered.append("- Areas touched:")
        for cat in categories:
            rendered.append(f"  - {cat}")

        label = path.name
        sections.append("\n".join([f"### {label} ({branch})", "", *rendered]))

    if not sections:
        return ""

    return "\n".join([SECTION_HEADER, "", *sections]).rstrip() + "\n"


def _strip_existing_generated_section(raw: str) -> str:
    lines = raw.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == SECTION_HEADER:
            return "\n".join(lines[:i]).rstrip() + "\n"
    return raw.rstrip() + "\n"


def _update_unreleased_file(unreleased_path: Path, generated: str) -> bool:
    try:
        existing = unreleased_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    base = _strip_existing_generated_section(existing)

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

    repo_root = Path(__file__).resolve().parents[1]
    generated = _render_worktree_status(repo_root)

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
        if _update_unreleased_file(unreleased_path, generated):
            changed_any = True

    return 0 if changed_any else 0


if __name__ == "__main__":
    raise SystemExit(main())
