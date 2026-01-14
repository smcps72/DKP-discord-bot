import os


def _read_repo_version() -> str:
    try:
        version_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
        with open(version_path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if "#" in raw:
            raw = raw.split("#", 1)[0].strip()
        return raw or "0.1.0-alpha.0"
    except OSError:
        return "0.1.0-alpha.0"


__version__ = os.getenv("DKP_BOT_VERSION") or _read_repo_version()
