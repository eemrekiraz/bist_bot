from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIRECTORIES = {"data", "models", "logs", "reports", "outputs", ".ssh", ".codex", ".agents", ".venv", "node_modules", ".wrangler"}
PRIVATE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".db", ".sql", ".dump", ".bak", ".log", ".zip"}
PATTERNS = {
    "Telegram token": re.compile(r"\b\d{6,16}:[A-Za-z0-9_-]{30,}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "Private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "Windows user directory": re.compile(r"(?i)[a-z]:[\\/]Users[\\/](?!Public\b|example\b)[^\s\\/]+"),
}


def forbidden_path(path: str) -> bool:
    parts = Path(path).parts
    name = Path(path).name
    return (
        any(part in PRIVATE_DIRECTORIES for part in parts)
        or (name.startswith(".env") and name != ".env.example")
        or name.startswith((".dev.vars", "id_rsa", "id_ed25519"))
        or Path(path).suffix.lower() in PRIVATE_SUFFIXES
        or ".sqlite" in name.lower()
    )


def main() -> None:
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT,
    ).decode().split("\0")
    failures = []
    checked = 0
    for relative in sorted(set(paths) - {""}):
        path = ROOT / relative
        if not path.is_file():
            continue
        checked += 1
        if forbidden_path(relative):
            failures.append(f"{relative}: private file type")
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in PATTERNS.items():
            if pattern.search(content):
                failures.append(f"{relative}: {label}")
        if relative == ".env.example":
            for line in content.splitlines():
                key, separator, value = line.partition("=")
                if separator and any(word in key for word in ("TOKEN", "SECRET", "CHAT_ID", "ACCOUNT_ID")) and value.strip():
                    failures.append(f"{relative}: sensitive example field must be empty")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Public-file safety checks passed for {checked} files.")


if __name__ == "__main__":
    main()
