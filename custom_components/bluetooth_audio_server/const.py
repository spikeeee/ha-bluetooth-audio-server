"""Constants for the Bluetooth Audio Server integration."""
from __future__ import annotations

from enum import StrEnum

DOMAIN = "bluetooth_audio_server"

# Config entry keys
CONF_SOURCE_ADAPTER = "source_adapter"   # e.g. "hci0"
CONF_OUTPUTS        = "outputs"

# Service names
SVC_ROUTE_TO_OUTPUT = "route_to_output"
SVC_STOP_OUTPUT     = "stop_output"
SVC_STOP_ALL        = "stop_all"
SVC_SET_DELAY       = "set_delay"
SVC_SET_VOLUME      = "set_volume"

# Service parameter keys
ATTR_OUTPUT_ID = "output_id"
ATTR_DELAY_MS  = "delay_ms"
ATTR_VOLUME    = "volume"

# Audio constants
SAMPLE_RATE    = 44100
CHANNELS       = 2
SAMPLE_WIDTH   = 2          # 16-bit PCM
BYTES_PER_SEC  = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH   # 176 400
CHUNK_BYTES    = 4096        # ~23 ms of audio per chunk

DEFAULT_DELAY_MS = 0
MAX_DELAY_MS     = 2000
MIN_DELAY_MS     = 0

# Output type discriminator
OUTPUT_TYPE_BLUETOOTH = "bluetooth"
OUTPUT_TYPE_ESP32     = "esp32"

# Platforms this integration creates entities on
PLATFORMS = ["media_player", "sensor"]


class SourceState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING   = "connecting"
    CONNECTED    = "connected"
    STREAMING    = "streaming"


class OutputState(StrEnum):
    UNAVAILABLE = "unavailable"
    IDLE        = "idle"
    ROUTING     = "routing"
    PLAYING     = "playing"
