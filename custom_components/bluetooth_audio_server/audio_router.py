"""
Core audio engine: stream capture, duplication, per-output delay buffer,
and forwarding to output sinks.

Delay Buffer Design
-------------------
Every PCM chunk is wrapped in a TimestampedChunk that records the monotonic
time it was captured.  Each output's worker task reads from its own asyncio
queue and computes:

    wait = (chunk.captured_at + delay_seconds) - time.monotonic()

If wait > 0 the worker sleeps that long before forwarding the chunk.
This means:
  - Increasing delay_ms queues more future chunks without flushing.
  - Decreasing delay_ms causes the worker to immediately drain the backlog
    until timing catches up.
  - All outputs share the same producer; their clocks are independent.
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .const import (
    BYTES_PER_SEC,
    CHUNK_BYTES,
    DEFAULT_DELAY_MS,
    MAX_DELAY_MS,
    MIN_DELAY_MS,
    OutputState,
)

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

# Maximum chunks buffered per output before we start dropping.
# At CHUNK_BYTES=4096 and ~23 ms/chunk this is ~46 seconds of audio.
_MAX_QUEUE_SIZE = 2000


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TimestampedChunk:
    """PCM audio chunk tagged with its capture time."""
    data: bytes
    captured_at: float   # time.monotonic() at capture


@dataclass
class OutputConfig:
    """Mutable runtime state for one audio output."""
    output_id: str
    display_name: str
    output_type: str             # OUTPUT_TYPE_BLUETOOTH | OUTPUT_TYPE_ESP32
    address: str                 # BT MAC or ESP32 "host:port"
    state: OutputState = OutputState.IDLE
    volume: float = 1.0          # 0.0 – 1.0
    delay_ms: int = DEFAULT_DELAY_MS


# ---------------------------------------------------------------------------
# Abstract output sink interface
# ---------------------------------------------------------------------------

class OutputSink(ABC):
    """Transport layer for one audio destination."""

    @abstractmethod
    async def async_connect(self) -> None:
        """Open the connection to the sink device."""

    @abstractmethod
    async def async_send(self, data: bytes) -> None:
        """Forward one PCM chunk (already volume-scaled) to the device."""

    @abstractmethod
    async def async_disconnect(self) -> None:
        """Tear down the connection gracefully."""


class BluetoothSink(OutputSink):
    """
    Writes PCM to a Bluetooth A2DP speaker.

    Uses the ALSA bluealsa virtual device (e.g. ``bluealsa:DEV=XX:XX:XX:XX:XX:XX``).
    Requires ``pyalsaaudio`` (Linux only).
    """

    def __init__(self, mac_address: str) -> None:
        self._mac = mac_address
        self._pcm = None

    async def async_connect(self) -> None:
        import alsaaudio  # type: ignore[import]
        device = f"bluealsa:DEV={self._mac}"
        self._pcm = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: alsaaudio.PCM(
                alsaaudio.PCM_PLAYBACK,
                device=device,
                rate=44100,
                channels=2,
                format=alsaaudio.PCM_FORMAT_S16_LE,
                periodsize=CHUNK_BYTES // 4,
            ),
        )
        _LOGGER.debug("BluetoothSink connected: %s", self._mac)

    async def async_send(self, data: bytes) -> None:
        if self._pcm is None:
            return
        await asyncio.get_event_loop().run_in_executor(None, self._pcm.write, data)

    async def async_disconnect(self) -> None:
        if self._pcm is not None:
            await asyncio.get_event_loop().run_in_executor(None, self._pcm.close)
            self._pcm = None
        _LOGGER.debug("BluetoothSink disconnected: %s", self._mac)


class ESP32Sink(OutputSink):
    """
    Streams raw PCM to an ESP32 satellite over UDP.

    The ESP32 firmware is expected to listen on a fixed UDP port and play
    the PCM it receives directly via I2S.  Packet loss is acceptable
    (live audio; retransmission would worsen latency).
    """

    def __init__(self, host: str, port: int = 5005) -> None:
        self._host = host
        self._port = port
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: asyncio.BaseProtocol | None = None

    async def async_connect(self) -> None:
        loop = asyncio.get_event_loop()
        self._transport, self._protocol = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            remote_addr=(self._host, self._port),
        )
        _LOGGER.debug("ESP32Sink connected: %s:%s", self._host, self._port)

    async def async_send(self, data: bytes) -> None:
        if self._transport and not self._transport.is_closing():
            self._transport.sendto(data)

    async def async_disconnect(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None
        _LOGGER.debug("ESP32Sink disconnected: %s:%s", self._host, self._port)


# ---------------------------------------------------------------------------
# Audio Router
# ---------------------------------------------------------------------------

class AudioRouter:
    """
    Receives raw PCM from the A2DP sink, duplicates it across all active
    outputs, and manages per-output delay buffers and volume scaling.
    """

    def __init__(self, on_output_state_changed: callable) -> None:
        """
        Args:
            on_output_state_changed: Callback ``(output_id, OutputState)``
                invoked whenever an output transitions state so that HA
                entities can refresh their state.
        """
        self._on_state_changed = on_output_state_changed
        self._outputs: dict[str, OutputConfig] = {}
        self._sinks: dict[str, OutputSink] = {}
        self._queues: dict[str, asyncio.Queue[TimestampedChunk | None]] = {}
        self._workers: dict[str, asyncio.Task] = {}
        self._capture_task: asyncio.Task | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Public API (called by the coordinator)
    # ------------------------------------------------------------------

    async def async_add_output(self, config: OutputConfig, sink: OutputSink) -> None:
        """Register a new output and start its stream-worker task."""
        output_id = config.output_id
        if output_id in self._outputs:
            _LOGGER.warning("Output %s already registered; ignoring", output_id)
            return

        self._outputs[output_id] = config
        self._sinks[output_id] = sink
        self._queues[output_id] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)

        try:
            await sink.async_connect()
        except Exception:
            _LOGGER.exception("Failed to connect sink for %s", output_id)
            self._set_state(output_id, OutputState.UNAVAILABLE)
            return

        self._set_state(output_id, OutputState.IDLE)
        _LOGGER.info("Output registered: %s (%s)", config.display_name, output_id)

    async def async_remove_output(self, output_id: str) -> None:
        """Unregister an output and clean up its resources."""
        await self._stop_worker(output_id)
        sink = self._sinks.pop(output_id, None)
        if sink:
            await sink.async_disconnect()
        self._outputs.pop(output_id, None)
        self._queues.pop(output_id, None)
        _LOGGER.info("Output removed: %s", output_id)

    async def async_route_output(self, output_id: str) -> None:
        """Start routing audio to an output (spawns stream-worker)."""
        if output_id not in self._outputs:
            raise ValueError(f"Unknown output: {output_id}")

        config = self._outputs[output_id]
        if config.state in (OutputState.ROUTING, OutputState.PLAYING):
            _LOGGER.debug("Output %s already active", output_id)
            return

        self._set_state(output_id, OutputState.ROUTING)
        self._workers[output_id] = asyncio.ensure_future(
            self._stream_worker(output_id)
        )

    async def async_stop_output(self, output_id: str) -> None:
        """Stop routing to one output."""
        await self._stop_worker(output_id)
        if output_id in self._outputs:
            self._set_state(output_id, OutputState.IDLE)

    async def async_stop_all(self) -> None:
        """Stop all active outputs simultaneously."""
        await asyncio.gather(
            *(self.async_stop_output(oid) for oid in list(self._outputs)),
            return_exceptions=True,
        )

    def set_volume(self, output_id: str, volume: float) -> None:
        """Update volume (0.0–1.0) for an output. Takes effect on next chunk."""
        volume = max(0.0, min(1.0, volume))
        if output_id in self._outputs:
            self._outputs[output_id].volume = volume

    def set_delay(self, output_id: str, delay_ms: int) -> None:
        """
        Update the delay for an output.

        The change takes effect immediately on the *next* chunk dequeued by
        the worker — no flush required.  Increasing delay causes the worker
        to sleep longer before forwarding; decreasing it causes the worker to
        drain the backlog without sleeping until timing realigns.
        """
        delay_ms = max(MIN_DELAY_MS, min(MAX_DELAY_MS, delay_ms))
        if output_id in self._outputs:
            self._outputs[output_id].delay_ms = delay_ms
            _LOGGER.debug("Delay for %s set to %d ms", output_id, delay_ms)

    # ------------------------------------------------------------------
    # Called by BluetoothSource when it has a PCM chunk ready
    # ------------------------------------------------------------------

    def distribute_chunk(self, data: bytes) -> None:
        """
        Fan-out one PCM chunk to every active output's delay queue.

        Called from the capture coroutine on the event loop — must be fast
        (no blocking I/O).
        """
        chunk = TimestampedChunk(data=data, captured_at=time.monotonic())
        for output_id, queue in self._queues.items():
            config = self._outputs.get(output_id)
            if config and config.state in (OutputState.ROUTING, OutputState.PLAYING):
                try:
                    queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    _LOGGER.warning(
                        "Buffer full for %s — dropping chunk (delay too large?)",
                        output_id,
                    )

    # ------------------------------------------------------------------
    # Stream worker — one per active output
    # ------------------------------------------------------------------

    async def _stream_worker(self, output_id: str) -> None:
        """
        Pulls chunks from the delay queue and forwards them to the sink.

        Delay logic
        ~~~~~~~~~~~
        Each chunk carries ``captured_at`` (monotonic time of capture).
        The worker computes the moment this chunk *should* play:

            play_at = captured_at + delay_seconds

        If ``play_at`` is in the future the worker awaits the difference.
        If it is in the past (e.g. after a delay decrease) the chunk is
        forwarded immediately without sleeping, draining the backlog fast.
        """
        queue = self._queues[output_id]
        sink = self._sinks[output_id]
        config = self._outputs[output_id]

        self._set_state(output_id, OutputState.PLAYING)
        _LOGGER.info("Stream worker started for %s", output_id)

        try:
            while True:
                chunk: TimestampedChunk | None = await queue.get()

                if chunk is None:
                    # Sentinel value — worker should stop.
                    break

                # --- Delay compensation ---
                delay_sec = config.delay_ms / 1000.0
                play_at   = chunk.captured_at + delay_sec
                wait_sec  = play_at - time.monotonic()
                if wait_sec > 0:
                    await asyncio.sleep(wait_sec)

                # --- Volume scaling (integer PCM 16-bit, little-endian) ---
                audio = _apply_volume(chunk.data, config.volume)

                # --- Forward to sink ---
                try:
                    await sink.async_send(audio)
                except Exception:
                    _LOGGER.exception("Sink send failed for %s", output_id)

        except asyncio.CancelledError:
            _LOGGER.debug("Stream worker cancelled for %s", output_id)
        finally:
            self._set_state(output_id, OutputState.IDLE)
            _LOGGER.info("Stream worker stopped for %s", output_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _stop_worker(self, output_id: str) -> None:
        """Cancel worker task and drain its queue."""
        task = self._workers.pop(output_id, None)
        if task and not task.done():
            # Enqueue sentinel so the worker exits its await cleanly.
            queue = self._queues.get(output_id)
            if queue:
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        # Drain leftover items so the queue is clean for next use.
        queue = self._queues.get(output_id)
        if queue:
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

    def _set_state(self, output_id: str, state: OutputState) -> None:
        config = self._outputs.get(output_id)
        if config and config.state != state:
            config.state = state
            self._on_state_changed(output_id, state)


# ---------------------------------------------------------------------------
# PCM volume scaling helper
# ---------------------------------------------------------------------------

def _apply_volume(data: bytes, volume: float) -> bytes:
    """
    Scale 16-bit little-endian PCM samples by ``volume`` (0.0–1.0).

    Uses the ``audioop`` stdlib module for performance.  Falls back to a
    pure-Python path if unavailable (Python 3.13+ removed audioop).
    """
    if volume == 1.0:
        return data

    try:
        import audioop  # type: ignore[import]   # removed in Py3.13
        # audioop.mul works on signed 16-bit samples; width=2
        return audioop.mul(data, 2, volume)
    except ImportError:
        pass

    # Pure-Python fallback (slower but dependency-free)
    import array
    samples = array.array("h", data)        # signed short
    for i, s in enumerate(samples):
        samples[i] = int(s * volume)
    return bytes(samples)
