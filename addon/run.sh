#!/usr/bin/with-contenv bashio
# Version: V26.281.1108
# Two processes: the daily scheduler (background) and the settings web page
# (foreground, served to Home Assistant through Ingress).
set -e

export LUNARREEF_DATA=/data      # config.json, backups/, logs/, state.json survive restarts
export LUNARREEF_ADDON=1         # use the built-in scheduler instead of an OS one
cd /opt/lunarreef

bashio::log.info "Timezone: ${TZ:-not set} - daily update runs on this clock"
python3 -m lunarreef scheduler &

# Ingress reaches the add-on over the internal network; the port isn't published.
bashio::log.info "Starting LunarReef web page on port 8788 (open it from the HA sidebar)"
exec python3 -m lunarreef web --bind 0.0.0.0 --port 8788 --no-browser
