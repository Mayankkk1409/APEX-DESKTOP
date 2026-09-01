#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$ROOT" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
skip_dirs = {".git", "node_modules", ".venv", "dist", "test-results", "playwright-report", "__pycache__", ".mypy_cache"}
skip_files = {"secret-scan.sh", "README.md"}
# docs may mention rotation; .env.example has empty names only
fail = 0
burned = "PKMHH4RBSYR5FPIIWJRU7FHELJ"

for path in root.rglob("*"):
    if not path.is_file():
        continue
    if any(p in skip_dirs for p in path.parts):
        continue
    if path.name in skip_files or path.name.startswith(".env"):
        continue
    if path.suffix.lower() in {".png", ".pdf", ".woff", ".woff2"}:
        continue
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    rel = path.relative_to(root).as_posix()
    if burned in text and not rel.startswith("docs/"):
        print(f"SECRET SCAN: burned key ID in {rel}")
        fail = 1
    for line in text.splitlines():
        if line.startswith("ALPACA_API_SECRET_KEY=") and line.split("=", 1)[1].strip():
            print(f"SECRET SCAN: secret assigned in {rel}")
            fail = 1
        if line.startswith("ALPACA_API_KEY_ID=PK"):
            print(f"SECRET SCAN: key ID assigned in {rel}")
            fail = 1

if fail:
    print("Secret scan failed")
    sys.exit(1)
print("Secret scan passed")
PY
