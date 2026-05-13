"""
Bluetooth Audio Server — Home Assistant Integration entry point.

Setup flow
----------
1. HA calls ``async_setup_entry`` with the ConfigEntry created by config_flow.
2. We instantiate the coordinator, register services, then forward platform
   setup to media_player.py and sensor.py.
3. On unload HA calls ``async_unload_entry`` which reverses everything.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_OUTPUTS, CONF_SOURCE_ADAPTER, DOMAIN, PLATFORMS
from .coordinator import BluetoothAudioCoordinator
from .services import async_register_services, async_unregister_services

def _check_system_deps() -> None:
    """Warn at startup if optional C-extension libraries are missing.

    pyalsaaudio must be installed at the OS level — it cannot be pip-installed
    inside the HA container because it requires gcc and ALSA dev headers.

    On Debian/Raspberry Pi OS:
        sudo apt-get install python3-alsaaudio

    On Home Assistant OS (haos): install the 'SSH & Web Terminal' add-on,
    then run:  apk add py3-alsaaudio
    """
    try:
        import alsaaudio  # noqa: F401
    except ImportError:
        _LOGGER.warning(
            "pyalsaaudio is not installed — audio streaming will not work. "
            "Install it at the OS level: 'sudo apt-get install python3-alsaaudio' "
            "(Debian/Ubuntu) or 'apk add py3-alsaaudio' (Alpine/HA OS)."
        )

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bluetooth Audio Server from a config entry."""
    _check_system_deps()
    adapter = entry.data.get(CONF_SOURCE_ADAPTER, "hci0")

    coordinator = BluetoothAudioCoordinator(hass, adapter)
    await coordinator.async_setup()

    # Outputs added via the Options flow are stored in entry.options;
    # outputs from the initial config flow are in entry.data.
    # Merge both, with options taking precedence on id collision.
    data_outputs    = entry.data.get(CONF_OUTPUTS, [])
    options_outputs = entry.options.get(CONF_OUTPUTS, [])
    seen: set[str] = set()
    outputs: list[dict] = []
    for out in options_outputs + data_outputs:
        if out["id"] not in seen:
            seen.add(out["id"])
            outputs.append(out)

    for output_cfg in outputs:
        if output_cfg.get("type") == "esp32":
            host, port = output_cfg["address"].split(":")
            await coordinator.async_add_esp32_output(
                output_id=output_cfg["id"],
                display_name=output_cfg["name"],
                host=host,
                port=int(port),
                delay_ms=output_cfg.get("delay_ms", 0),
            )
        else:
            await coordinator.async_add_bluetooth_output(
                output_id=output_cfg["id"],
                display_name=output_cfg["name"],
                mac_address=output_cfg["address"],
                delay_ms=output_cfg.get("delay_ms", 0),
            )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    async_register_services(hass, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info("Bluetooth Audio Server entry %s set up successfully", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: BluetoothAudioCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
        async_unregister_services(hass)
        _LOGGER.info("Bluetooth Audio Server entry %s unloaded", entry.entry_id)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
