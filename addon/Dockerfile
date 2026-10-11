# Version: V26.281.1108
ARG BUILD_FROM
FROM $BUILD_FROM

# Standard library only - no pip packages. tzdata so the daily run follows HA's timezone.
RUN apk add --no-cache python3 tzdata curl

# LunarReef itself, fetched from the matching tag on GitHub.
# Keep LUNARREEF_REF in step with `version` in config.yaml (tag = v<version>).
ARG LUNARREEF_REF=v0.1.0
RUN mkdir -p /opt/lunarreef /tmp/src \
 && curl -fsSL "https://github.com/mad-science-lab/LunarReef/archive/refs/tags/${LUNARREEF_REF}.tar.gz" \
    | tar -xz -C /tmp/src \
 && mv /tmp/src/*/lunarreef /tmp/src/*/config.example.json /opt/lunarreef/ \
 && rm -rf /tmp/src

COPY run.sh /
RUN chmod a+x /run.sh
CMD [ "/run.sh" ]
