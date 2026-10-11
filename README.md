<!-- Version: V26.284.1445 -->
# LunarReef

Makes the lunar (moonlight) channel of EcoTech Radion XR15 lights on a Neptune Apex
follow the real moon at your location.
Enter a latitude and longitude; LunarReef works out the moon's phase and when it
is above your horizon, and writes a matching control table to the lunar output
on the Apex.

## Related projects

| Name | Link | Description |
|---|---|---|
| **ReefHub** | <https://github.com/mad-science-lab/ReefHub> | Neptune Apex to MQTT bridge: read every outlet and probe, control outlets and feed modes. Home Assistant add-on and Docker. |
| **LunarReef** | <https://github.com/mad-science-lab/LunarReef> | Makes the lunar channel of EcoTech Radion XR15 lights follow the real moon at your location. Home Assistant add-on and local web app. |
| **RADclouds** | <https://github.com/mad-science-lab/RADclouds> | Drifts an EcoTech Radion profile on a Neptune Apex like passing clouds. Home Assistant add-on and local web app. |

## What it does

**Designed for EcoTech Radion XR15 lights connected to the Apex through a Neptune MXM module.**

- The Apex lists each Radion's lunar (moonlight) channel as its own output, type
  `MXMLight|Ecotech|15G6PL` (White + Blue), alongside the main light
  `MXMLight|Ecotech|15G6P`. LunarReef writes the lunar output's schedule table.
- With more than one Radion, group their lunar outputs in Apex Fusion and pick the
  group master; the Apex copies the table to the rest of the group.
- Developed and tested on an Apex running AOS 5.15L with two Radion XR15 G6 Pro.

Other MXM lights with a schedule table (other Radion models, AI Prime/Hydra) use
the same `tdata` format and may work, but are untested. Lights that aren't on the
MXM module are not supported.

Python 3.9+ standard library only. Runs on Windows, macOS or a Raspberry Pi, and as a
Home Assistant add-on.

## Install

### Home Assistant add-on

1. In Home Assistant: **Settings > Add-ons > Add-on Store > three-dot menu > Repositories**.
2. Add `https://github.com/mad-science-lab/LunarReef` and close the dialog.
3. Find **LunarReef** in the store, **Install**, **Start**, then open it from the sidebar.

The settings page is served through Ingress (HA's login, no published port). The daily
update runs in the container on HA's timezone and catches up after a restart. Settings,
backups and the log live in the add-on's `/data`, and on first start the location is
taken from HA's home.

To install from a Samba share instead, run `.\build_addon.ps1` (stages `dist\lunarreef`),
copy it to `\\<ha-ip>\addons\lunarreef`, then *Check for updates* in the store and
install **LunarReef** from *Local add-ons*.

### Standalone (without Home Assistant)

- **Windows:** double-click `run.bat`.
- **macOS / Pi:** `./run.sh` (add `--bind 0.0.0.0` to open it from a phone on your network).
- Opens <http://127.0.0.1:8788>. On first run `config.json` is created from `config.example.json`.

In the page: set your location ("Pick on map" needs internet for the map tiles, or
"Use this device's location"), pick the lunar output, **Preview**, then **Apply to Apex**.
The web page is only for settings and manual changes; it doesn't need to stay open.

**Daily update.** A separate one-shot job, `python -m lunarreef update`, writes the new
day's table (or does nothing if the Apex already has it), logs the result to
`logs/activity.jsonl` and exits. The operating system's scheduler runs it:

- **Windows:** in the page, *Daily update > Turn on*, or `python -m lunarreef schedule install --at 00:05`.
  Creates the Task Scheduler task "LunarReef Daily Update": daily at that time
  (computer clock) plus 1 minute after logon, and catches up a missed start. Runs
  `pythonw.exe`, so no window appears. The page shows the next/last run and every
  run's result under *Activity*.
- **macOS / Raspberry Pi:** not automated yet. Point cron/launchd/systemd at
  `python3 -m lunarreef update` in this folder.

## Configuration

`config.example.json` ships the Apex factory login (admin / 1234) used on the lab
test unit. `APEX_HOST`, `APEX_USER`, `APEX_PASSWORD` environment variables
override the file. `table.channels` = `null` keeps the color mix already on the
Apex; or set e.g. `{"White": 20, "Blue": 100}`.

Command line:

```
python -m lunarreef moon                 # phase, moonrise/set for your location
python -m lunarreef preview [--date D]   # current vs new table, changes nothing
python -m lunarreef apply --write        # back up, write, verify
python -m lunarreef restore <backup.json> --write
python -m lunarreef update               # the daily job: write today's table if needed
python -m lunarreef schedule install|uninstall|status|run [--at HH:MM]
```

## How it works

`intensity = full-moon intensity x fraction illuminated x min(altitude / ramp, 1)`,
zero while the moon is below the horizon. The day is sampled every 5 minutes on
the **Apex's** clock (its reported UTC offset, not the PC's) and reduced to at
most *Max table rows* `tdata` points; the Apex ramps between them itself.
The moon still drives the light when it is up in daytime.

Moon position is Meeus, *Astronomical Algorithms* ch. 47. Checked against USNO:
phase instants within 2-4 minutes, moonrise/set within ~3 minutes.

## Safety

Writes use the same calls as the Apex's own web UI: `POST /rest/login`,
`GET /rest/config/oconf/<id>`, change only the `tdata` lines of `prog` (Fallback / If
lines are kept), `PUT` the whole object back, then read it back to verify. Every write
saves the previous object to `backups/` first; `restore` puts one back.

**Groups:** write the group master. Verified on AOS 5.15L: the Apex copies the
master's table to the other members of the group (`Lunar` 3_66 -> `Lunar_3_67` 3_67).
LunarReef checks each member afterwards and writes any that did not follow.

## License and trademarks

Licensed under the [GNU Affero General Public License v3.0](LICENSE). Free for anyone to use; any copy, part or modified version, including one run as a hosted service, must stay open source under the same license.

LunarReef is an independent project, not affiliated with or endorsed by Neptune
Systems or EcoTech Marine. Neptune Apex is a trademark of Neptune Systems; EcoTech
and Radion are trademarks of EcoTech Marine. They are named only to describe the
equipment LunarReef works with.
