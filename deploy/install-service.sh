#!/bin/bash
PLIST_SRC="$(dirname "$0")/com.avelero.enrichment.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.avelero.enrichment.plist"
cp "$PLIST_SRC" "$PLIST_DST"
launchctl load "$PLIST_DST"
echo "Service installed and loaded."
launchctl list | grep avelero
