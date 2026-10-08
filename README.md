# LYWSD02 Sync

Set the clock of Xiaomi **LYWSD02 / LYWSD02MMC** e-Ink clocks from Home
Assistant, over Bluetooth - so that all your ESPHome Bluetooth proxies are used
for coverage.

Fork of [ashald/home-assistant-lywsd02](https://github.com/ashald/home-assistant-lywsd02)
by Borys Pierov (`ashald`), including the work of the contributors of
[pull request #22](https://github.com/ashald/home-assistant-lywsd02/pull/22)
(`ernetas`). Licensed under the Unlicense, like the original.

## What this fork adds

| | Upstream | Here |
|---|---|---|
| Set the clock from a YAML service | ✅ | ✅ (kept, unchanged) |
| Bluetooth auto-discovery | PR #22 only | ✅ |
| Device page + "Sync now" button | PR #22 only | ✅ |
| Failing sync raises (instead of a silent log) | PR #22 only | ✅ |
| **Built-in daily schedule** | ❌ | ✅ |
| **Diagnostic entities (last sync, sync problem)** | ❌ | ✅ |
| **Anti-loop guard** | ❌ | ✅ |

The point of the last three: this integration writes to a device that reports
nothing back. Without them, a clock that stopped being synchronised is simply
invisible - the automation stays green and the display keeps showing the wrong
time.

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋯ → **Custom repositories**
2. Add `https://github.com/rpouetpouet/ha-lywsd02-sync`, category **Integration**
3. Install it, then **restart Home Assistant**

### Adding a clock

Either accept the discovery prompt (the manifest declares the `LYWSD02` and
`LYWSD02MMC` Bluetooth local names), or **Add integration → LYWSD02 Sync** and
enter the MAC address.

The config entry is optional: the legacy service below works without it.

## Entities

| Entity | What it is |
|---|---|
| `button.<clock>_sync_now` | Syncs the clock immediately |
| `sensor.<clock>_last_sync` | Timestamp of the last **successful** sync (diagnostic) |
| `binary_sensor.<clock>_sync_problem` | `on` when the last attempt failed |

`sensor.<clock>_last_sync` also carries `result`, `last_error`, `last_trigger`
(`schedule`, `startup`, `button`), `duration_ms`, `sync_count`,
`skipped_count`, `schedule_time` and `next_sync` as attributes.

## Options (Configure on the integration entry)

| Option | Default | Notes |
|---|---|---|
| Synchronise automatically | on | enables the built-in daily schedule |
| Daily sync time | `04:00` | deliberately outside the DST transition window, see below |
| Also sync shortly after start | on | 60 s after Home Assistant starts |
| Displayed temperature unit | leave unchanged | `C` / `F` |
| Clock face | leave unchanged | `12` / `24`, **LYWSD02MMC only** |
| Bluetooth connection timeout | 60 s | raise it if the connection fails |

With the schedule enabled, **no YAML automation is needed** - you can delete it.

## Time zones and daylight saving time

The device displays `timestamp + tz_offset` as wall-clock time, so the
integration sends `now_utc + local_utc_offset` (and `tz_offset`, sent
separately, is subtracted from it - baking the full offset in *and* sending a
non-zero `tz_offset` made the clock run fast, upstream issue #13). The offset
comes from Home Assistant's time zone, never from the host OS, which is usually
UTC inside a container.

Two DST traps were considered deliberately, and both are covered by tests
(`tests/test_dst.py`):

1. **Drift accumulating across syncs.** Every sync writes the *current local
   wall clock*, so nothing adds up over time. Proof: 8 760 hourly syncs spread
   over a whole year (both transitions included) keep the displayed time exactly
   equal to the local wall clock - maximum deviation 0 seconds. There is no
   "go back one hour every hour" behaviour to fall into: each write is
   independent of the previous one.
2. **A double trigger around the transition.** At 04:00 the pattern exists
   exactly once a day; the fall-back night repeats `02:00`-`02:59` (once, at
   `02:00`, not in a loop), and the spring-forward night simply skips it - so
   `04:00` is fired once in both cases. As a belt-and-braces measure, an
   automatic sync is skipped when an attempt already happened less than
   **5 minutes** earlier (`MIN_RESYNC_INTERVAL`). A manual press is never
   skipped.

Schedule the sync **outside 02:00-03:00 local time** to stay clear of the
ambiguous window: `04:00` (the default) is safe year-round.

## Legacy YAML service

Kept for backwards compatibility, no config entry required:

```yaml
service: lywsd02.set_time
data:
  mac: A1:B2:C3:D4:E5:F6
```

Optional parameters: `timestamp`, `tz_offset` (leave at 0), `temp_mode`,
`clock_mode`, `timeout`. Unlike upstream, a failure **raises** - a failed
service call is now visible in the automation that called it.

YAML setup (only needed for the service):

```yaml
lywsd02:
```

## Limitations

- **`clock_mode` (12/24-hour) is only supported on the LYWSD02MMC.** The
  7-byte payload is validated against a Mi Home capture, but the plain LYWSD02
  has a fixed-length 5-byte time characteristic and rejects it. In that case the
  time is still set and a warning is logged. See upstream
  [#10](https://github.com/ashald/home-assistant-lywsd02/issues/10).
- A **connectable** Bluetooth path is required: an ESPHome Bluetooth proxy in
  range, or a local adapter. A passive-only path is not enough.
- This integration only writes the clock. Temperature and humidity readings come
  from Home Assistant's built-in Bluetooth/Xiaomi support.

## Tests

```bash
python3 tests/test_dst.py          # timezone / DST proofs
python3 tests/test_sync_logic.py   # option merging, schedule parsing, guard
python3 tests/test_imports.py      # static check: no missing constant import
```

No Home Assistant installation required: the helpers module imports nothing
from Home Assistant, so the tests exercise real behaviour.
