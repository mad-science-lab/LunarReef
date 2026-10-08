# Version: V26.281.0251
ARG BUILD_FROM
FROM $BUILD_FROM

# Standard library only - no pip packages. tzdata so the daily run follows HA's timezone.
RUN apk add --no-cache python3 tzdata

# Staged into this folder by build_addon.ps1
COPY apexlunar/ /opt/apexlunar/apexlunar/
COPY config.example.json /opt/apexlunar/

COPY run.sh /
RUN chmod a+x /run.sh
CMD [ "/run.sh" ]
