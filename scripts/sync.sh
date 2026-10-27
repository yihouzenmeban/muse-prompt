#!/bin/bash
# Full backup of the Muse home resource library to a private GitHub repo
# via SSH. Run it every few hours from a scheduled task; quiet on success.
#
# Setup: clone your (private!) backup repo to REPO_DIR below and set its
# origin; put a push-capable SSH key at KEY below; then list every
# credential file on your machine in .excludes.local (one rsync pattern
# per line, gitignored, never committed — see the loader below) — that
# list is the safety-critical part, take your time with it. The script
# aborts if that file is missing.
#
# Strategy: rsync $HOME into this repo (excluding secrets, regenerable
# bloat, and runtime-managed dirs), then commit and push when anything
# changed. The repo working tree therefore mirrors $HOME.
set -euo pipefail

REPO_DIR="$HOME/workspace/muse-backup"
KEY="$HOME/.ssh/github-backup"   # <-- your SSH key path
export GIT_SSH_COMMAND="ssh -i $KEY -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$HOME/.ssh/known_hosts"

command -v rsync >/dev/null || { echo "backup: rsync not found" >&2; exit 1; }
cd "$REPO_DIR"

EXCLUDES=(
  # The repo mirrors $HOME -- never touch the working tree itself.
  --exclude=/workspace/muse-backup/
  # Keep this script at the repo root (documents the backup, not mirrored).
  --exclude=/sync.sh
  # Repo-root files that live only in the repo (never mirrored): protect
  # them from --delete, which would otherwise remove them because they
  # are not in the source tree.
  --exclude=/.gitignore
  --exclude=/.excludes.local
  # --- secrets: never backed up ---
  --exclude=/.ssh/
  --exclude=/.config/ngrok/
  --exclude=.env
  # Project credential files: list YOUR OWN here, one by one — token
  # files, local config files with passwords, API key files. Examples:
  # --exclude=/workspace/my-project/config.local.json
  # --exclude=/workspace/my-project/.tokens.json
  # --exclude=/workspace/my-project/db/
  # --exclude=/workspace/my-tool/.api_key
  # --exclude=/workspace/my-tool/.credentials
  # --- regenerable bloat ---
  --exclude=.venv/
  --exclude=__pycache__/
  --exclude=node_modules/
  --exclude=.git/
  # --- runtime-managed dirs (not user resources) ---
  --exclude=/agents/
  --exclude=/assets/
  --exclude=/bin/
  --exclude=/docs/
  --exclude=/hooks/
  --exclude=/subscriptions/
  --exclude=/data/
  --exclude=/.cache/
  --exclude=/.local/
  --exclude=/.pki/
  # Runtime staging dir: root-owned 0700, unreadable, not user resources.
  --exclude=/.stagged-uploads/
  --exclude=/.hatch-db-change-signals
  --exclude=/runtime.lock
  --exclude=/.postgres-ready
)

# Local secret excludes (single source, never committed): one rsync
# --exclude pattern per line in $REPO_DIR/.excludes.local (gitignored).
# Your own credential paths live in that file, not in this script.
# Abort if it is missing — running without it could mirror credentials
# into the repo.
LOCAL_EXCLUDES="$REPO_DIR/.excludes.local"
if [ ! -f "$LOCAL_EXCLUDES" ]; then
  echo "backup: ABORT - $LOCAL_EXCLUDES missing; list your credential files there (one --exclude pattern per line)" >&2
  exit 1
fi
while IFS= read -r _line || [ -n "$_line" ]; do
  case "$_line" in ''|'#'*) continue ;; esac
  EXCLUDES+=( "--exclude=$_line" )
done < "$LOCAL_EXCLUDES"

rsync -a --delete "${EXCLUDES[@]}" "$HOME/" "$REPO_DIR/"

# Safety net: abort before committing if anything secret-looking slipped in.
if grep -rInE --exclude-dir=.git \
  -e 'ghp_[A-Za-z0-9]{10,}' \
  -e 'github_pat_[A-Za-z0-9_]{10,}' \
  -e 'gho_[A-Za-z0-9]{10,}' \
  -e 'AKIA[0-9A-Z]{16}' \
  -e 'xox[bpras]-[A-Za-z0-9-]{10,}' \
  -e 'sk-live-[A-Za-z0-9]{10,}' \
  "$REPO_DIR" ; then
  echo "backup: ABORT - possible secret detected in backup files" >&2
  exit 1
fi

git add -A
TS=$(date '+%Y-%m-%d %H:%M %Z')
if ! git diff --cached --quiet; then
  git -c user.name=muse-backup -c user.email=muse-backup@local commit -qm "Backup $TS"
fi
# Push whenever local is ahead of the remote (covers retries after a
# failed push, where there is nothing new to commit but origin is behind).
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git ls-remote origin main 2>/dev/null | awk '{print $1}')
if [ "$LOCAL" != "$REMOTE" ]; then
  git push -q origin main
  echo "backup: pushed ($TS)"
else
  echo "backup: no changes"
fi
