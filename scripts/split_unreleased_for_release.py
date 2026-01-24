import argparse
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path


def _run_git(args: list[str], cwd: Path, timeout: float = 30) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout,
        )
    except Exception as e:
        return 1, str(e)
    return proc.returncode, (proc.stdout or "")


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


def _openai_chat_completion(prompt: str, timeout: float = 45) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    base_url_raw = (os.getenv("OPENAI_BASE_URL") or "").strip()
    base_url = (base_url_raw or "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "o3-mini")
    is_o_series = model.lower().startswith("o")

    payload: dict[str, object] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert release note curator for a Discord bot. "
                    "Your job is to split a draft Unreleased changelog into two parts: shipped vs remaining. "
                    "Only include items as shipped if they are supported by the provided code diff. "
                    "Return STRICT JSON only (no markdown fences) with keys: "
                    "version_md, unreleased_md. "
                    "Both values must be markdown in the same style as the project's 0.1.0-alpha.* changelog files: "
                    "use '##' headings, '-' bullets, short paragraphs, and occasional sub-bullets. "
                    "Do not mention filenames, file paths, branches, worktrees, commit hashes, or git commands."
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


def _parse_strict_json(text: str) -> dict[str, str] | None:
    s = (text or "").strip()
    if not s:
        return None

    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", s)
        s = re.sub(r"\n```\s*$", "", s)
        s = s.strip()

    try:
        obj = json.loads(s)
    except Exception:
        return None

    if not isinstance(obj, dict):
        return None

    version_md = obj.get("version_md")
    unreleased_md = obj.get("unreleased_md")
    if not isinstance(version_md, str) or not isinstance(unreleased_md, str):
        return None

    return {"version_md": version_md.strip(), "unreleased_md": unreleased_md.strip()}


def _find_tag_for_version(repo_root: Path, version: str) -> str | None:
    for cand in (f"v{version}", version):
        code, _out = _run_git(["rev-parse", "-q", "--verify", f"refs/tags/{cand}"], cwd=repo_root)
        if code == 0:
            return cand
    return None


def _write_text(path: Path, content: str) -> bool:
    try:
        existing = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        existing = ""

    out = (content or "").strip() + "\n"
    if out == existing:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--previous-version", required=True)
    parser.add_argument("--head-ref", default="origin/master")
    parser.add_argument("--base-ref", default=None)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[1]

    unreleased_path = repo_root / "changelog" / "Unreleased.md"
    if not unreleased_path.exists():
        return 0

    try:
        unreleased_md = unreleased_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return 0

    if not unreleased_md or unreleased_md.strip() == "- No unreleased notes yet.":
        return 0

    base_ref = args.base_ref
    if not base_ref:
        base_ref = _find_tag_for_version(repo_root, args.previous_version)

    if not base_ref:
        return 0

    code, diff_raw = _run_git(["diff", "--no-color", "-U3", f"{base_ref}..{args.head_ref}"], cwd=repo_root)
    if code not in (0, 1):
        return 0

    diff_for_ai = _sanitize_diff_for_ai(diff_raw)
    if not diff_for_ai:
        return 0

    prompt = (
        "You will be given (1) the current Unreleased changelog draft and (2) the code changes being shipped.\n\n"
        "Task:\n"
        "- Produce the versioned changelog markdown for ONLY the shipped items.\n"
        "- Produce an updated Unreleased markdown that keeps ONLY the remaining (unshipped) items.\n"
        "- Preserve the original wording when possible; only rewrite when needed for clarity.\n"
        "- Remove empty headings after splitting.\n\n"
        "Unreleased draft:\n"
        f"{unreleased_md}\n\n"
        "Shipped code diff:\n"
        f"{diff_for_ai}\n"
    )

    ai_text = _openai_chat_completion(prompt)
    if not ai_text:
        return 1 if args.strict else 0

    parsed = _parse_strict_json(ai_text)
    if not parsed:
        return 1 if args.strict else 0

    version_md = parsed["version_md"].strip()
    remaining_md = parsed["unreleased_md"].strip()

    if not version_md:
        return 1 if args.strict else 0

    if not remaining_md:
        remaining_md = "- No unreleased notes yet."

    version_path = repo_root / "changelog" / f"{args.release_version}.md"

    changed = False
    changed |= _write_text(version_path, version_md)
    changed |= _write_text(unreleased_path, remaining_md)

    return 0 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
