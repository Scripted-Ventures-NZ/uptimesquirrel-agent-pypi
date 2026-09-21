#!/usr/bin/env bash
# Sync the canonical agent source files into this PyPI package and rewrite
# flat imports to package-relative imports. The canonical files live in the
# main UptimeSquirrel monorepo under
#   uptimesquirrel-frontend/public/downloads/agent/
# because the frontend serves them via direct download. This script keeps the
# pip-installable package in lock-step with what the website serves.
#
# Usage:
#   scripts/sync-from-frontend.sh                  # default: ../UptimeSquirrel/uptimesquirrel-frontend/public/downloads/agent
#   scripts/sync-from-frontend.sh /abs/path/to/agent-dir
#
# After running:
#   - uptimesquirrel_agent/{agent,check_executor,task_manager}.py are updated
#   - pyproject.toml version matches latest-linux.txt
#   - Review the diff, commit, then tag vX.Y.Z and push to trigger publish.
set -euo pipefail

PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_SRC="${PKG_DIR}/../UptimeSquirrel/uptimesquirrel-frontend/public/downloads/agent"
SRC_DIR="${1:-${DEFAULT_SRC}}"
DST_DIR="${PKG_DIR}/uptimesquirrel_agent"
VERSION_FILE="${SRC_DIR}/latest-linux.txt"

if [[ ! -d "${SRC_DIR}" ]]; then
    echo "ERROR: source dir not found: ${SRC_DIR}" >&2
    echo "Pass an explicit path: scripts/sync-from-frontend.sh /path/to/agent-dir" >&2
    exit 1
fi
if [[ ! -f "${VERSION_FILE}" ]]; then
    echo "ERROR: version file not found: ${VERSION_FILE}" >&2
    exit 1
fi

VERSION="$(tr -d '[:space:]' < "${VERSION_FILE}")"
echo "Syncing agent v${VERSION}"
echo "  source: ${SRC_DIR}"
echo "  target: ${DST_DIR}"

cp "${SRC_DIR}/uptimesquirrel_agent.py" "${DST_DIR}/agent.py"
cp "${SRC_DIR}/check_executor.py"       "${DST_DIR}/check_executor.py"
cp "${SRC_DIR}/task_manager.py"         "${DST_DIR}/task_manager.py"

# Rewrite flat imports to package-relative. The standalone download form uses
# `from check_executor import ...`; the package form needs `from .check_executor ...`.
python3 - "${DST_DIR}" <<'PY'
import pathlib, re, sys
dst = pathlib.Path(sys.argv[1])
patterns = [
    (re.compile(r'^(\s*)from check_executor import', re.M), r'\1from .check_executor import'),
    (re.compile(r'^(\s*)from task_manager import',  re.M), r'\1from .task_manager import'),
    (re.compile(r'^(\s*)from snmp_collector import',re.M), r'\1from .snmp_collector import'),
]
for f in ('agent.py', 'check_executor.py', 'task_manager.py'):
    p = dst / f
    text = p.read_text()
    orig = text
    for rx, repl in patterns:
        text = rx.sub(repl, text)
    if text != orig:
        p.write_text(text)
        print(f"  rewrote imports in {f}")
PY

echo "Updating pyproject.toml version to ${VERSION}"
python3 - "${PKG_DIR}/pyproject.toml" "${VERSION}" <<'PY'
import pathlib, re, sys
toml = pathlib.Path(sys.argv[1])
version = sys.argv[2]
text = toml.read_text()
new = re.sub(r'(?m)^version = "[^"]+"', f'version = "{version}"', text, count=1)
if new == text:
    print(f"WARNING: version line not found in pyproject.toml", file=sys.stderr)
toml.write_text(new)
PY

echo
echo "Done. Review the diff:"
echo "  git -C ${PKG_DIR} diff"
echo
echo "Then commit and tag:"
echo "  git -C ${PKG_DIR} add -A"
echo "  git -C ${PKG_DIR} commit -m 'Release v${VERSION}'"
echo "  git -C ${PKG_DIR} tag v${VERSION}"
echo "  git -C ${PKG_DIR} push origin main v${VERSION}"
