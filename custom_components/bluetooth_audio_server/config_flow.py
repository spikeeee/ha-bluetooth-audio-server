"""Config flow for Bluetooth Audio Server."""
from __future__ import annotations

import logging
import re

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_OUTPUTS,
    CONF_SOURCE_ADAPTER,
    DEFAULT_DELAY_MS,
    DOMAIN,
    MAX_DELAY_MS,
    MIN_DELAY_MS,
    OUTPUT_TYPE_BLUETOOTH,
    OUTPUT_TYPE_ESP32,
)

_LOGGER = logging.getLogger(__name__)

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

_OUTPUT_TYPE_OPTIONS = {
    OUTPUT_TYPE_BLUETOOTH: "Bluetooth Speaker (A2DP / bluealsa)",
    OUTPUT_TYPE_ESP32:     "ESP32 Satellite (raw PCM over UDP)",
}


def _slug(name: str) -> str:
    """Convert a display name to a safe entity-id fragment."""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


async def _detect_bt_adapters() -> list[str]:
    """Return adapter names found in /sys/class/bluetooth, or ['hci0']."""
    import os
    try:
        path = "/sys/class/bluetooth"
        if os.path.exists(path):
            found = sorted(os.listdir(path))
            if found:
                return found
    except Exception:
        pass
    return ["hci0"]


# ─── Config flow ─────────────────────────────────────────────────────────────

class BluetoothAudioConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Two-step config flow:
      1. user        — pick the BT adapter
      2. add_output  — add one or more speaker outputs (can be skipped)
    """

    VERSION = 1

    def __init__(self) -> None:
        self._adapter: str = "hci0"
        self._outputs: list[dict] = []

    # ── Step 1: adapter ──────────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        adapters = await _detect_bt_adapters()

        if user_input is not None:
            self._adapter = user_input[CONF_SOURCE_ADAPTER].strip()

            # Prevent the same adapter being configured twice.
            await self.async_set_unique_id(self._adapter)
            self._abort_if_unique_id_configured()

            return await self.async_step_add_output()

        # Show adapter as a dropdown when multiple are detected.
        if len(adapters) > 1:
            adapter_schema = vol.In(adapters)
        else:
            adapter_schema = str

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_SOURCE_ADAPTER, default=adapters[0]): adapter_schema,
            }),
            errors=errors,
            description_placeholders={"adapters": ", ".join(adapters)},
        )

    # ── Step 2: add output (repeatable) ──────────────────────────────────────

    async def async_step_add_output(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            name    = user_input.get("name", "").strip()
            skip    = user_input.get("skip_and_finish", False)

            # Empty name or explicit skip → finish without adding this entry.
            if skip or not name:
                return self._finish()

            out_type = user_input["type"]
            address  = user_input.get("address", "").strip()

            # Validate the address for the chosen output type.
            if out_type == OUTPUT_TYPE_BLUETOOTH:
                if not _MAC_RE.match(address):
                    errors["address"] = "invalid_mac"
            else:
                # ESP32: append default port if omitted.
                if address and ":" not in address:
                    address = f"{address}:5005"
                if not address:
                    errors["address"] = "address_required"

            if not errors:
                self._outputs.append({
                    "id":       f"media_player.bt_output_{_slug(name)}",
                    "name":     name,
                    "type":     out_type,
                    "address":  address,
                    "delay_ms": int(user_input.get("delay_ms", DEFAULT_DELAY_MS)),
                })

                if user_input.get("add_another", False):
                    # Loop back to add another output.
                    return await self.async_step_add_output()

                return self._finish()

        added_so_far = len(self._outputs)

        return self.async_show_form(
            step_id="add_output",
            data_schema=vol.Schema({
                vol.Optional("name"):    str,
                vol.Required("type", default=OUTPUT_TYPE_BLUETOOTH): vol.In(_OUTPUT_TYPE_OPTIONS),
                vol.Optional("address", default=""): str,
                vol.Optional("delay_ms", default=DEFAULT_DELAY_MS): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_DELAY_MS, max=MAX_DELAY_MS),
                ),
                vol.Optional("add_another",      default=False): bool,
                vol.Optional("skip_and_finish",  default=added_so_far > 0): bool,
            }),
            errors=errors,
            description_placeholders={"count": str(added_so_far)},
        )

    def _finish(self) -> config_entries.FlowResult:
        return self.async_create_entry(
            title=f"Bluetooth Audio — {self._adapter}",
            data={
                CONF_SOURCE_ADAPTER: self._adapter,
                CONF_OUTPUTS:        self._outputs,
            },
        )

    # ── Options flow hook ─────────────────────────────────────────────────────

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> BluetoothAudioOptionsFlow:
        return BluetoothAudioOptionsFlow(config_entry)


# ─── Options flow ─────────────────────────────────────────────────────────────

class BluetoothAudioOptionsFlow(config_entries.OptionsFlow):
    """
    Lets the user add more outputs after the initial setup.

    Each save appends one output and triggers an integration reload
    (handled by the update_listener in __init__.py).
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        # Merge: options outputs take precedence over data outputs (they are
        # the post-install additions). Combine both to preserve everything.
        data_outputs    = config_entry.data.get(CONF_OUTPUTS, [])
        options_outputs = config_entry.options.get(CONF_OUTPUTS, [])
        # De-duplicate by entity id, options win on collision.
        seen: set[str] = set()
        merged: list[dict] = []
        for out in options_outputs + data_outputs:
            if out["id"] not in seen:
                seen.add(out["id"])
                merged.append(out)
        self._outputs: list[dict] = merged

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        return await self.async_step_add_output()

    async def async_step_add_output(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            name     = user_input.get("name", "").strip()
            out_type = user_input["type"]
            address  = user_input.get("address", "").strip()

            if not name:
                errors["name"] = "name_required"

            if out_type == OUTPUT_TYPE_BLUETOOTH:
                if not _MAC_RE.match(address):
                    errors["address"] = "invalid_mac"
            else:
                if not address:
                    errors["address"] = "address_required"
                elif ":" not in address:
                    address = f"{address}:5005"

            if not errors:
                self._outputs.append({
                    "id":       f"media_player.bt_output_{_slug(name)}",
                    "name":     name,
                    "type":     out_type,
                    "address":  address,
                    "delay_ms": int(user_input.get("delay_ms", DEFAULT_DELAY_MS)),
                })
                return self.async_create_entry(
                    title="",
                    data={CONF_OUTPUTS: self._outputs},
                )

        return self.async_show_form(
            step_id="add_output",
            data_schema=vol.Schema({
                vol.Required("name"):    str,
                vol.Required("type", default=OUTPUT_TYPE_BLUETOOTH): vol.In(_OUTPUT_TYPE_OPTIONS),
                vol.Required("address"): str,
                vol.Optional("delay_ms", default=DEFAULT_DELAY_MS): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_DELAY_MS, max=MAX_DELAY_MS),
                ),
            }),
            errors=errors,
        )
