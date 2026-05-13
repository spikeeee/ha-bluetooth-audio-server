"""
Sensor entities for the Bluetooth Audio Server.

Two sensors are created:
  - bt_audio_source_state   — current SourceState enum value
  - bt_audio_source_device  — friendly name of the connected BT source device
"""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SourceState
from .coordinator import BluetoothAudioCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BluetoothAudioCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SourceStateSensor(coordinator, entry),
        SourceDeviceSensor(coordinator, entry),
    ])


class _BaseSourceSensor(CoordinatorEntity, SensorEntity):
    """Shared base for source-level sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BluetoothAudioCoordinator,
        entry: ConfigEntry,
        sensor_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id  = f"{DOMAIN}_{entry.entry_id}_{sensor_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Bluetooth Audio Server",
            manufacturer="Bluetooth Audio Server",
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class SourceStateSensor(_BaseSourceSensor):
    """
    Tracks the A2DP source connection state.

    State values: disconnected | connecting | connected | streaming
    """

    _attr_icon = "mdi:bluetooth-audio"

    def __init__(
        self,
        coordinator: BluetoothAudioCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "source_state")
        self._attr_name = "Source State"

    @property
    def native_value(self) -> str:
        return self.coordinator.source_state

    @property
    def extra_state_attributes(self) -> dict:
        return {"raw_state": self.coordinator.source_state}


class SourceDeviceSensor(_BaseSourceSensor):
    """
    Shows the friendly name of the currently connected BT source device.
    Becomes None when nothing is connected.
    """

    _attr_icon = "mdi:cellphone-bluetooth"

    def __init__(
        self,
        coordinator: BluetoothAudioCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "source_device")
        self._attr_name = "Source Device"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.source_device_name
