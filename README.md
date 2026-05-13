# 🔊 Bluetooth Audio Server

> A Home Assistant custom integration that turns your HA host into an A2DP Bluetooth sink, routing audio from any connected device to multiple smart speakers and ESP32 satellites — with per-speaker delay compensation for perfect synchronisation.

[![Version](https://img.shields.io/badge/version-1.0.0-blue?style=flat-square)](https://github.com/spikeeee/ha-bluetooth-audio-server/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange?style=flat-square&logo=home-assistant-community-store)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-brightgreen?style=flat-square&logo=home-assistant)](https://www.home-assistant.io)
[![License](https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square)](LICENSE)
[![Author](https://img.shields.io/badge/author-Spike-blueviolet?style=flat-square)](https://designspiked.co.uk)

---

## Table of Contents

- [About](#about)
- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Requirements](#requirements)
- [Installation](#installation)
  - [HACS (Recommended)](#hacs-recommended)
  - [Manual Installation](#manual-installation)
- [Configuration](#configuration)
  - [Setting Up the Integration](#setting-up-the-integration)
  - [Adding the Lovelace Card](#adding-the-lovelace-card)
- [Services Reference](#services-reference)
- [Entities Created](#entities-created)
- [Automation Examples](#automation-examples)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## About

| | |
|---|---|
| **Version** | 1.0.0 |
| **Author** | Spike |
| **Website** | [designspiked.co.uk](https://designspiked.co.uk) |
| **Platform** | Linux (requires BlueZ + bluealsa) |
| **HA Domain** | `bluetooth_audio_server` |

**Bluetooth Audio Server** solves a common smart-home problem: you want to play music from your phone through multiple speakers in perfect sync, routed and controlled entirely within Home Assistant.

Connect your phone over Bluetooth once. The integration captures the audio stream, duplicates it to every configured output (Bluetooth speakers or ESP32-based satellites), and applies an independently configurable delay per speaker to compensate for different hardware latencies — so every room plays in time.

Because each output is a standard `media_player` entity, the full power of HA automations (`state: playing`, `state: unavailable`, presence-based routing, time-based scene changes) is available with zero extra configuration.

---

## Features

- **A2DP Bluetooth Sink** — pairs with any Bluetooth source device (phone, tablet, laptop)
- **Multi-room audio routing** — duplicate and route to any number of outputs simultaneously
- **Per-speaker audio delay** — 0–2,000 ms programmable delay buffer for latency compensation
- **ESP32 satellite support** — stream raw PCM over UDP to custom I2S satellite speakers
- **Standard `media_player` entities** — works with all existing HA automations and dashboards
- **Volume control per output** — independent levels with real-time adjustment
- **Custom Lovelace card** — dedicated sidebar panel with source display, output cards, settings drawers, and a stop-all button
- **Full service API** — every action callable via `hass.services.call` or automation YAML

---

## Architecture Overview

```
Phone / Tablet
  │  (Bluetooth A2DP)
  ▼
HA Host (BlueZ A2DP Sink)
  │
  ├─── BluetoothSource (bluealsa PCM capture)
  │
  └─── AudioRouter
         │  TimestampedChunk fan-out
         ├──[delay buffer]──► BluetoothSink ──► Living Room Speaker (BT)
         ├──[delay buffer]──► BluetoothSink ──► Bedroom Speaker (BT)
         └──[delay buffer]──► ESP32Sink (UDP) ──► Kitchen Satellite (ESP32/I2S)

  HA Entities:
    sensor.bt_audio_source_state      (disconnected / streaming)
    sensor.bt_audio_source_device     (friendly name of connected phone)
    media_player.bt_output_*          (one per output; state, volume, delay_ms)

  Lovelace Card:
    custom:bluetooth-audio-card       (source selector + output control panels)
```

---

## Requirements

### Host System

| Requirement | Notes |
|---|---|
| **Linux** | BlueZ requires Linux. Tested on Raspberry Pi OS (Bookworm) and Debian 12. |
| **BlueZ ≥ 5.66** | Provides the D-Bus A2DP profile API. |
| **bluealsa** | Exposes the A2DP stream as a virtual ALSA PCM device. Install: `sudo apt install bluealsa` |
| **Python 3.11+** | Required by HA 2024.1+. |

### Python Packages

Installed automatically by HACS / HA on first run (declared in `manifest.json`):

```
pydbus>=0.6.0
pyalsaaudio>=0.10.0
```

### Home Assistant

- Home Assistant **2024.1** or later
- HACS **1.34+** (for HACS installation method)

---

## Installation

### HACS (Recommended)

This integration ships two HACS entries: one for the **custom integration** and one for the **Lovelace frontend card**. Add both.

#### Step 1 — Add the Integration

1. Open your Home Assistant UI and navigate to **HACS → Integrations**.
2. Click the **⋮ (three-dot menu)** in the top-right corner and select **Custom repositories**.
3. Enter the repository URL:
   ```
   https://github.com/spikeeee/ha-bluetooth-audio-server
   ```
4. Set the **Category** to `Integration` and click **Add**.
5. Close the dialog. Search for **"Bluetooth Audio Server"** in the HACS Integrations list.
6. Click **Download** and confirm.
7. **Restart Home Assistant.**

#### Step 2 — Add the Lovelace Card

1. Navigate to **HACS → Frontend**.
2. Click **⋮ → Custom repositories**.
3. Enter the same repository URL and set Category to `Lovelace`.
4. Close and search for **"Bluetooth Audio Card"**.
5. Click **Download**.
6. The card resource will be registered automatically. If not, see [Adding the Lovelace Card](#adding-the-lovelace-card).

#### Step 3 — Set Up the Integration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **"Bluetooth Audio Server"** and follow the config flow.

---

### Manual Installation

#### Integration

1. Download or clone this repository.
2. Copy the `custom_components/bluetooth_audio_server/` directory into your HA configuration directory:
   ```
   <ha-config>/custom_components/bluetooth_audio_server/
   ```
3. Restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration → Bluetooth Audio Server**.

#### Lovelace Card

1. Copy `www/bluetooth-audio-card.js` into your HA configuration:
   ```
   <ha-config>/www/bluetooth-audio-card.js
   ```
2. Register it as a Lovelace resource (**Settings → Dashboards → Resources → Add resource**):
   ```
   URL:  /local/bluetooth-audio-card.js
   Type: JavaScript module
   ```
3. Clear your browser cache (Ctrl + Shift + R).

---

## Configuration

### Setting Up the Integration

After installation, the config flow guides you through:

1. **Select Bluetooth Adapter** — choose which adapter (e.g., `hci0`) acts as the A2DP sink.
2. **Add Outputs** — for each speaker, choose the type:
   - **Bluetooth** — enter the speaker's MAC address
   - **ESP32 Satellite** — enter the device's IP address and UDP port (default: `5005`)
3. Set an optional **display name** and **initial delay (ms)** per output.

A complete `configuration.yaml` example (including helper entities for the automation examples) can be found in [`docs/configuration.yaml`](docs/configuration.yaml).

---

### Adding the Lovelace Card

Add the card to any dashboard:

```yaml
type: custom:bluetooth-audio-card
title: "Music Server"
source_sensor: sensor.bt_audio_source_state
source_device_sensor: sensor.bt_audio_source_device
outputs:
  - entity: media_player.bt_output_living_room
    name: Living Room
  - entity: media_player.bt_output_bedroom
    name: Bedroom
  - entity: media_player.bt_output_esp32_kitchen
    name: Kitchen
```

| Option | Required | Description |
|---|---|---|
| `title` | No | Card header text. Default: `"Bluetooth Audio"` |
| `source_sensor` | Yes | Entity ID of the source state sensor |
| `source_device_sensor` | Yes | Entity ID of the source device name sensor |
| `outputs` | Yes | List of `{ entity, name }` output descriptors |

---

## Services Reference

All services are in the `bluetooth_audio_server` domain and callable from automations, scripts, the Developer Tools, or `hass.callService` in frontend code.

### `route_to_output`

Start routing the captured audio stream to a specific output.

```yaml
service: bluetooth_audio_server.route_to_output
data:
  output_id: media_player.bt_output_living_room
```

| Parameter | Type | Required | Description |
|---|---|---|---|
| `output_id` | string | Yes | Entity ID of the target output media player |

---

### `stop_output`

Stop audio routing to a single output. The output returns to `idle` state.

```yaml
service: bluetooth_audio_server.stop_output
data:
  output_id: media_player.bt_output_living_room
```

---

### `stop_all`

Stop all active outputs simultaneously.

```yaml
service: bluetooth_audio_server.stop_all
```

---

### `set_delay`

Set the audio delay (in milliseconds) for one output. Takes effect on the next audio chunk — no restart required.

```yaml
service: bluetooth_audio_server.set_delay
data:
  output_id: media_player.bt_output_living_room
  delay_ms: 250
```

| Parameter | Type | Required | Range | Description |
|---|---|---|---|---|
| `output_id` | string | Yes | — | Target output entity ID |
| `delay_ms` | int | Yes | 0–2000 | Delay in milliseconds |

**Tip:** Use `delay_ms` to synchronise speakers with different hardware latencies. Measure the delay of your fastest speaker with an audio analysis tool, then add delay to all others to match.

---

### `set_volume`

Set the playback volume for one output.

```yaml
service: bluetooth_audio_server.set_volume
data:
  output_id: media_player.bt_output_living_room
  volume: 0.75
```

| Parameter | Type | Required | Range | Description |
|---|---|---|---|---|
| `output_id` | string | Yes | — | Target output entity ID |
| `volume` | float | Yes | 0.0–1.0 | Volume level |

---

## Entities Created

| Entity ID | Domain | Description |
|---|---|---|
| `sensor.bt_audio_source_state` | `sensor` | Current source state: `disconnected` / `connecting` / `connected` / `streaming` |
| `sensor.bt_audio_source_device` | `sensor` | Friendly name of the connected Bluetooth source device |
| `media_player.bt_output_{name}` | `media_player` | One per configured output; exposes `state`, `volume_level`, and `delay_ms` attribute |

### Output entity states

| HA State | Meaning |
|---|---|
| `playing` | Audio is actively streaming to this output |
| `buffering` | Stream worker starting; audio arriving shortly |
| `idle` | Output is reachable but not receiving audio |
| `unavailable` | Output could not be connected |

### Extra state attributes on `media_player.*` entities

```yaml
# Example: media_player.bt_output_living_room
state: playing
attributes:
  volume_level: 0.75
  delay_ms: 120
  output_type: bluetooth       # or esp32
  address: "AA:BB:CC:DD:EE:FF" # or "192.168.1.50:5005"
```

---

## Automation Examples

Three ready-to-use automation files are included in [`docs/automations/`](docs/automations/):

| File | Scenario | Description |
|---|---|---|
| [`moving_room.yaml`](docs/automations/moving_room.yaml) | Moving Room | Audio follows you from room to room using presence sensors |
| [`mass_broadcast.yaml`](docs/automations/mass_broadcast.yaml) | Mass Broadcast | Activate all speakers instantly for party mode or announcements |
| [`conditional_playback.yaml`](docs/automations/conditional_playback.yaml) | Conditional Playback | Smart routing based on time of day, occupancy, and volume ramping |

To import an automation into HA:

1. Go to **Settings → Automations & Scenes → Automations**.
2. Click **⋮ → Import via YAML** (or create a new automation and paste the YAML in the code editor).

---

## Troubleshooting

### No audio from Bluetooth source

1. Check that `bluealsa` is running: `systemctl status bluealsa`
2. Confirm your adapter is discoverable: `bluetoothctl show`
3. Check HA logs for `bluetooth_audio_server` errors: **Settings → Logs → Filter by `bluetooth_audio_server`**

### Speakers are out of sync

Use the **Audio Delay** slider in the Lovelace card settings drawer (⚙ per output) or call `set_delay` directly. Increase the delay on the *faster* speaker until it matches the slower one.

### Card not appearing in the UI

- Ensure the JS resource is registered under **Settings → Dashboards → Resources**.
- Hard-refresh the browser with **Ctrl + Shift + R** (or Cmd + Shift + R on Mac).
- Check browser console for import errors (F12 → Console).

### `media_player` entity stuck on `unavailable`

- Verify the Bluetooth MAC address or ESP32 IP is correct in the integration config.
- Ensure `bluealsa` can see the device: `bluealsa-aplay -l`
- For ESP32 satellites: confirm the device is on the same network and its firmware is running.

---

## Contributing

Contributions are welcome! Please open an issue or pull request on GitHub.

- Report bugs: [GitHub Issues](https://github.com/spikeeee/ha-bluetooth-audio-server/issues)
- Discuss features: [GitHub Discussions](https://github.com/spikeeee/ha-bluetooth-audio-server/discussions)

---

## License

MIT © 2025 [Spike](https://designspiked.co.uk)

See [LICENSE](LICENSE) for full text.
