#!/usr/bin/with-contenv bashio
# Version: V26.281.0251
# Two processes: the daily scheduler (background) and the settings web page
# (foreground, served to Home Assistant through Ingress).
set -e

export APEXLUNAR_DATA=/data      # config.json, backups/, logs/, state.json survive restarts
export APEXLUNAR_ADDON=1         # use the built-in scheduler instead of an OS one
cd /opt/apexlunar

bashio::log.info "Timezone: ${TZ:-not set} - daily update runs on this clock"
python3 -m apexlunar scheduler &

# Ingress reaches the add-on over the internal network; the port isn't published.
bashio::log.info "Starting ApexLunar web page on port 8788 (open it from the HA sidebar)"
exec python3 -m apexlunar web --bind 0.0.0.0 --port 8788 --no-browser
