/**
 * bluetooth-audio-card.js
 * Custom Lovelace card for the Bluetooth Audio Server integration.
 *
 * Installation
 * ────────────
 * 1. Copy this file to <ha-config>/www/bluetooth-audio-card.js
 * 2. Add as a Lovelace resource (Settings → Dashboards → Resources):
 *      URL:  /local/bluetooth-audio-card.js
 *      Type: JavaScript module
 *
 * Card YAML
 * ─────────
 * type: custom:bluetooth-audio-card
 * title: "Music Server"
 * source_sensor: sensor.bt_audio_source_state
 * source_device_sensor: sensor.bt_audio_source_device
 * outputs:
 *   - entity: media_player.bt_output_living_room
 *     name: Living Room
 *   - entity: media_player.bt_output_bedroom
 *     name: Bedroom
 *   - entity: media_player.bt_output_esp32_kitchen
 *     name: Kitchen
 */

import {
  LitElement,
  html,
  css,
  nothing,
} from "https://cdn.jsdelivr.net/gh/lit/dist@3/core/lit-core.min.js";

// ─── Helpers ────────────────────────────────────────────────────────────────

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

const debounce = (fn, ms) => {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
};

/** CSS color for each integration state value. */
const STATE_COLOR = {
  playing:      "#32d74b",
  buffering:    "#ff9f0a",
  idle:         "rgba(255,255,255,0.28)",
  unavailable:  "#ff3b30",
  streaming:    "#32d74b",
  connected:    "#ff9f0a",
  connecting:   "#ff9f0a",
  disconnected: "rgba(255,255,255,0.22)",
};

const STATE_LABEL = {
  playing:      "Playing",
  buffering:    "Buffering",
  idle:         "Idle",
  unavailable:  "Unavailable",
  streaming:    "Streaming",
  connected:    "Connected",
  connecting:   "Connecting…",
  disconnected: "Disconnected",
};

// ─── bt-slider-control ──────────────────────────────────────────────────────
//
// Reusable slider + numeric input pair.
// Emits a `bt-change` CustomEvent with `detail = new numeric value`.
// Debounces upward events so callers can safely call services on every change.

class BtSliderControl extends LitElement {
  static properties = {
    icon:  {},
    value: { type: Number },
    min:   { type: Number },
    max:   { type: Number },
    step:  { type: Number },
    unit:  {},
    _val:  { state: true },   // internal tracked value
  };

  static styles = css`
    :host { display: block; padding: 2px 0; }

    .row {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .icon {
      font-size: 15px;
      width: 18px;
      text-align: center;
      flex-shrink: 0;
      opacity: 0.65;
      user-select: none;
    }

    /* ── Range slider ── */
    input[type="range"] {
      -webkit-appearance: none;
      flex: 1;
      height: 4px;
      border-radius: 2px;
      outline: none;
      cursor: pointer;
      /* filled track via gradient; --pct is set inline */
      background: linear-gradient(
        to right,
        var(--primary-color, #4a90d9) 0%,
        var(--primary-color, #4a90d9) var(--pct, 0%),
        rgba(255,255,255,0.13) var(--pct, 0%),
        rgba(255,255,255,0.13) 100%
      );
    }
    input[type="range"]::-webkit-slider-thumb {
      -webkit-appearance: none;
      width: 16px;
      height: 16px;
      border-radius: 50%;
      background: #fff;
      box-shadow: 0 1px 5px rgba(0,0,0,0.55);
      cursor: grab;
      transition: transform 0.1s ease, box-shadow 0.1s ease;
    }
    input[type="range"]::-webkit-slider-thumb:active {
      cursor: grabbing;
      transform: scale(1.3);
      box-shadow: 0 2px 10px rgba(0,0,0,0.65);
    }
    input[type="range"]:focus-visible { outline: 2px solid var(--primary-color, #4a90d9); border-radius: 2px; }

    /* ── Number input ── */
    .num-wrap {
      display: flex;
      align-items: center;
      gap: 3px;
      flex-shrink: 0;
    }
    input[type="number"] {
      width: 46px;
      padding: 4px 6px;
      background: rgba(255,255,255,0.07);
      border: 1px solid rgba(255,255,255,0.11);
      border-radius: 7px;
      color: var(--primary-text-color, #fff);
      font-size: 12px;
      font-family: inherit;
      text-align: right;
      outline: none;
      transition: border-color 0.15s;
      -moz-appearance: textfield;
    }
    input[type="number"]:focus { border-color: var(--primary-color, #4a90d9); }
    input[type="number"]::-webkit-inner-spin-button,
    input[type="number"]::-webkit-outer-spin-button { -webkit-appearance: none; }

    .unit {
      font-size: 11px;
      color: var(--secondary-text-color, rgba(255,255,255,0.45));
      min-width: 16px;
      user-select: none;
    }
  `;

  constructor() {
    super();
    this.icon = "🔊"; this.min = 0; this.max = 100;
    this.step = 1; this.unit = ""; this.value = 50; this._val = 50;
    this._dragging = false;
  }

  willUpdate(changed) {
    // Sync _val from the external value prop only when not actively dragging.
    if (changed.has("value") && !this._dragging) {
      this._val = this.value;
    }
  }

  _pct() {
    return `${((this._val - this.min) / (this.max - this.min)) * 100}%`;
  }

  _emit(v) {
    this._val = v;
    this.dispatchEvent(new CustomEvent("bt-change", {
      detail: v, bubbles: true, composed: true,
    }));
  }

  _onSliderInput(e) {
    this._dragging = true;
    this._emit(+e.target.value);
  }

  _onSliderEnd() { this._dragging = false; }

  _onNumberChange(e) {
    this._emit(clamp(+e.target.value, this.min, this.max));
  }

  render() {
    return html`
      <div class="row">
        <span class="icon">${this.icon}</span>
        <input
          type="range"
          min=${this.min} max=${this.max} step=${this.step}
          .value=${String(this._val)}
          style="--pct:${this._pct()}"
          @input=${this._onSliderInput}
          @pointerup=${this._onSliderEnd}
          @touchend=${this._onSliderEnd}
        />
        <div class="num-wrap">
          <input
            type="number"
            min=${this.min} max=${this.max} step=${this.step}
            .value=${String(this._val)}
            @change=${this._onNumberChange}
          />
          <span class="unit">${this.unit}</span>
        </div>
      </div>
    `;
  }
}
customElements.define("bt-slider-control", BtSliderControl);


// ─── bt-confirm-dialog ──────────────────────────────────────────────────────
//
// Modal confirmation overlay.  Emits `bt-cancel` or `bt-confirm`.
// Uses the `open` boolean attribute so CSS can target `:host([open])`.

class BtConfirmDialog extends LitElement {
  static properties = {
    open:    { type: Boolean, reflect: true },
    message: {},
  };

  static styles = css`
    :host          { display: none; }
    :host([open])  { display: block; }

    .backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.55);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 9999;
      backdrop-filter: blur(3px);
      animation: fade-in 0.15s ease forwards;
    }
    @keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }

    .dialog {
      background: var(--card-background-color, #2c2c2e);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 18px;
      padding: 28px 24px 20px;
      width: 280px;
      text-align: center;
      box-shadow: 0 24px 64px rgba(0,0,0,0.55);
      animation: slide-up 0.2s cubic-bezier(.34,1.4,.64,1) forwards;
    }
    @keyframes slide-up {
      from { transform: translateY(18px) scale(0.97); opacity: 0; }
      to   { transform: translateY(0)    scale(1);    opacity: 1; }
    }

    .dialog-icon { font-size: 36px; margin-bottom: 10px; }

    .dialog-title {
      font-size: 17px;
      font-weight: 700;
      color: var(--primary-text-color, #fff);
      margin-bottom: 6px;
    }
    .dialog-message {
      font-size: 13px;
      line-height: 1.5;
      color: var(--secondary-text-color, rgba(255,255,255,0.55));
      margin-bottom: 22px;
    }

    .dialog-actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    button {
      padding: 12px;
      border: none;
      border-radius: 11px;
      font-size: 15px;
      font-weight: 600;
      font-family: inherit;
      cursor: pointer;
      transition: opacity 0.12s, transform 0.1s;
    }
    button:active { opacity: 0.72; transform: scale(0.96); }
    .btn-cancel  { background: rgba(255,255,255,0.09); color: var(--primary-text-color, #fff); }
    .btn-confirm { background: #ff3b30; color: #fff; }
  `;

  _cancel()  { this.dispatchEvent(new CustomEvent("bt-cancel",  { bubbles: true, composed: true })); }
  _confirm() { this.dispatchEvent(new CustomEvent("bt-confirm", { bubbles: true, composed: true })); }

  render() {
    if (!this.open) return nothing;
    return html`
      <div class="backdrop" @click=${this._cancel}>
        <div class="dialog" @click=${e => e.stopPropagation()}>
          <div class="dialog-icon">⏹</div>
          <div class="dialog-title">Stop Output?</div>
          <div class="dialog-message">${this.message}</div>
          <div class="dialog-actions">
            <button class="btn-cancel"  @click=${this._cancel}>Cancel</button>
            <button class="btn-confirm" @click=${this._confirm}>Stop</button>
          </div>
        </div>
      </div>
    `;
  }
}
customElements.define("bt-confirm-dialog", BtConfirmDialog);


// ─── bt-output-card ──────────────────────────────────────────────────────────
//
// Renders one speaker output:
//   • Header row: name, state badge, route / stop / settings buttons
//   • Volume slider (always visible)
//   • Settings drawer (collapsible): delay slider
//
// Calls hass.callService for all mutations; debounces slider events (300 ms
// for volume, 400 ms for delay) to avoid saturating the HA WebSocket.

class BtOutputCard extends LitElement {
  static properties = {
    hass:           { attribute: false },
    entity:         {},
    name:           {},
    _settingsOpen:  { state: true },
    _confirmOpen:   { state: true },
  };

  static styles = css`
    :host { display: block; }

    /* ── Card shell ── */
    .card {
      background: rgba(255,255,255,0.038);
      border: 1px solid rgba(255,255,255,0.07);
      border-radius: 14px;
      margin-bottom: 10px;
      overflow: hidden;
      transition: border-color 0.3s ease, box-shadow 0.3s ease;
    }
    .card[data-state="playing"] {
      border-color: rgba(50,215,75,0.28);
      box-shadow: 0 0 0 1px rgba(50,215,75,0.08) inset;
    }
    .card[data-state="unavailable"] { opacity: 0.5; }

    /* ── Header row ── */
    .header {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 13px 14px 0;
    }
    .speaker-icon {
      font-size: 19px;
      flex-shrink: 0;
      filter: drop-shadow(0 1px 2px rgba(0,0,0,0.4));
    }
    .name {
      flex: 1;
      font-size: 14px;
      font-weight: 600;
      color: var(--primary-text-color, #fff);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    /* ── State badge ── */
    .badge {
      display: flex;
      align-items: center;
      gap: 5px;
      flex-shrink: 0;
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--secondary-text-color, rgba(255,255,255,0.5));
    }
    .dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .dot[data-state="playing"]     { background: #32d74b; box-shadow: 0 0 0 3px rgba(50,215,75,0.22); animation: pulse 2.2s ease-in-out infinite; }
    .dot[data-state="buffering"]   { background: #ff9f0a; box-shadow: 0 0 0 3px rgba(255,159,10,0.22); }
    .dot[data-state="idle"]        { background: rgba(255,255,255,0.28); }
    .dot[data-state="unavailable"] { background: #ff3b30; }
    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50%       { opacity: 0.55; transform: scale(0.85); }
    }

    /* ── Icon buttons ── */
    .actions { display: flex; gap: 2px; flex-shrink: 0; }
    .icon-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 30px;
      height: 30px;
      padding: 0;
      border: none;
      border-radius: 8px;
      background: transparent;
      cursor: pointer;
      font-size: 14px;
      color: var(--secondary-text-color, rgba(255,255,255,0.55));
      transition: background 0.14s, color 0.14s, transform 0.1s;
      line-height: 1;
    }
    .icon-btn:hover  { background: rgba(255,255,255,0.08); color: var(--primary-text-color, #fff); }
    .icon-btn:active { transform: scale(0.9); }
    .icon-btn:disabled { opacity: 0.3; cursor: not-allowed; pointer-events: none; }

    .btn-route  { color: #32d74b; }
    .btn-route:hover  { background: rgba(50,215,75,0.14); }
    .btn-stop   { color: #ff3b30; }
    .btn-stop:hover   { background: rgba(255,59,48,0.14); }
    .btn-settings.active { background: rgba(255,255,255,0.11); color: #fff; }

    /* ── Controls area ── */
    .controls { padding: 8px 14px 14px; }

    /* ── Settings drawer (CSS grid trick for smooth expand) ── */
    .drawer {
      display: grid;
      grid-template-rows: 0fr;
      transition: grid-template-rows 0.27s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .drawer.open { grid-template-rows: 1fr; }
    .drawer-inner { min-height: 0; overflow: hidden; }

    .drawer-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 10px 0 6px;
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--secondary-text-color, rgba(255,255,255,0.35));
    }
    .drawer-header::before,
    .drawer-header::after {
      content: "";
      flex: 1;
      height: 1px;
      background: rgba(255,255,255,0.07);
    }
  `;

  constructor() {
    super();
    this._settingsOpen = false;
    this._confirmOpen  = false;

    // Debounced service callers — avoid flooding HA on every slider tick.
    this._callVolume = debounce((entityId, pct) => {
      this.hass?.callService("bluetooth_audio_server", "set_volume", {
        output_id: entityId,
        volume: parseFloat((pct / 100).toFixed(2)),
      });
    }, 300);

    this._callDelay = debounce((entityId, ms) => {
      this.hass?.callService("bluetooth_audio_server", "set_delay", {
        output_id: entityId,
        delay_ms: ms,
      });
    }, 400);
  }

  // ── Derived state from hass ──

  get _stateObj() { return this.hass?.states[this.entity]; }
  get _state()    { return this._stateObj?.state ?? "unavailable"; }
  get _attrs()    { return this._stateObj?.attributes ?? {}; }
  get _volPct()   { return Math.round((this._attrs.volume_level ?? 0.75) * 100); }
  get _delayMs()  { return this._attrs.delay_ms ?? 0; }

  get _displayName() {
    return this.name || this._attrs.friendly_name || this.entity;
  }

  // ── Service calls ──

  _route() {
    this.hass.callService("bluetooth_audio_server", "route_to_output", {
      output_id: this.entity,
    });
  }

  _openConfirm() { this._confirmOpen = true; }
  _closeConfirm() { this._confirmOpen = false; }

  _doStop() {
    this._confirmOpen = false;
    this.hass.callService("bluetooth_audio_server", "stop_output", {
      output_id: this.entity,
    });
  }

  _toggleSettings() { this._settingsOpen = !this._settingsOpen; }

  render() {
    const state   = this._state;
    const label   = STATE_LABEL[state] ?? state;
    const isIdle  = state === "idle" || state === "buffering" || state === "playing";
    const canStop = state === "playing" || state === "buffering";

    return html`
      <!-- Output card -->
      <div class="card" data-state=${state}>

        <!-- Header -->
        <div class="header">
          <span class="speaker-icon">🔊</span>
          <span class="name" title=${this.entity}>${this._displayName}</span>

          <div class="badge">
            <div class="dot" data-state=${state}></div>
            ${label}
          </div>

          <div class="actions">
            <button
              class="icon-btn btn-route"
              title="Route audio to this output"
              ?disabled=${!isIdle}
              @click=${this._route}
            >▶</button>

            <button
              class="icon-btn btn-stop"
              title="Stop this output"
              ?disabled=${!canStop}
              @click=${this._openConfirm}
            >■</button>

            <button
              class="icon-btn btn-settings ${this._settingsOpen ? "active" : ""}"
              title="${this._settingsOpen ? "Close" : "Open"} settings"
              @click=${this._toggleSettings}
            >⚙</button>
          </div>
        </div>

        <!-- Controls -->
        <div class="controls">

          <!-- Volume -->
          <bt-slider-control
            icon="🔈"
            .value=${this._volPct}
            min="0" max="100" step="1" unit="%"
            @bt-change=${e => this._callVolume(this.entity, e.detail)}
          ></bt-slider-control>

          <!-- Settings drawer -->
          <div class="drawer ${this._settingsOpen ? "open" : ""}">
            <div class="drawer-inner">
              <div class="drawer-header">Settings</div>

              <!-- Delay -->
              <bt-slider-control
                icon="⏱"
                .value=${this._delayMs}
                min="0" max="2000" step="10" unit="ms"
                @bt-change=${e => this._callDelay(this.entity, e.detail)}
              ></bt-slider-control>
            </div>
          </div>

        </div>
      </div>

      <!-- Confirmation dialog (portal-like; rendered after card so z-index works) -->
      <bt-confirm-dialog
        ?open=${this._confirmOpen}
        message="Audio to '${this._displayName}' will stop immediately."
        @bt-cancel=${this._closeConfirm}
        @bt-confirm=${this._doStop}
      ></bt-confirm-dialog>
    `;
  }
}
customElements.define("bt-output-card", BtOutputCard);


// ─── bluetooth-audio-card (root) ─────────────────────────────────────────────
//
// The main Lovelace card.  Layout:
//   ┌──────────────────────────────────┐
//   │ Header (title + burger menu)     │
//   ├──────────────────────────────────┤  ≈ 25%
//   │ Source section                   │
//   ├──────────────────────────────────┤
//   │ Outputs section  (scrollable)    │  ≈ 70%
//   ├──────────────────────────────────┤
//   │ Footer: Stop All                 │  ≈ 10%
//   └──────────────────────────────────┘
//
// The burger menu slides in from the right as an absolute-positioned drawer
// over the card.

class BluetoothAudioCard extends LitElement {
  static properties = {
    hass:       { attribute: false },
    _config:    { state: true },
    _menuOpen:  { state: true },
    _srcEntity: { state: true },   // selected source entity id
  };

  // ── Required Lovelace card API ──

  setConfig(config) {
    if (!Array.isArray(config.outputs)) {
      throw new Error("bluetooth-audio-card: 'outputs' must be a list.");
    }
    this._config = config;
    this._srcEntity = this._srcEntity ?? "";
  }

  static getStubConfig() {
    return {
      title: "Music Server",
      source_sensor: "sensor.bt_audio_source_state",
      source_device_sensor: "sensor.bt_audio_source_device",
      outputs: [
        { entity: "media_player.bt_output_living_room", name: "Living Room" },
        { entity: "media_player.bt_output_bedroom",     name: "Bedroom" },
      ],
    };
  }

  static getCardSize() { return 5; }

  // ── Computed props ──

  get _sourceState() {
    const id = this._config?.source_sensor;
    return id ? (this.hass?.states[id]?.state ?? "disconnected") : "disconnected";
  }

  get _sourceDevice() {
    const id = this._config?.source_device_sensor;
    const v  = id ? this.hass?.states[id]?.state : null;
    return (!v || v === "unknown" || v === "unavailable") ? null : v;
  }

  /** All media_player entities in HA, sorted alphabetically by friendly name. */
  get _allMediaPlayers() {
    if (!this.hass) return [];
    return Object.entries(this.hass.states)
      .filter(([id]) => id.startsWith("media_player."))
      .map(([id, s]) => ({ id, name: s.attributes.friendly_name || id }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  // ── Actions ──

  _stopAll() {
    this.hass.callService("bluetooth_audio_server", "stop_all", {});
  }

  _toggleMenu() { this._menuOpen = !this._menuOpen; }
  _closeMenu()  { this._menuOpen = false; }

  _onSourceChange(e) {
    this._srcEntity = e.target.value;
    // Placeholder for future "select source" service call.
    // When a media_player is chosen, it could be passed to the backend
    // to configure which HA entity to mirror as the A2DP source.
  }

  // ── Styles ──

  static styles = css`
    :host {
      display: block;
      /* Expose card-level tokens so sub-elements can override via :host vars */
      --bt-primary:  var(--primary-color, #4a90d9);
      --bt-success:  #32d74b;
      --bt-danger:   #ff3b30;
      --bt-warning:  #ff9f0a;
      --bt-radius:   16px;
      --bt-surface:  rgba(255,255,255,0.04);
    }

    ha-card {
      overflow: hidden;
      display: flex;
      flex-direction: column;
      /* Give the card a baseline height; flex handles the rest */
    }

    /* Inner wrapper is position:relative so the slide-out drawer can be
       position:absolute without escaping the card's painted bounds. */
    .card-inner {
      position: relative;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      flex: 1;
    }

    /* ─── Header ─── */
    .card-header {
      display: flex;
      align-items: center;
      padding: 16px 18px 13px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      flex-shrink: 0;
    }
    .card-title {
      flex: 1;
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.01em;
      color: var(--primary-text-color, #fff);
    }
    .burger-btn {
      background: none;
      border: none;
      cursor: pointer;
      color: var(--secondary-text-color, rgba(255,255,255,0.55));
      font-size: 20px;
      line-height: 1;
      width: 34px;
      height: 34px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 8px;
      transition: background 0.14s;
      padding: 0;
    }
    .burger-btn:hover { background: rgba(255,255,255,0.08); }

    /* ─── Source section ─── */
    .source-section {
      padding: 14px 16px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      flex-shrink: 0;
    }

    .section-label {
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--secondary-text-color, rgba(255,255,255,0.35));
      margin-bottom: 9px;
    }

    .source-pill {
      display: flex;
      align-items: center;
      gap: 12px;
      background: var(--bt-surface);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 12px;
      padding: 10px 14px;
    }
    .source-dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      flex-shrink: 0;
      transition: background 0.35s, box-shadow 0.35s;
    }
    .source-dot[data-streaming="true"] {
      animation: stream-pulse 2s ease-in-out infinite;
    }
    @keyframes stream-pulse {
      0%, 100% { opacity: 1;    box-shadow: 0 0 0 0   rgba(50,215,75,0.4); }
      50%       { opacity: 0.7; box-shadow: 0 0 0 5px rgba(50,215,75,0);   }
    }

    .source-info { flex: 1; min-width: 0; }
    .source-device {
      font-size: 14px;
      font-weight: 600;
      color: var(--primary-text-color, #fff);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .source-state-text {
      font-size: 11px;
      color: var(--secondary-text-color, rgba(255,255,255,0.5));
    }

    /* Custom styled <select> for the source dropdown */
    .source-select {
      -webkit-appearance: none;
      appearance: none;
      background: rgba(255,255,255,0.07)
        url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath fill='rgba(255,255,255,0.45)' d='M0 0l5 6 5-6z'/%3E%3C/svg%3E")
        no-repeat right 9px center;
      border: 1px solid rgba(255,255,255,0.11);
      border-radius: 9px;
      color: var(--primary-text-color, #fff);
      font-size: 12px;
      font-family: inherit;
      padding: 7px 28px 7px 10px;
      outline: none;
      cursor: pointer;
      flex-shrink: 0;
      max-width: 150px;
      transition: border-color 0.15s;
    }
    .source-select:focus { border-color: var(--bt-primary); }
    .source-select option { background: #2c2c2e; color: #fff; }

    /* ─── Outputs section ─── */
    .outputs-label { padding: 13px 16px 0; flex-shrink: 0; }
    .outputs-label .section-label { margin-bottom: 0; }

    .outputs-section {
      flex: 1;
      overflow-y: auto;
      padding: 10px 16px;
      /* min-height prevents card from collapsing with 0 outputs */
      min-height: 120px;
      max-height: 56vh;
      scrollbar-width: thin;
      scrollbar-color: rgba(255,255,255,0.14) transparent;
    }
    .outputs-section::-webkit-scrollbar { width: 4px; }
    .outputs-section::-webkit-scrollbar-track { background: transparent; }
    .outputs-section::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.14); border-radius: 2px; }

    .empty-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 40px 20px;
      text-align: center;
      color: var(--secondary-text-color, rgba(255,255,255,0.4));
      gap: 10px;
    }
    .empty-icon { font-size: 40px; }
    .empty-text { font-size: 13px; line-height: 1.5; }

    /* ─── Footer ─── */
    .footer {
      display: flex;
      align-items: center;
      padding: 10px 16px 14px;
      border-top: 1px solid rgba(255,255,255,0.06);
      gap: 10px;
      flex-shrink: 0;
    }

    .stop-all-btn {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 11px 16px;
      background: rgba(255,59,48,0.1);
      border: 1px solid rgba(255,59,48,0.22);
      border-radius: 11px;
      color: var(--bt-danger);
      font-size: 14px;
      font-weight: 700;
      font-family: inherit;
      letter-spacing: 0.02em;
      cursor: pointer;
      transition: background 0.15s, transform 0.1s;
    }
    .stop-all-btn:hover  { background: rgba(255,59,48,0.2); }
    .stop-all-btn:active { transform: scale(0.97); }
    .stop-all-btn .icon  { font-size: 16px; }

    /* ─── Burger menu overlay + drawer ─── */
    .menu-overlay {
      position: absolute;
      inset: 0;
      background: rgba(0,0,0,0.45);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.24s ease;
      z-index: 10;
      backdrop-filter: blur(2px);
    }
    .menu-overlay.open { opacity: 1; pointer-events: all; }

    .menu-drawer {
      position: absolute;
      top: 0; right: 0; bottom: 0;
      width: 220px;
      background: var(--card-background-color, #1c1c1e);
      border-left: 1px solid rgba(255,255,255,0.09);
      box-shadow: -8px 0 28px rgba(0,0,0,0.35);
      transform: translateX(100%);
      transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
      z-index: 11;
      display: flex;
      flex-direction: column;
    }
    .menu-drawer.open { transform: translateX(0); }

    .menu-close-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 16px 16px 12px;
      border-bottom: 1px solid rgba(255,255,255,0.07);
    }
    .menu-title {
      font-size: 14px;
      font-weight: 700;
      color: var(--primary-text-color, #fff);
    }
    .menu-close-btn {
      background: none;
      border: none;
      cursor: pointer;
      color: var(--secondary-text-color, rgba(255,255,255,0.55));
      font-size: 18px;
      line-height: 1;
      padding: 4px;
      border-radius: 6px;
      transition: background 0.13s;
    }
    .menu-close-btn:hover { background: rgba(255,255,255,0.09); }

    .menu-items { flex: 1; padding: 6px 0; }

    .menu-item {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 13px 16px;
      font-size: 14px;
      color: var(--primary-text-color, #fff);
      cursor: pointer;
      transition: background 0.12s;
      user-select: none;
    }
    .menu-item:hover { background: rgba(255,255,255,0.06); }
    .menu-item:active { background: rgba(255,255,255,0.1); }
    .menu-item .m-icon { font-size: 18px; width: 22px; text-align: center; }

    .menu-footer {
      padding: 12px 16px;
      border-top: 1px solid rgba(255,255,255,0.06);
      font-size: 11px;
      color: var(--secondary-text-color, rgba(255,255,255,0.3));
      text-align: center;
    }
  `;

  render() {
    if (!this._config || !this.hass) return nothing;

    const srcState  = this._sourceState;
    const srcDevice = this._sourceDevice;
    const dotColor  = STATE_COLOR[srcState] ?? "rgba(255,255,255,0.22)";
    const outputs   = this._config.outputs ?? [];
    const players   = this._allMediaPlayers;
    const isStream  = srcState === "streaming";

    return html`
      <ha-card>
        <div class="card-inner">

          <!-- ══ Header ══ -->
          <div class="card-header">
            <span class="card-title">
              ${this._config.title ?? "Bluetooth Audio"}
            </span>
            <button class="burger-btn" @click=${this._toggleMenu} title="Menu">
              ☰
            </button>
          </div>

          <!-- ══ Source Section ══ -->
          <div class="source-section">
            <div class="section-label">Bluetooth Source</div>
            <div class="source-pill">

              <div class="source-dot"
                data-streaming=${isStream}
                style="background:${dotColor};"
              ></div>

              <div class="source-info">
                <div class="source-device">
                  ${srcDevice ?? "No device connected"}
                </div>
                <div class="source-state-text">
                  ${STATE_LABEL[srcState] ?? srcState}
                </div>
              </div>

              <select
                class="source-select"
                .value=${this._srcEntity}
                @change=${this._onSourceChange}
                title="Override source media player"
              >
                <option value="">Auto-detect</option>
                ${players.map(p => html`
                  <option value=${p.id} ?selected=${this._srcEntity === p.id}>
                    ${p.name}
                  </option>
                `)}
              </select>

            </div>
          </div>

          <!-- ══ Outputs Section ══ -->
          <div class="outputs-label">
            <div class="section-label">Outputs</div>
          </div>
          <div class="outputs-section">
            ${outputs.length === 0 ? html`
              <div class="empty-state">
                <div class="empty-icon">🔇</div>
                <div class="empty-text">
                  No outputs configured.<br>
                  Add <code>outputs:</code> entries to your card YAML.
                </div>
              </div>
            ` : outputs.map(out => html`
              <bt-output-card
                .hass=${this.hass}
                entity=${out.entity}
                name=${out.name ?? ""}
              ></bt-output-card>
            `)}
          </div>

          <!-- ══ Footer ══ -->
          <div class="footer">
            <button class="stop-all-btn" @click=${this._stopAll}>
              <span class="icon">■</span>
              Stop All Outputs
            </button>
          </div>

          <!-- ══ Burger Menu ══ -->
          <div
            class="menu-overlay ${this._menuOpen ? "open" : ""}"
            @click=${this._closeMenu}
          ></div>

          <div class="menu-drawer ${this._menuOpen ? "open" : ""}">
            <div class="menu-close-row">
              <span class="menu-title">Options</span>
              <button class="menu-close-btn" @click=${this._closeMenu}>✕</button>
            </div>

            <div class="menu-items">
              <div class="menu-item" @click=${() => {
                this._closeMenu();
                this.hass.callService("homeassistant", "reload_config_entry", {
                  entry_id: Object.values(this.hass.states)
                    .find(s => s.entity_id.startsWith("sensor.bt_audio"))
                    ?.attributes.entry_id ?? "",
                });
              }}>
                <span class="m-icon">↻</span> Reload Integration
              </div>

              <div class="menu-item" @click=${() => {
                this._closeMenu();
                this.hass.callService("persistent_notification", "create", {
                  title: "Bluetooth Audio Server",
                  message: "Scanning for Bluetooth devices…",
                  notification_id: "bt_audio_scan",
                });
              }}>
                <span class="m-icon">🔍</span> Scan for Devices
              </div>

              <div class="menu-item" @click=${() => {
                window.open("/config/integrations/integration/bluetooth_audio_server", "_blank");
                this._closeMenu();
              }}>
                <span class="m-icon">⚙</span> Integration Settings
              </div>
            </div>

            <div class="menu-footer">Bluetooth Audio Server v0.1</div>
          </div>

        </div>
      </ha-card>
    `;
  }
}
customElements.define("bluetooth-audio-card", BluetoothAudioCard);

// ─── Card registration ───────────────────────────────────────────────────────
// Registers the card with the Lovelace card picker UI.

window.customCards ??= [];
window.customCards.push({
  type:        "bluetooth-audio-card",
  name:        "Bluetooth Audio Server",
  description: "Control Bluetooth A2DP source routing and per-speaker delay.",
  preview:     true,
  documentationURL: "https://github.com/spikeeee/ha-bluetooth-audio-server",
});
