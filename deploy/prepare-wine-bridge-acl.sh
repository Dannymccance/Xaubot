#!/usr/bin/env bash
# Allow the sandboxed root-owned research bridge to read ONLY its xaumt5 MT5 CSV.
# We deliberately keep CapabilityBoundingSet= empty in systemd and DO NOT chmod 777.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: bash deploy/prepare-wine-bridge-acl.sh" >&2
  exit 1
fi
if ! command -v setfacl >/dev/null 2>&1; then
  echo "Missing setfacl; install 'acl' with apt install -y acl" >&2
  exit 1
fi

file="/home/xaumt5/.wine-xaubot/drive_c/users/xaumt5/AppData/Roaming/MetaQuotes/Terminal/Common/Files/xaubot_xauusd_m1_server.csv"
if [[ ! -f "$file" || -L "$file" ]]; then
  echo "Source CSV missing or a symbolic link: refusing to change permissions." >&2
  exit 1
fi
if [[ "$(stat -c %U "$file")" != "xaumt5" ]]; then
  echo "Unexpected file owner: refusing to change permissions." >&2
  exit 1
fi

folder="${file%/*}"
current="$folder"
while [[ "$current" != "/home" ]]; do
  if [[ ! -d "$current" || -L "$current" ]]; then
    echo "Unexpected symlink or missing directory in Wine source path." >&2
    exit 1
  fi
  # The root-based bridge has no CAP_DAC_OVERRIDE or CAP_DAC_READ_SEARCH.
  # Grant root traversal only, not directory listing or write access.
  setfacl -m u:root:--x "$current"
  current="${current%/*}"
done

# Read access to this CSV, not to other files in the Wine prefix.
setfacl -m u:root:r-- "$file"

# MQL5 FileMove replaces the destination with a newly created temp file.
# Let newly created files in this one directory inherit a read ACL for root.
setfacl -m d:u:root:r-x "$folder"

echo "Configured narrowly scoped Wine CSV read ACL for Xaubot bridge."
echo "Next: systemctl restart xaubot-wine-bridge.service"
echo "Then: journalctl -u xaubot-wine-bridge.service -n 25 --no-pager"
