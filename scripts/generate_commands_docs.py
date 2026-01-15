import ast
import os
from dataclasses import dataclass
from typing import Iterable


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COGS_DIR = os.path.join(REPO_ROOT, "discord_bot", "cogs")
BOT_FILE = os.path.join(REPO_ROOT, "discord_bot", "bot.py")
OUTPUT_MD = os.path.join(REPO_ROOT, "Documentation", "commands.md")


@dataclass(frozen=True)
class CommandDoc:
    kind: str
    name: str
    description: str
    source: str


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _iter_py_files() -> Iterable[str]:
    if os.path.isdir(COGS_DIR):
        for name in sorted(os.listdir(COGS_DIR)):
            if not name.endswith(".py"):
                continue
            yield os.path.join(COGS_DIR, name)
    if os.path.isfile(BOT_FILE):
        yield BOT_FILE


def _decorator_dotted_name(expr: ast.AST) -> str | None:
    parts: list[str] = []
    cur: ast.AST | None = expr
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    else:
        return None
    return ".".join(reversed(parts))


def _const_str(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_from_decorator(call: ast.Call) -> CommandDoc | None:
    fn_name = _decorator_dotted_name(call.func)
    if fn_name is None:
        return None

    kw = {k.arg: k.value for k in call.keywords if k.arg}

    if fn_name == "discord.app_commands.command" or fn_name == "app_commands.command" or fn_name.endswith("app_commands.command"):
        name = _const_str(kw.get("name")) or ""
        desc = _const_str(kw.get("description")) or ""
        if not name:
            return None
        return CommandDoc(kind="Slash", name=name, description=desc, source="")

    if fn_name == "commands.command" or fn_name.endswith("commands.command"):
        name = _const_str(kw.get("name")) or ""
        desc = _const_str(kw.get("help")) or ""
        if not name:
            return None
        return CommandDoc(kind="Prefix", name=name, description=desc, source="")

    if fn_name.endswith("tree.command"):
        name = _const_str(kw.get("name")) or ""
        desc = _const_str(kw.get("description")) or ""
        if not name:
            return None
        return CommandDoc(kind="Slash", name=name, description=desc, source="")

    return None


def extract_commands_from_file(path: str) -> list[CommandDoc]:
    try:
        tree = ast.parse(_read_text(path), filename=path)
    except SyntaxError:
        return []

    rel = os.path.relpath(path, REPO_ROOT)

    out: list[CommandDoc] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            cmd = _extract_from_decorator(dec)
            if cmd is None:
                continue
            out.append(CommandDoc(kind=cmd.kind, name=cmd.name, description=cmd.description, source=rel))

    # de-dupe by (kind, name)
    seen: set[tuple[str, str]] = set()
    unique: list[CommandDoc] = []
    for c in out:
        key = (c.kind, c.name)
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)

    return unique


def _render_table(cmds: list[CommandDoc]) -> str:
    lines: list[str] = []
    lines.append("| Command | Description | Source |")
    lines.append("| --- | --- | --- |")
    for c in sorted(cmds, key=lambda x: (x.kind, x.name)):
        cmd_name = f"`/{c.name}`" if c.kind == "Slash" else f"`!{c.name}`"
        desc = (c.description or "").replace("\n", " ").strip()
        src = f"`{c.source}`" if c.source else ""
        lines.append(f"| {cmd_name} | {desc} | {src} |")
    return "\n".join(lines)


def main() -> None:
    all_cmds: list[CommandDoc] = []
    for path in _iter_py_files():
        all_cmds.extend(extract_commands_from_file(path))

    slash = [c for c in all_cmds if c.kind == "Slash"]
    prefix = [c for c in all_cmds if c.kind == "Prefix"]

    md_lines: list[str] = []
    md_lines.append("# Commands")
    md_lines.append("")
    md_lines.append("This page is generated from the current bot code.")
    md_lines.append("")
    md_lines.append("To regenerate it locally:")
    md_lines.append("")
    md_lines.append("```bash")
    md_lines.append("python3 scripts/generate_commands_docs.py")
    md_lines.append("```")

    if slash:
        md_lines.append("")
        md_lines.append("## Slash commands")
        md_lines.append("")
        md_lines.append(_render_table(slash))

    if prefix:
        md_lines.append("")
        md_lines.append("## Prefix commands")
        md_lines.append("")
        md_lines.append(_render_table(prefix))

    os.makedirs(os.path.dirname(OUTPUT_MD), exist_ok=True)
    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines).rstrip() + "\n")


if __name__ == "__main__":
    main()
