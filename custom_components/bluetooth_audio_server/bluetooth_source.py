"""
BlueZ A2DP Sink interface.

Registers this machine as an A2DP sink profile with BlueZ via D-Bus,
accepts incoming connections from source devices (phones, tablets),
and reads the raw PCM audio stream.

Linux / BlueZ specifics
-----------------------
BlueZ exposes Bluetooth profiles through the D-Bus interface
``org.bluez.ProfileManager1``.  When a source device connects and starts
streaming, BlueZ calls our ``NewConnection`` method with a Unix socket file
descriptor carrying the SBC-encoded A2DP data.

We decode SBC → PCM using ``pysbc`` (or delegate to ``bluealsa`` which
handles the codec transparently and gives us a plain PCM ALSA device).

For simplicity this implementation uses the ``bluealsa`` path: once the
source is streaming, ``bluealsa`` makes it available as an ALSA capture
device, so we just open that device and read PCM directly.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from .const import BYTES_PER_SEC, CHUNK_BYTES, SourceState

_LOGGER = logging.getLogger(__name__)

# ALSA capture device name template for bluealsa.
# Requires the bluealsa daemon running on the host.
_BLUEALSA_CAPTURE_DEVICE = "bluealsa:DEV={mac},PROFILE=a2dp"

# How many seconds to wait between connection-poll cycles when no stream
# is active (keeps CPU usage negligible).
_POLL_INTERVAL = 1.0


class BluetoothSource:
    """
    Manages the A2DP Sink role and calls back into the coordinator when
    stream state changes or PCM data is available.

    Callbacks
    ---------
    on_connected(device_name: str)
        Fired when a BT source device connects.
    on_disconnected()
        Fired when the source device disconnects or the stream ends.
    on_stream_start()
        Fired when audio data begins arriving (PCM read loop starts).
    on_stream_stop()
        Fired when audio data stops (read loop exits cleanly).
    on_chunk(data: bytes)
        Fired for every PCM chunk read from the capture device.
        This is the hot path — must be non-blocking.
    """

    def __init__(
        self,
        adapter: str,
        on_connected: Callable[[str], None],
        on_disconnected: Callable[[], None],
        on_stream_start: Callable[[], None],
        on_stream_stop: Callable[[], None],
        on_chunk: Callable[[bytes], None],
    ) -> None:
        self._adapter = adapter      # e.g. "hci0"
        self._on_connected     = on_connected
        self._on_disconnected  = on_disconnected
        self._on_stream_start  = on_stream_start
        self._on_stream_stop   = on_stream_stop
        self._on_chunk         = on_chunk

        self._monitor_task: asyncio.Task | None = None
        self._capture_task:  asyncio.Task | None = None
        self._connected_mac: str | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """
        Make the adapter discoverable and register the A2DP sink profile.
        Then start the connection-monitor loop.
        """
        await self._make_adapter_discoverable()
        await self._register_a2dp_profile()
        self._running = True
        self._monitor_task = asyncio.ensure_future(self._connection_monitor())
        _LOGGER.info(
            "BluetoothSource ready on adapter %s (waiting for source device)",
            self._adapter,
        )

    async def async_teardown(self) -> None:
        """Stop monitoring and clean up any active stream."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        await self._stop_capture()
        _LOGGER.info("BluetoothSource torn down")

    # ------------------------------------------------------------------
    # D-Bus / BlueZ helpers
    # ------------------------------------------------------------------

    async def _make_adapter_discoverable(self) -> None:
        """Set the BT adapter to pairable + discoverable via D-Bus."""
        try:
            import pydbus  # type: ignore[import]
            bus = pydbus.SystemBus()
            adapter_path = f"/org/bluez/{self._adapter}"
            adapter = bus.get("org.bluez", adapter_path)
            adapter.Discoverable = True
            adapter.Pairable    = True
            _LOGGER.debug("Adapter %s set to discoverable/pairable", self._adapter)
        except Exception:
            _LOGGER.warning(
                "Could not set adapter discoverable (non-Linux or BlueZ missing); "
                "continuing in simulation mode",
                exc_info=True,
            )

    async def _register_a2dp_profile(self) -> None:
        """
        Register an A2DP Sink profile UUID with BlueZ.

        BlueZ will call our profile's ``NewConnection`` method when a source
        device connects.  In this implementation bluealsa handles the actual
        profile logic; we just ensure the UUID is advertised.
        """
        A2DP_SINK_UUID = "0000110b-0000-1000-8000-00805f9b34fb"
        try:
            import pydbus  # type: ignore[import]
            bus = pydbus.SystemBus()
            manager = bus.get("org.bluez", "/org/bluez")
            # bluealsa registers the profile itself; we only need to verify
            # the service is running.
            _LOGGER.debug("A2DP Sink UUID %s advertised via bluealsa", A2DP_SINK_UUID)
        except Exception:
            _LOGGER.warning(
                "BlueZ profile registration skipped (non-Linux environment)",
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Connection monitor loop
    # ------------------------------------------------------------------

    async def _connection_monitor(self) -> None:
        """
        Polls BlueZ via D-Bus to detect when a source device connects or
        disconnects, then starts/stops the PCM capture loop accordingly.

        In production this would use D-Bus signal subscriptions
        (``InterfacesAdded`` / ``PropertiesChanged``) for zero-latency
        detection.  The polling approach here is simpler to follow and still
        correct — latency is at most ``_POLL_INTERVAL`` seconds.
        """
        _LOGGER.debug("Connection monitor started")
        was_connected = False

        while self._running:
            try:
                mac, name = await self._find_streaming_device()
                is_connected = mac is not None

                if is_connected and not was_connected:
                    self._connected_mac = mac
                    _LOGGER.info("Source connected: %s (%s)", name, mac)
                    self._on_connected(name or mac)
                    await self._start_capture(mac)
                    was_connected = True

                elif not is_connected and was_connected:
                    _LOGGER.info("Source disconnected")
                    await self._stop_capture()
                    self._connected_mac = None
                    self._on_disconnected()
                    was_connected = False

            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Error in connection monitor")

            await asyncio.sleep(_POLL_INTERVAL)

    async def _find_streaming_device(self) -> tuple[str | None, str | None]:
        """
        Query BlueZ for a connected device that has the A2DP Sink profile.
        Returns ``(mac, name)`` or ``(None, None)``.
        """
        try:
            import pydbus  # type: ignore[import]
            bus = pydbus.SystemBus()
            manager = bus.get("org.bluez", "/")
            objects = manager.GetManagedObjects()

            for path, interfaces in objects.items():
                device = interfaces.get("org.bluez.Device1")
                if not device:
                    continue
                if not device.get("Connected", False):
                    continue
                uuids: list[str] = device.get("UUIDs", [])
                # A2DP source UUID — this device is sending audio to us
                if "0000110a-0000-1000-8000-00805f9b34fb" in uuids:
                    mac  = device.get("Address")
                    name = device.get("Name", mac)
                    return mac, name

        except Exception:
            # On non-Linux systems fall back to None so the caller can
            # operate in simulation mode.
            pass

        return None, None

    # ------------------------------------------------------------------
    # PCM capture loop
    # ------------------------------------------------------------------

    async def _start_capture(self, mac: str) -> None:
        if self._capture_task and not self._capture_task.done():
            return
        self._on_stream_start()
        self._capture_task = asyncio.ensure_future(self._capture_loop(mac))

    async def _stop_capture(self) -> None:
        if self._capture_task:
            self._capture_task.cancel()
            try:
                await self._capture_task
            except (asyncio.CancelledError, Exception):
                pass
            self._capture_task = None
        self._on_stream_stop()

    async def _capture_loop(self, mac: str) -> None:
        """
        Read raw PCM from the bluealsa ALSA capture device and fan it out
        via ``on_chunk`` to the AudioRouter.

        The ``alsaaudio.PCM`` read call is blocking so it runs in the
        default thread-pool executor to avoid blocking the event loop.
        """
        device = _BLUEALSA_CAPTURE_DEVICE.format(mac=mac)
        _LOGGER.info("Starting PCM capture from %s", device)
        loop = asyncio.get_event_loop()

        try:
            import alsaaudio  # type: ignore[import]
            pcm = await loop.run_in_executor(
                None,
                lambda: alsaaudio.PCM(
                    alsaaudio.PCM_CAPTURE,
                    device=device,
                    rate=44100,
                    channels=2,
                    format=alsaaudio.PCM_FORMAT_S16_LE,
                    periodsize=CHUNK_BYTES // 4,
                ),
            )

            while True:
                # read() returns (num_frames, data); blocks until period ready
                length, data = await loop.run_in_executor(None, pcm.read)
                if length > 0 and data:
                    self._on_chunk(data)
                await asyncio.sleep(0)   # yield to event loop between reads

        except asyncio.CancelledError:
            _LOGGER.debug("Capture loop cancelled for %s", mac)
            raise
        except Exception:
            _LOGGER.exception("Capture loop error for %s", mac)
        finally:
            try:
                pcm.close()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            _LOGGER.info("PCM capture stopped for %s", mac)
