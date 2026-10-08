<!-- Version: V26.281.0215 -->
# ApexLunar

Makes a Neptune Apex's lunar lighting follow the real moon at your location.
Enter a latitude and longitude; ApexLunar works out the moon's phase and when it
is above your horizon, and writes a matching control table to the lunar output
on the Apex. Pure Python 3.9+ standard library, so no installs: runs the same on
Windows, macOS and Raspberry Pi.

## Run it

- **Windows:** double-click `run.bat`
- **macOS / Pi:** `./run.sh` (add `--bind 0.0.0.0` to open it from a phone on your network)
- Opens <http://127.0.0.1:8788>. On first run `config.json` is created from `config.example.json`.

In the page: set your location ("Pick on map" - needs internet for the map tiles - or
"Use this device's location"), pick the lunar
output, **Preview**, then **Apply to Apex**. Tick *Daily update* and leave the app
running to have it write a fresh table every day.

Command line, if you prefer:

```
python -m apexlunar moon                 # phase, moonrise/set for your location
python -m apexlunar preview [--date D]   # current vs new table, changes nothing
python -m apexlunar apply --write        # back up, write, verify
python -m apexlunar restore <backup.json> --write
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
