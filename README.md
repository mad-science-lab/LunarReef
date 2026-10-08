<!-- Version: V26.281.0247 -->
# ApexLunar

Makes the lunar (moonlight) channel of EcoTech Radion XR15 lights on a Neptune Apex
follow the real moon at your location.
Enter a latitude and longitude; ApexLunar works out the moon's phase and when it
is above your horizon, and writes a matching control table to the lunar output
on the Apex. Pure Python 3.9+ standard library, so no installs: runs the same on
Windows, macOS and Raspberry Pi.

## Designed for

**EcoTech Radion XR15 lights connected to the Apex through a Neptune MXM module.**

- The Apex lists each Radion's lunar (moonlight) channel as its own output, type
  `MXMLight|Ecotech|15G6PL` (White + Blue), alongside the main light
  `MXMLight|Ecotech|15G6P`. ApexLunar writes the lunar output's schedule table.
- With more than one Radion, group their lunar outputs in Apex Fusion and pick the
  group master; the Apex copies the table to the rest of the group.
- Developed and tested on an Apex running AOS 5.15L with two Radion XR15 G6 Pro.

Other MXM lights with a schedule table (other Radion models, AI Prime/Hydra) use
the same `tdata` format and may work, but are untested. Lights that aren't on the
MXM module are not supported.

## Run it

- **Windows:** double-click `run.bat`
- **macOS / Pi:** `./run.sh` (add `--bind 0.0.0.0` to open it from a phone on your network)
- Opens <http://127.0.0.1:8788>. On first run `config.json` is created from `config.example.json`.

In the page: set your location ("Pick on map" - needs internet for the map tiles - or
"Use this device's location"), pick the lunar
output, **Preview**, then **Apply to Apex**.

The web page is only for settings and manual changes; it doesn't need to stay open.

## Daily update

A separate one-shot job, `python -m apexlunar update`, writes the new day's table
(or does nothing if the Apex already has it), logs the result to `logs/activity.jsonl`
and exits. The operating system's scheduler runs it:

- **Windows:** in the page, *Daily update -> Turn on*, or `python -m apexlunar schedule install --at 00:05`.
  Creates the Task Scheduler task "ApexLunar Daily Update": daily at that time
  (computer clock) plus 1 minute after logon, and catches up a missed start. Runs
  `pythonw.exe`, so no window appears. The page shows the next/last run and every
  run's result under *Activity*.
- **macOS / Raspberry Pi:** not automated yet - point cron/launchd/systemd at
  `python3 -m apexlunar update` in this folder.

Command line, if you prefer:

```
python -m apexlunar moon                 # phase, moonrise/set for your location
python -m apexlunar preview [--date D]   # current vs new table, changes nothing
python -m apexlunar apply --write        # back up, write, verify
python -m apexlunar restore <backup.json> --write
python -m apexlunar update               # the daily job: write today's table if needed
python -m apexlunar schedule install|uninstall|status|run [--at HH:MM]
```

## How the table is built

`intensity = full-moon intensity x fraction illuminated x min(altitude / ramp, 1)`,
zero while the moon is below the horizon. The day is sampled every 5 minutes on
the **Apex's** clock (its reported UTC offset, not the PC's) and reduced to at
most *Max table rows* `tdata` points; the Apex ramps between them itself.
The moon still drives the light when it is up in daytime.

Moon position is Meeus, *Astronomical Algorithms* ch. 47. Checked against USNO:
phase instants within 2-4 minutes, moonrise/set within ~3 minutes.

## How it writes to the Apex

Same calls as the Apex's own web UI: `POST /rest/login`, `GET /rest/config/oconf/<id>`,
change only the `tdata` lines of `prog` (Fallback / If lines are kept), `PUT` the
whole object back, then read it back to verify. Every write saves the previous
object to `backups/` first.

**Groups:** write the group master. Verified on AOS 5.15L: the Apex copies the
master's table to the other members of the group (`Lunar` 3_66 -> `Lunar_3_67` 3_67).
ApexLunar checks each member afterwards and writes any that did not follow.

## Config

`config.example.json` ships the Apex factory login (admin / 1234) used on the lab
test unit. `APEX_HOST`, `APEX_USER`, `APEX_PASSWORD` environment variables
override the file. `table.channels` = `null` keeps the color mix already on the
Apex; or set e.g. `{"White": 20, "Blue": 100}`.
