#!/bin/sh
# Version: V26.281.1108
# Start LunarReef (macOS / Raspberry Pi). Add --bind 0.0.0.0 to reach it from your phone.
cd "$(dirname "$0")"
exec python3 -m lunarreef web "$@"
