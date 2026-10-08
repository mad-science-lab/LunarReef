# Version: V26.281.1108
ARG BUILD_FROM
FROM $BUILD_FROM

# Standard library only - no pip packages. tzdata so the daily run follows HA's timezone.
RUN apk add --no-cache python3 tzdata

# Staged into this folder by build_addon.ps1
COPY lunarreef/ /opt/lunarreef/lunarreef/
COPY config.example.json /opt/lunarreef/

COPY run.sh /
RUN chmod a+x /run.sh
CMD [ "/run.sh" ]
