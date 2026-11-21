const DOMAIN = "thermal_storage_optimizer";
const CARD_TAG = "thermal-storage-day-chart-card";
const REFRESH_MS = 5 * 60 * 1000;
const HOUR_MS = 3600 * 1000;

const TEXT = {
  en: {
    title: "Today and tomorrow",
    loading: "Loading chart…",
    error: "The chart data could not be loaded.",
    noHistory: "Recorder history is unavailable, so past outcomes are not shown.",
    noPrices: "No electricity prices are available.",
    tomorrowPending: "Tomorrow's prices are not published yet",
    tomorrowPendingShort: "No prices yet",
    price: "Electricity price",
    perKwh: "per kWh",
    plannedFiring: "Planned firing",
    actualFiring: "Actual firing",
    plannedTank: "Planned tank",
    actualTank: "Actual tank",
    use: "Use tank",
    reserve: "Reserve tank",
    forced: "Forced use",
    other: "No control",
    firing: "Firing",
    firingWindow: "Firing window",
    latestStart: "latest start",
    none: "—",
    now: "Now",
    time: "Time",
    hint: "Point at the chart for exact values.",
    table: "Hourly table",
  },
  sv: {
    title: "Idag och imorgon",
    loading: "Läser in diagrammet…",
    error: "Diagramdata kunde inte läsas in.",
    noHistory: "Recorder-historik saknas, så faktiskt utfall visas inte.",
    noPrices: "Det finns inga elpriser att visa.",
    tomorrowPending: "Morgondagens priser är inte publicerade än",
    tomorrowPendingShort: "Inga priser än",
    price: "Elpris",
    perKwh: "per kWh",
    plannedFiring: "Planerad eldning",
    actualFiring: "Faktisk eldning",
    plannedTank: "Planerad tank",
    actualTank: "Faktisk tank",
    use: "Använd tank",
    reserve: "Spara tank",
    forced: "Tvingad användning",
    other: "Ingen styrning",
    firing: "Eldning",
    firingWindow: "Eldningsfönster",
    latestStart: "senaste start",
    none: "—",
    now: "Nu",
    time: "Tid",
    hint: "Peka på diagrammet för exakta värden.",
    table: "Timtabell",
  },
};

const TANK_STATES = {
  use_tank: "use",
  reserve_tank: "reserve",
  forced_use: "forced",
  cold_or_empty: "other",
  waiting_for_data: "other",
  fault_fallback: "other",
  disabled: "other",
};

class ThermalStorageDayChartCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = undefined;
    this._data = undefined;
    this._history = undefined;
    this._historyFailed = false;
    this._error = undefined;
    this._loading = false;
    this._loadedAt = 0;
    this._watchSignature = undefined;
    this._hoverTime = undefined;
    this._tableOpen = false;
    this._geometry = undefined;
    this._model = undefined;
    this._timer = undefined;
    this._width = 700;
    this._resizeObserver = new ResizeObserver((entries) => {
      const width = Math.round(entries[0]?.contentRect?.width || 0);
      if (width && Math.abs(width - this._width) > 4) {
        this._width = width;
        this._render();
      }
    });
    const root = this.shadowRoot;
    root.addEventListener("pointermove", (event) => this._hover(event));
    root.addEventListener("pointerdown", (event) => this._hover(event));
    root.addEventListener("pointerleave", () => this._setHover(undefined), true);
    root.addEventListener(
      "toggle",
      (event) => {
        if (event.target instanceof HTMLDetailsElement) this._tableOpen = event.target.open;
      },
      true,
    );
  }

  setConfig(config) {
    this._config = { title: config?.title };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const signature = this._signature();
    if (!this._data && !this._error) {
      void this._load();
    } else if (signature !== this._watchSignature) {
      this._watchSignature = signature;
      void this._load();
    }
  }

  connectedCallback() {
    this._resizeObserver.observe(this);
    this._timer = window.setInterval(() => void this._load(), REFRESH_MS);
    if (this._hass && Date.now() - this._loadedAt > REFRESH_MS) void this._load();
  }

  disconnectedCallback() {
    this._resizeObserver.disconnect();
    window.clearInterval(this._timer);
  }

  getCardSize() {
    return 7;
  }

  getGridOptions() {
    return { columns: "full", min_columns: 6 };
  }

  static getStubConfig() {
    return {};
  }

  get _t() {
    return TEXT[this._hass?.language?.startsWith("sv") ? "sv" : "en"];
  }

  get _locale() {
    return this._hass?.locale?.language || this._hass?.language || undefined;
  }

  _signature() {
    const entities = Object.values(this._data?.entities || {}).filter(Boolean);
    return entities.map((id) => `${id}:${this._hass?.states?.[id]?.state || ""}`).join("|");
  }

  async _load() {
    if (!this._hass || this._loading || !this.isConnected) return;
    this._loading = true;
    if (!this._data) this._render();
    try {
      const result = await this._hass.callWS({
        type: "call_service",
        domain: DOMAIN,
        service: "get_day_chart",
        service_data: {},
        return_response: true,
      });
      const data = result?.response ?? result;
      if (!data || !Array.isArray(data.prices) || !Array.isArray(data.planned)) {
        throw new Error("Invalid day-chart response");
      }
      this._data = data;
      this._error = undefined;
      await this._loadHistory(data);
    } catch (error) {
      this._error = error instanceof Error ? error.message : String(error?.message || error);
    } finally {
      this._loading = false;
      this._loadedAt = Date.now();
      this._watchSignature = this._signature();
      this._render();
    }
  }

  async _loadHistory(data) {
    const ids = Object.values(data.entities || {}).filter(Boolean);
    if (!ids.length) {
      this._history = {};
      this._historyFailed = true;
      return;
    }
    try {
      this._history = await this._hass.callWS({
        type: "history/history_during_period",
        start_time: new Date(data.window_start).toISOString(),
        end_time: new Date().toISOString(),
        entity_ids: ids,
        minimal_response: true,
        no_attributes: true,
        significant_changes_only: false,
      });
      this._historyFailed = false;
    } catch (_error) {
      this._history = {};
      this._historyFailed = true;
    }
  }

  /* ---------- data shaping ---------- */

  _buildModel() {
    const data = this._data;
    const start = new Date(data.window_start).getTime();
    const end = new Date(data.window_end).getTime();
    const now = Math.min(Math.max(Date.now(), start), end);
    const clip = (segments) =>
      mergeSegments(
        segments
          .map((s) => ({ ...s, start: Math.max(s.start, start), end: Math.min(s.end, end) }))
          .filter((s) => Number.isFinite(s.start) && Number.isFinite(s.end) && s.end > s.start),
      );

    const prices = data.prices
      .map((p) => ({
        start: new Date(p.start).getTime(),
        end: new Date(p.end).getTime(),
        price: Number(p.price),
      }))
      .filter((p) => Number.isFinite(p.price) && p.end > start && p.start < end && p.end > p.start)
      .sort((a, b) => a.start - b.start);

    const entities = data.entities || {};
    const history = (key) => historySegments(this._history?.[entities[key]], start, now);

    const plannedPast = history("release_recommended")
      .map((s) => ({ ...s, state: s.state === "on" ? "use" : s.state === "off" ? "reserve" : undefined }))
      .filter((s) => s.state);
    const plannedFuture = [];
    for (const item of data.planned) {
      const from = new Date(item.start).getTime();
      const to = new Date(item.end).getTime();
      const release = item.recommendation === "use_tank" ? new Date(item.release_start).getTime() : to;
      plannedFuture.push({ start: Math.max(from, now), end: Math.min(release, to), state: "reserve" });
      plannedFuture.push({ start: Math.max(release, now), end: to, state: "use" });
    }

    const actualTank = history("operating_state")
      .map((s) => ({ ...s, state: TANK_STATES[s.state] }))
      .filter((s) => s.state);
    const actualFiring = history("stove_firing")
      .filter((s) => s.state === "on")
      .map((s) => ({ ...s, state: "firing" }));

    const firing = data.firing;
    const plannedFiring = [];
    let latestStart;
    if (firing?.recommended) {
      const earliest = new Date(firing.earliest_start).getTime();
      latestStart = new Date(firing.latest_start).getTime();
      const duration = (Number(firing.duration_minutes) || 0) * 60000;
      plannedFiring.push({
        start: earliest,
        end: Math.max(latestStart + duration, earliest + duration),
        state: "window",
      });
    }

    const boundary = new Date(data.day_boundary).getTime();
    return {
      start,
      end,
      boundary: boundary > start && boundary < end ? boundary : start + (end - start) / 2,
      now,
      prices,
      latestStart,
      firing,
      lanes: [
        { key: "plannedFiring", segments: clip(plannedFiring) },
        { key: "actualFiring", segments: clip(actualFiring) },
        { key: "plannedTank", segments: clip([...plannedPast, ...plannedFuture]) },
        { key: "actualTank", segments: clip(actualTank) },
      ],
    };
  }

  _stateLabel(state) {
    if (state === "window") return this._t.firingWindow;
    return this._t[state] || this._t.none;
  }

  _valuesAt(time) {
    const model = this._model;
    const price = model.prices.find((p) => time >= p.start && time < p.end);
    const values = [[this._t.time, this._dateTime(time, true)]];
    values.push([this._t.price, price ? `${this._number(price.price, 2)} ${this._t.perKwh}` : this._t.none]);
    for (const lane of model.lanes) {
      const segment = lane.segments.find((s) => time >= s.start && time < s.end);
      let label = segment ? this._stateLabel(segment.state) : this._t.none;
      if (segment?.state === "window" && model.latestStart) {
        label += ` (${this._t.latestStart} ${this._dateTime(model.latestStart)})`;
      }
      values.push([this._t[lane.key], label]);
    }
    return values;
  }

  /* ---------- formatting ---------- */

  _number(value, digits = 2) {
    if (value === undefined || value === null || !Number.isFinite(Number(value))) return "—";
    return new Intl.NumberFormat(this._locale, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(Number(value));
  }

  _format(time, options) {
    const timeZone = this._hass?.config?.time_zone;
    try {
      return new Intl.DateTimeFormat(this._locale, { ...options, timeZone }).format(new Date(time));
    } catch (_error) {
      return new Intl.DateTimeFormat(this._locale, options).format(new Date(time));
    }
  }

  _dateTime(time, withDay = false) {
    return this._format(time, {
      weekday: withDay ? "short" : undefined,
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    });
  }

  /* ---------- interaction ---------- */

  _hover(event) {
    const geometry = this._geometry;
    const svg = this.shadowRoot.querySelector("svg");
    if (!geometry || !svg || !event.composedPath().includes(svg)) return;
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * geometry.width;
    if (px < geometry.left || px > geometry.right) return this._setHover(undefined);
    const ratio = (px - geometry.left) / (geometry.right - geometry.left);
    this._setHover(geometry.start + ratio * (geometry.end - geometry.start));
  }

  _setHover(time) {
    this._hoverTime = time;
    const geometry = this._geometry;
    const line = this.shadowRoot.querySelector(".crosshair");
    const readout = this.shadowRoot.querySelector(".readout");
    if (!geometry || !line || !readout) return;
    if (time === undefined) {
      line.setAttribute("visibility", "hidden");
    } else {
      const px =
        geometry.left +
        ((time - geometry.start) / (geometry.end - geometry.start)) * (geometry.right - geometry.left);
      line.setAttribute("x1", px);
      line.setAttribute("x2", px);
      line.setAttribute("visibility", "visible");
    }
    readout.innerHTML = this._renderReadout();
  }

  /* ---------- rendering ---------- */

  _render() {
    if (!this.shadowRoot) return;
    const title = escapeHtml(this._config.title || this._t.title);
    let body;
    if (this._data) {
      this._model = this._buildModel();
      body = this._renderBody();
    } else {
      this._geometry = undefined;
      body = `<div class="empty ${this._error ? "is-error" : ""}">${escapeHtml(
        this._error ? `${this._t.error} ${this._error}` : this._t.loading,
      )}</div>`;
    }
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        <div class="title">${title}</div>
        ${body}
      </ha-card>`;
    if (this._data) this._setHover(this._hoverTime);
  }

  _renderBody() {
    const t = this._t;
    const notes = [];
    if (this._error) notes.push(`${t.error} ${this._error}`);
    if (this._historyFailed) notes.push(t.noHistory);
    if (!this._model.prices.length) notes.push(t.noPrices);
    const legend = [
      ["use", t.use],
      ["reserve", t.reserve],
      ["forced", t.forced],
      ["other", t.other],
      ["window", t.firingWindow],
      ["firing", t.firing],
    ]
      .map(([key, label]) => `<span><i class="swatch swatch-${key}"></i>${escapeHtml(label)}</span>`)
      .join("");
    return `
      <div class="legend">${legend}</div>
      <div class="chart-wrap">${this._renderChart()}</div>
      <div class="readout" aria-live="polite"></div>
      ${notes.map((note) => `<div class="note">${escapeHtml(note)}</div>`).join("")}
      <details ${this._tableOpen ? "open" : ""}>
        <summary>${escapeHtml(t.table)}</summary>
        <div class="table-wrap">${this._renderTable()}</div>
      </details>`;
  }

  _renderReadout() {
    if (this._hoverTime === undefined) return `<span class="hint">${escapeHtml(this._t.hint)}</span>`;
    return this._valuesAt(this._hoverTime)
      .map(([label, value]) => `<span><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></span>`)
      .join("");
  }

  _renderChart() {
    const t = this._t;
    const model = this._model;
    const width = Math.max(280, this._width - 32);
    const narrow = width < 460;
    const left = 40;
    const right = width - 8;
    const plotWidth = right - left;
    const dateY = 12;
    const priceTop = 34;
    const priceHeight = narrow ? 110 : 140;
    const priceBottom = priceTop + priceHeight;
    const laneGap = 32;
    const laneHeight = 12;
    const lanesTop = priceBottom + 44;
    const lanesBottom = lanesTop + model.lanes.length * laneGap - (laneGap - laneHeight - 14);
    const height = lanesBottom + 20;
    const span = model.end - model.start;
    const x = (time) => left + ((time - model.start) / span) * plotWidth;
    this._geometry = { width, left, right, start: model.start, end: model.end };

    // Price scale: always include zero so the line height reads as magnitude.
    const values = model.prices.map((p) => p.price);
    const low = Math.min(0, ...values);
    const high = niceCeil(Math.max(0.01, ...values));
    const y = (value) => priceBottom - ((value - low) / (high - low)) * priceHeight;
    const priceTicks = [low, (low + high) / 2, high]
      .map(
        (value) => `<line class="grid" x1="${left}" x2="${right}" y1="${y(value)}" y2="${y(value)}" />
          <text class="axis" text-anchor="end" x="${left - 6}" y="${y(value) + 4}">${escapeHtml(
            this._number(value, 2),
          )}</text>`,
      )
      .join("");

    let path = "";
    let previousEnd;
    for (const p of model.prices) {
      const from = x(Math.max(p.start, model.start));
      const to = x(Math.min(p.end, model.end));
      path += `${previousEnd === p.start ? "L" : "M"}${from.toFixed(1)},${y(p.price).toFixed(1)}H${to.toFixed(1)}`;
      previousEnd = p.end;
    }

    // Time axis: a tick every 6 h (12 h when narrow), midnight emphasised.
    const step = (narrow ? 12 : 6) * HOUR_MS;
    const timeTicks = [];
    for (let time = model.start; time <= model.end + 1; time += step) {
      const px = x(time);
      const edge = time === model.start ? "start" : time >= model.end ? "end" : "middle";
      timeTicks.push(
        `<line class="grid" x1="${px}" x2="${px}" y1="${priceTop}" y2="${priceBottom}" />
         <text class="axis" text-anchor="${edge}" x="${px}" y="${priceBottom + 15}">${escapeHtml(
           this._format(time, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }),
         )}</text>`,
      );
    }
    const midnight = model.boundary;
    const dayLabel = (time) => this._format(time, { weekday: "long", day: "numeric", month: "short" });
    const days = `
      <text class="day" x="${left}" y="${dateY}">${escapeHtml(dayLabel(model.start + HOUR_MS))}</text>
      <text class="day" x="${x(midnight) + 5}" y="${dateY}">${escapeHtml(dayLabel(midnight + HOUR_MS))}</text>
      <line class="day-line" x1="${x(midnight)}" x2="${x(midnight)}" y1="2" y2="${lanesBottom}" />`;

    const lastPrice = model.prices.length ? model.prices[model.prices.length - 1].end : model.start;
    const pending =
      model.prices.length && lastPrice <= midnight + HOUR_MS
        ? `<text class="pending" text-anchor="middle" x="${(x(midnight) + right) / 2}" y="${
            priceTop + priceHeight / 2
          }">${escapeHtml(narrow ? t.tomorrowPendingShort : t.tomorrowPending)}</text>`
        : "";

    const lanes = model.lanes
      .map((lane, index) => {
        const top = lanesTop + index * laneGap;
        const rects = lane.segments
          .map((s) => {
            const from = x(s.start);
            return `<rect class="seg seg-${s.state}" x="${from.toFixed(1)}" y="${top}" width="${Math.max(
              0.6,
              x(s.end) - from,
            ).toFixed(1)}" height="${laneHeight}" rx="2" />`;
          })
          .join("");
        const marker =
          lane.key === "plannedFiring" && lane.segments.length && model.latestStart
            ? `<line class="latest" x1="${x(model.latestStart)}" x2="${x(model.latestStart)}" y1="${top - 3}" y2="${
                top + laneHeight + 3
              }"><title>${escapeHtml(`${t.latestStart} ${this._dateTime(model.latestStart)}`)}</title></line>`
            : "";
        return `<text class="lane-label" x="${left}" y="${top - 5}">${escapeHtml(t[lane.key])}</text>
          <rect class="lane-track" x="${left}" y="${top}" width="${plotWidth}" height="${laneHeight}" rx="2" />
          ${rects}${marker}`;
      })
      .join("");

    const nowX = x(model.now);
    const nowAnchor = nowX > right - 24 ? "end" : nowX < left + 24 ? "start" : "middle";
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(
      `${this._config.title || t.title}: ${t.price}, ${t.plannedFiring}, ${t.plannedTank}, ${t.actualTank}`,
    )}">
      <defs>
        <pattern id="reserve-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="2.5" height="5" class="hatch-reserve"></rect>
        </pattern>
        <pattern id="window-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
          <rect width="2" height="5" class="hatch-window"></rect>
        </pattern>
      </defs>
      ${days}
      <text class="lane-label" x="${left}" y="${priceTop - 8}">${escapeHtml(`${t.price} (${t.perKwh})`)}</text>
      ${priceTicks}${timeTicks.join("")}
      ${pending}
      <path class="price" d="${path}" />
      ${lanes}
      <line class="now-line" x1="${nowX}" x2="${nowX}" y1="${priceTop}" y2="${lanesBottom + 3}" />
      <text class="now-label" text-anchor="${nowAnchor}" x="${nowX}" y="${lanesBottom + 15}">${escapeHtml(t.now)}</text>
      <line class="crosshair" visibility="hidden" x1="0" x2="0" y1="${priceTop}" y2="${lanesBottom}" />
      <rect class="hit" x="${left}" y="${priceTop}" width="${plotWidth}" height="${lanesBottom - priceTop}" />
    </svg>`;
  }

  _renderTable() {
    const model = this._model;
    const header = [this._t.time, this._t.price, ...model.lanes.map((lane) => this._t[lane.key])];
    const rows = [];
    for (let time = model.start; time < model.end; time += HOUR_MS) {
      const values = this._valuesAt(time);
      // Sample each lane mid-hour so a change at the hour boundary is attributed correctly.
      const lanes = this._valuesAt(time + HOUR_MS / 2).slice(2);
      rows.push([values[0][1], values[1][1], ...lanes.map((value) => value[1])]);
    }
    return `<table>
      <thead><tr>${header.map((cell) => `<th>${escapeHtml(cell)}</th>`).join("")}</tr></thead>
      <tbody>${rows
        .map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`)
        .join("")}</tbody>
    </table>`;
  }
}

function historySegments(rows, start, now) {
  if (!Array.isArray(rows)) return [];
  const points = rows
    .map((row) => ({ state: row.s ?? row.state, time: historyTime(row) }))
    .filter((point) => Number.isFinite(point.time))
    .sort((a, b) => a.time - b.time);
  return points.map((point, index) => ({
    state: point.state,
    start: Math.max(point.time, start),
    end: Math.min(index + 1 < points.length ? points[index + 1].time : now, now),
  }));
}

function historyTime(row) {
  if (row.lu !== undefined) return Number(row.lu) * 1000;
  if (row.lc !== undefined) return Number(row.lc) * 1000;
  return new Date(row.last_updated ?? row.last_changed).getTime();
}

function mergeSegments(segments) {
  const sorted = [...segments].sort((a, b) => a.start - b.start);
  const merged = [];
  for (const segment of sorted) {
    const last = merged[merged.length - 1];
    if (last && last.state === segment.state && segment.start <= last.end + 1000) {
      last.end = Math.max(last.end, segment.end);
    } else {
      merged.push({ ...segment });
    }
  }
  return merged;
}

function niceCeil(value) {
  const magnitude = 10 ** Math.floor(Math.log10(value));
  for (const factor of [1, 2, 2.5, 4, 5, 8, 10]) {
    if (factor * magnitude >= value) return factor * magnitude;
  }
  return 10 * magnitude;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const STYLES = `
  :host {
    display: block;
    --tso-use: var(--success-color, #43a047);
    --tso-reserve: var(--warning-color, #ffa600);
    --tso-forced: var(--error-color, #db4437);
    --tso-other: var(--disabled-text-color, #9e9e9e);
    --tso-firing: var(--deep-orange-color, #ff5722);
    --tso-price: var(--primary-color, #03a9f4);
  }
  ha-card { padding: 16px; color: var(--primary-text-color); overflow: hidden; }
  .title { font-size: 20px; font-weight: 500; margin-bottom: 10px; }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 14px; color: var(--secondary-text-color); font-size: 12px; margin-bottom: 8px; }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .swatch { display: inline-block; width: 16px; height: 9px; border-radius: 2px; box-sizing: border-box; }
  .swatch-use { background: var(--tso-use); }
  .swatch-reserve { background: repeating-linear-gradient(135deg, var(--tso-reserve) 0 2px, transparent 2px 4px); border: 1px solid var(--tso-reserve); }
  .swatch-forced { background: var(--tso-forced); }
  .swatch-other { background: var(--tso-other); }
  .swatch-firing { background: var(--tso-firing); }
  .swatch-window { background: repeating-linear-gradient(45deg, var(--tso-firing) 0 2px, transparent 2px 4px); border: 1px solid var(--tso-firing); }
  .chart-wrap { width: 100%; }
  svg { display: block; width: 100%; height: auto; overflow: visible; touch-action: pan-y; }
  svg text { fill: var(--secondary-text-color); font-size: 11px; }
  .day, .lane-label { fill: var(--primary-text-color); font-weight: 500; }
  .day { font-size: 12px; }
  .lane-label, .axis { paint-order: stroke; stroke: var(--ha-card-background, var(--card-background-color, transparent)); stroke-width: 3px; stroke-linejoin: round; }
  .grid { stroke: var(--divider-color); stroke-width: 1; opacity: .6; }
  .day-line { stroke: var(--divider-color); stroke-width: 2; }
  .price { fill: none; stroke: var(--tso-price); stroke-width: 2; stroke-linejoin: round; }
  .pending { font-style: italic; }
  .lane-track { fill: color-mix(in srgb, var(--primary-text-color) 6%, transparent); }
  .seg-use { fill: var(--tso-use); }
  .seg-reserve { fill: url(#reserve-hatch); stroke: var(--tso-reserve); stroke-width: 1; }
  .hatch-reserve { fill: var(--tso-reserve); }
  .seg-forced { fill: var(--tso-forced); }
  .seg-other { fill: var(--tso-other); }
  .seg-firing { fill: var(--tso-firing); }
  .seg-window { fill: url(#window-hatch); stroke: var(--tso-firing); stroke-width: 1; }
  .hatch-window { fill: var(--tso-firing); }
  .latest { stroke: var(--primary-text-color); stroke-width: 2; }
  .now-line { stroke: var(--primary-text-color); stroke-width: 1.5; stroke-dasharray: 3 3; }
  .now-label { fill: var(--primary-text-color); font-weight: 500; }
  .crosshair { stroke: var(--secondary-text-color); stroke-width: 1; pointer-events: none; }
  .hit { fill: transparent; cursor: crosshair; }
  .readout { min-height: 40px; display: flex; flex-wrap: wrap; gap: 8px 18px; padding: 10px 0; }
  .readout > span { display: flex; flex-direction: column; }
  .readout small { color: var(--secondary-text-color); font-size: 11px; }
  .readout strong { font-size: 13px; font-weight: 500; }
  .readout .hint { display: block; color: var(--secondary-text-color); font-size: 13px; align-self: center; }
  .note { color: var(--secondary-text-color); font-size: 12px; padding-bottom: 6px; }
  details { border-top: 1px solid var(--divider-color); }
  summary { min-height: 40px; line-height: 40px; cursor: pointer; font-weight: 500; }
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; white-space: nowrap; }
  th, td { padding: 7px 10px; border-bottom: 1px solid var(--divider-color); text-align: left; }
  th { color: var(--secondary-text-color); font-weight: 500; }
  .empty { padding: 28px 4px; color: var(--secondary-text-color); }
  .empty.is-error { color: var(--error-color); }
  @media (max-width: 600px) { ha-card { padding: 12px; } }
`;

if (!customElements.get(CARD_TAG)) customElements.define(CARD_TAG, ThermalStorageDayChartCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: CARD_TAG,
  name: "Thermal Storage Day Chart",
  description: "Price, firing, and planned versus actual tank use for today and tomorrow",
  preview: true,
});
