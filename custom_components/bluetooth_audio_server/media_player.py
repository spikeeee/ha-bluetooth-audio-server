"""
Media Player entities — one per configured audio output.

State mapping
-------------
OutputState.UNAVAILABLE  →  MediaPlayerState.UNAVAILABLE
OutputState.IDLE         →  MediaPlayerState.IDLE
OutputState.ROUTING      →  MediaPlayerState.BUFFERING
OutputState.PLAYING      →  MediaPlayerState.PLAYING

Supported HA features
---------------------
  VOLUME_SET   — sets output volume via the coordinator
  STOP         — calls async_stop_output on the coordinator

Because we use the ``media_player`` domain, automations can trigger on
``state: playing``, ``state: idle``, ``state: unavailable`` with no extra
configuration.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MAX_DELAY_MS, MIN_DELAY_MS, OutputState
from .coordinator import BluetoothAudioCoordinator

_LOGGER = logging.getLogger(__name__)

_OUTPUT_STATE_MAP: dict[OutputState, MediaPlayerState] = {
    OutputState.UNAVAILABLE: MediaPlayerState.UNAVAILABLE,
    OutputState.IDLE:        MediaPlayerState.IDLE,
    OutputState.ROUTING:     MediaPlayerState.BUFFERING,
    OutputState.PLAYING:     MediaPlayerState.PLAYING,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a MediaPlayer entity for each configured output."""
    coordinator: BluetoothAudioCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        BluetoothAudioOutputEntity(coordinator, output_id)
        for output_id in coordinator.get_all_output_ids()
    ]
    async_add_entities(entities)


class BluetoothAudioOutputEntity(CoordinatorEntity, MediaPlayerEntity):
    """
    Represents one audio output destination.

    The entity is a thin view over ``OutputConfig``; all mutations go through
    the coordinator so there is a single write path.
    """

    _attr_has_entity_name = True
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.STOP
    )

    def __init__(
        self,
        coordinator: BluetoothAudioCoordinator,
        output_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._output_id = output_id
        config = coordinator.get_output_config(output_id)

        self._attr_unique_id = f"{DOMAIN}_{output_id}"
        self._attr_name      = config.display_name if config else output_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, output_id)},
            name=self._attr_name,
            manufacturer="Bluetooth Audio Server",
            model=config.output_type if config else "unknown",
        )

    # ------------------------------------------------------------------
    # CoordinatorEntity callback — called whenever the coordinator pushes
    # an update (no polling)
    # ------------------------------------------------------------------

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # State properties
    # ------------------------------------------------------------------

    @property
    def _config(self):
        return self.coordinator.get_output_config(self._output_id)

    @property
    def state(self) -> MediaPlayerState:
        config = self._config
        if config is None:
            return MediaPlayerState.UNAVAILABLE
        return _OUTPUT_STATE_MAP.get(config.state, MediaPlayerState.UNAVAILABLE)

    @property
    def volume_level(self) -> float | None:
        config = self._config
        return config.volume if config else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose delay_ms as a state attribute for automations/dashboards."""
        config = self._config
        if config is None:
            return {}
        return {
            "delay_ms":    config.delay_ms,
            "output_type": config.output_type,
            "address":     config.address,
        }

    # ------------------------------------------------------------------
    # HA service handlers
    # ------------------------------------------------------------------

    async def async_set_volume_level(self, volume: float) -> None:
        self.coordinator.set_volume(self._output_id, volume)

    async def async_media_stop(self) -> None:
        await self.coordinator.async_stop_output(self._output_id)

    # Custom service: set_delay (called via hass.services.call)
    async def async_set_delay(self, delay_ms: int) -> None:
        delay_ms = max(MIN_DELAY_MS, min(MAX_DELAY_MS, delay_ms))
        self.coordinator.set_delay(self._output_id, delay_ms)
