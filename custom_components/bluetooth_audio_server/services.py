"""
Service registration for bluetooth_audio_server.

All services are callable via:
    hass.services.call("bluetooth_audio_server", "<service_name>", {<params>})

Or from a HA automation / script:
    service: bluetooth_audio_server.route_to_output
    data:
      output_id: "media_player.bt_output_living_room"

Service catalogue
-----------------
route_to_output   Start routing audio to one output
stop_output       Stop one output
stop_all          Stop all outputs
set_delay         Set per-output audio delay (ms)
set_volume        Set per-output volume (0.0–1.0)
"""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_DELAY_MS,
    ATTR_OUTPUT_ID,
    ATTR_VOLUME,
    DOMAIN,
    MAX_DELAY_MS,
    MIN_DELAY_MS,
    SVC_ROUTE_TO_OUTPUT,
    SVC_SET_DELAY,
    SVC_SET_VOLUME,
    SVC_STOP_ALL,
    SVC_STOP_OUTPUT,
)
from .coordinator import BluetoothAudioCoordinator

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Voluptuous schemas — enforce types and ranges before handlers are called
# ---------------------------------------------------------------------------

_OUTPUT_ID_SCHEMA = vol.Schema(
    {vol.Required(ATTR_OUTPUT_ID): cv.string},
    extra=vol.ALLOW_EXTRA,
)

_SET_DELAY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_OUTPUT_ID): cv.string,
        vol.Required(ATTR_DELAY_MS): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_DELAY_MS, max=MAX_DELAY_MS),
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

_SET_VOLUME_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_OUTPUT_ID): cv.string,
        vol.Required(ATTR_VOLUME): vol.All(
            vol.Coerce(float),
            vol.Range(min=0.0, max=1.0),
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def async_register_services(
    hass: HomeAssistant,
    coordinator: BluetoothAudioCoordinator,
) -> None:
    """Register all bluetooth_audio_server services with HA."""

    # --- route_to_output ---------------------------------------------------
    async def handle_route_to_output(call: ServiceCall) -> None:
        output_id = call.data[ATTR_OUTPUT_ID]
        _LOGGER.info("Service: route_to_output → %s", output_id)
        await coordinator.async_route_to_output(output_id)

    hass.services.async_register(
        DOMAIN,
        SVC_ROUTE_TO_OUTPUT,
        handle_route_to_output,
        schema=_OUTPUT_ID_SCHEMA,
    )

    # --- stop_output -------------------------------------------------------
    async def handle_stop_output(call: ServiceCall) -> None:
        output_id = call.data[ATTR_OUTPUT_ID]
        _LOGGER.info("Service: stop_output → %s", output_id)
        await coordinator.async_stop_output(output_id)

    hass.services.async_register(
        DOMAIN,
        SVC_STOP_OUTPUT,
        handle_stop_output,
        schema=_OUTPUT_ID_SCHEMA,
    )

    # --- stop_all ----------------------------------------------------------
    async def handle_stop_all(call: ServiceCall) -> None:
        _LOGGER.info("Service: stop_all")
        await coordinator.async_stop_all()

    hass.services.async_register(
        DOMAIN,
        SVC_STOP_ALL,
        handle_stop_all,
        schema=vol.Schema({}),
    )

    # --- set_delay ---------------------------------------------------------
    async def handle_set_delay(call: ServiceCall) -> None:
        output_id = call.data[ATTR_OUTPUT_ID]
        delay_ms  = call.data[ATTR_DELAY_MS]
        _LOGGER.info("Service: set_delay → %s = %d ms", output_id, delay_ms)
        coordinator.set_delay(output_id, delay_ms)

    hass.services.async_register(
        DOMAIN,
        SVC_SET_DELAY,
        handle_set_delay,
        schema=_SET_DELAY_SCHEMA,
    )

    # --- set_volume --------------------------------------------------------
    async def handle_set_volume(call: ServiceCall) -> None:
        output_id = call.data[ATTR_OUTPUT_ID]
        volume    = call.data[ATTR_VOLUME]
        _LOGGER.info("Service: set_volume → %s = %.2f", output_id, volume)
        coordinator.set_volume(output_id, volume)

    hass.services.async_register(
        DOMAIN,
        SVC_SET_VOLUME,
        handle_set_volume,
        schema=_SET_VOLUME_SCHEMA,
    )

    _LOGGER.debug("All bluetooth_audio_server services registered")


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove all services when the integration is unloaded."""
    for service in (
        SVC_ROUTE_TO_OUTPUT,
        SVC_STOP_OUTPUT,
        SVC_STOP_ALL,
        SVC_SET_DELAY,
        SVC_SET_VOLUME,
    ):
        hass.services.async_remove(DOMAIN, service)
    _LOGGER.debug("All bluetooth_audio_server services unregistered")
