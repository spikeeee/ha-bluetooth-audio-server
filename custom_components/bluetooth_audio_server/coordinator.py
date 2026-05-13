"""
Central coordinator — the single source of truth for the integration.

The coordinator bridges:
  BluetoothSource  →  AudioRouter  →  HA entities

All entities subscribe to the coordinator via ``async_add_listener``.
When state changes the coordinator calls ``async_update_listeners`` to push
the update to every subscribed entity without polling.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .audio_router import AudioRouter, BluetoothSink, ESP32Sink, OutputConfig
from .bluetooth_source import BluetoothSource
from .const import (
    DEFAULT_DELAY_MS,
    DOMAIN,
    OUTPUT_TYPE_BLUETOOTH,
    OUTPUT_TYPE_ESP32,
    OutputState,
    SourceState,
)

_LOGGER = logging.getLogger(__name__)


class BluetoothAudioCoordinator(DataUpdateCoordinator):
    """
    Owns BluetoothSource and AudioRouter.
    Exposes the high-level actions consumed by services and entities.
    """

    def __init__(self, hass: HomeAssistant, adapter: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # No polling — all updates are push-driven.
            update_interval=None,
        )
        self.source_state: SourceState  = SourceState.DISCONNECTED
        self.source_device_name: str | None = None

        self._router = AudioRouter(
            on_output_state_changed=self._on_output_state_changed
        )
        self._source = BluetoothSource(
            adapter=adapter,
            on_connected=self._on_source_connected,
            on_disconnected=self._on_source_disconnected,
            on_stream_start=self._on_stream_start,
            on_stream_stop=self._on_stream_stop,
            on_chunk=self._router.distribute_chunk,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Start BlueZ monitoring. Called from __init__.py on entry setup."""
        await self._source.async_setup()

    async def async_shutdown(self) -> None:
        """Tear down everything. Called from __init__.py on entry unload."""
        await self._router.async_stop_all()
        await self._source.async_teardown()

    # ------------------------------------------------------------------
    # Output registration (called from config flow / options flow)
    # ------------------------------------------------------------------

    async def async_add_bluetooth_output(
        self,
        output_id: str,
        display_name: str,
        mac_address: str,
        delay_ms: int = DEFAULT_DELAY_MS,
    ) -> None:
        config = OutputConfig(
            output_id=output_id,
            display_name=display_name,
            output_type=OUTPUT_TYPE_BLUETOOTH,
            address=mac_address,
            delay_ms=delay_ms,
        )
        sink = BluetoothSink(mac_address)
        await self._router.async_add_output(config, sink)
        self.async_update_listeners()

    async def async_add_esp32_output(
        self,
        output_id: str,
        display_name: str,
        host: str,
        port: int = 5005,
        delay_ms: int = DEFAULT_DELAY_MS,
    ) -> None:
        config = OutputConfig(
            output_id=output_id,
            display_name=display_name,
            output_type=OUTPUT_TYPE_ESP32,
            address=f"{host}:{port}",
            delay_ms=delay_ms,
        )
        sink = ESP32Sink(host, port)
        await self._router.async_add_output(config, sink)
        self.async_update_listeners()

    async def async_remove_output(self, output_id: str) -> None:
        await self._router.async_remove_output(output_id)
        self.async_update_listeners()

    # ------------------------------------------------------------------
    # Service actions
    # ------------------------------------------------------------------

    async def async_route_to_output(self, output_id: str) -> None:
        """Start streaming audio to a specific output."""
        await self._router.async_route_output(output_id)

    async def async_stop_output(self, output_id: str) -> None:
        """Stop streaming to a specific output."""
        await self._router.async_stop_output(output_id)

    async def async_stop_all(self) -> None:
        """Stop all outputs."""
        await self._router.async_stop_all()

    def set_delay(self, output_id: str, delay_ms: int) -> None:
        """Set per-output delay (takes effect on next chunk)."""
        self._router.set_delay(output_id, delay_ms)
        self.async_update_listeners()

    def set_volume(self, output_id: str, volume: float) -> None:
        """Set per-output volume."""
        self._router.set_volume(output_id, volume)
        self.async_update_listeners()

    # ------------------------------------------------------------------
    # Read accessors for entities
    # ------------------------------------------------------------------

    def get_output_config(self, output_id: str) -> OutputConfig | None:
        return self._router._outputs.get(output_id)

    def get_all_output_ids(self) -> list[str]:
        return list(self._router._outputs.keys())

    # ------------------------------------------------------------------
    # BluetoothSource callbacks (run on the HA event loop)
    # ------------------------------------------------------------------

    def _on_source_connected(self, device_name: str) -> None:
        self.source_state       = SourceState.CONNECTED
        self.source_device_name = device_name
        _LOGGER.info("Source connected: %s", device_name)
        self.async_update_listeners()

    def _on_source_disconnected(self) -> None:
        self.source_state       = SourceState.DISCONNECTED
        self.source_device_name = None
        # Stop all outputs — no stream to route.
        self.hass.async_create_task(self.async_stop_all())
        _LOGGER.info("Source disconnected")
        self.async_update_listeners()

    def _on_stream_start(self) -> None:
        self.source_state = SourceState.STREAMING
        _LOGGER.info("Audio stream started")
        self.async_update_listeners()

    def _on_stream_stop(self) -> None:
        if self.source_state == SourceState.STREAMING:
            self.source_state = SourceState.CONNECTED
        _LOGGER.info("Audio stream stopped")
        self.async_update_listeners()

    # ------------------------------------------------------------------
    # AudioRouter callbacks
    # ------------------------------------------------------------------

    def _on_output_state_changed(self, output_id: str, state: OutputState) -> None:
        _LOGGER.debug("Output %s → %s", output_id, state)
        self.async_update_listeners()

    # ------------------------------------------------------------------
    # DataUpdateCoordinator required override
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> None:
        # Push-only integration — no polling fetch needed.
        return None
