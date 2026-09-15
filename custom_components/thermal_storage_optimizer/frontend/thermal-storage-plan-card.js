const DOMAIN = "thermal_storage_optimizer";
const CARD_TAG = "thermal-storage-plan-card";

const TEXT = {
  en: {
    title: "Thermal storage plan",
    recalculate: "Recalculate",
    loading: "Loading plan…",
    noPlan: "No future plan is available.",
    error: "The plan could not be loaded.",
    current: "Current recommendation",
    next: "Next tank use",
    energy: "Available tank energy",
    savings: "Expected avoided cost",
    use: "Use tank",
    reserve: "Reserve tank",
    waiting: "Waiting",
    unavailable: "Not scheduled",
    details: "Plan details",
    select: "Select an interval in the chart for exact values.",
    period: "Period",
    action: "Action",
    allocation: "Tank energy",
    demand: "Heat demand",
    price: "Electricity price",
    cop: "COP",
    value: "Adjusted heat value",
    saving: "Avoided cost",
    full_forecast: "Full forecast",
    saved_plan: "Saved plan",
    waitingStatus: "Waiting for forecast",
    invalid: "Invalid plan",
    now: "Now",
    demandLegend: "Heat demand",
    allocationLegend: "Allocated tank energy",
    priceLegend: "Electricity price",
  },
  sv: {
    title: "Plan för värmelagret",
    recalculate: "Beräkna om",
    loading: "Läser in planen…",
    noPlan: "Det finns ingen kommande plan att visa.",
    error: "Planen kunde inte läsas in.",
    current: "Aktuell rekommendation",
    next: "Nästa tankanvändning",
    energy: "Tillgänglig tankenergi",
    savings: "Förväntad besparing",
    use: "Använd tanken",
    reserve: "Spara tanken",
    waiting: "Väntar",
    unavailable: "Inte planerad",
    details: "Plandetaljer",
    select: "Välj ett intervall i diagrammet för exakta värden.",
    period: "Period",
    action: "Åtgärd",
    allocation: "Tankenergi",
    demand: "Värmebehov",
    price: "Elpris",
    cop: "COP",
    value: "Justerat värmevärde",
    saving: "Besparing",
    full_forecast: "Fullständig prognos",
    saved_plan: "Sparad plan",
    waitingStatus: "Väntar på prognos",
    invalid: "Ogiltig plan",
    now: "Nu",
    demandLegend: "Värmebehov",
    allocationLegend: "Tilldelad tankenergi",
    priceLegend: "Elpris",
  },
};

class ThermalStoragePlanCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = undefined;
    this._plan = undefined;
    this._error = undefined;
    this._loading = false;
    this._selected = undefined;
    this._detailsOpen = false;
    this._watchSignature = "";
    this._width = 700;
    this._resizeObserver = new ResizeObserver((entries) => {
      const width = Math.round(entries[0]?.contentRect?.width || 0);
      if (width && Math.abs(width - this._width) > 4) {
        this._width = width;
        this._render();
      }
    });
    this.shadowRoot.addEventListener("click", (event) => this._handleClick(event));
    this.shadowRoot.addEventListener("pointerover", (event) => this._selectFromEvent(event));
    this.shadowRoot.addEventListener("focusin", (event) => this._selectFromEvent(event));
    this.shadowRoot.addEventListener(
      "toggle",
      (event) => {
        if (event.target instanceof HTMLDetailsElement) this._detailsOpen = event.target.open;
      },
      true,
    );
  }

  setConfig(config) {
    this._config = {
      title: config.title,
      max_intervals: Math.min(48, Math.max(1, Number(config.max_intervals || 48))),
      last_optimization_entity:
        config.last_optimization_entity ||
        "sensor.thermal_storage_optimizer_last_optimization",
      plan_status_entity:
        config.plan_status_entity || "sensor.thermal_storage_optimizer_plan_status",
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const watched = [
      this._config.last_optimization_entity,
      this._config.plan_status_entity,
    ]
      .map((entityId) => {
        const state = hass.states[entityId];
        return `${entityId}:${state?.state || ""}:${state?.last_updated || ""}`;
      })
      .join("|");
    if (!this._plan || watched !== this._watchSignature) {
      this._watchSignature = watched;
      void this._loadPlan();
    }
  }

  connectedCallback() {
    this._resizeObserver.observe(this);
    if (this._hass && !this._plan) void this._loadPlan();
  }

  disconnectedCallback() {
    this._resizeObserver.disconnect();
  }

  getCardSize() {
    return 7;
  }

  static getStubConfig() {
    return {};
  }

  get _t() {
    return TEXT[this._hass?.language?.startsWith("sv") ? "sv" : "en"];
  }

  async _loadPlan() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    this._error = undefined;
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "call_service",
        domain: DOMAIN,
        service: "get_plan_summary",
        service_data: { max_intervals: this._config.max_intervals || 48 },
        return_response: true,
      });
      const response = result?.response ?? result;
      if (!response || !Array.isArray(response.intervals)) {
        throw new Error("Invalid plan-summary response");
      }
      this._plan = response;
      if (this._selected >= response.intervals.length) this._selected = undefined;
    } catch (error) {
      this._error = error instanceof Error ? error.message : String(error);
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _recalculate() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    this._render();
    try {
      await this._hass.callService(DOMAIN, "recalculate");
      this._loading = false;
      await this._loadPlan();
    } catch (error) {
      this._loading = false;
      this._error = error instanceof Error ? error.message : String(error);
      this._render();
    }
  }

  _handleClick(event) {
    const action = event.composedPath().find((node) => node?.dataset?.action)?.dataset
      ?.action;
    if (action === "recalculate") void this._recalculate();
    this._selectFromEvent(event);
  }

  _selectFromEvent(event) {
    const target = event.composedPath().find((node) => node?.dataset?.intervalIndex);
    if (!target) return;
    const index = Number(target.dataset.intervalIndex);
    if (Number.isInteger(index) && index !== this._selected) {
      this._selected = index;
      this._render();
    }
  }

  _number(value, maximumFractionDigits = 2) {
    if (value === undefined || value === null || !Number.isFinite(Number(value))) return "—";
    return new Intl.NumberFormat(this._hass?.locale?.language || this._hass?.language, {
      maximumFractionDigits,
    }).format(Number(value));
  }

  _dateTime(value, includeDate = false) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat(this._hass?.locale?.language || this._hass?.language, {
      weekday: includeDate ? "short" : undefined,
      month: includeDate ? "short" : undefined,
      day: includeDate ? "numeric" : undefined,
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }

  _statusLabel(status) {
    if (status === "waiting") return this._t.waitingStatus;
    return this._t[status] || status || this._t.waitingStatus;
  }

  _recommendationLabel(value) {
    if (value === "use_tank") return this._t.use;
    if (value === "reserve_tank") return this._t.reserve;
    return this._t.waiting;
  }

  _render() {
    if (!this.shadowRoot) return;
    const title = escapeHtml(this._config.title || this._t.title);
    const status = this._plan?.plan_status || "waiting";
    const content = this._plan?.intervals?.length
      ? this._renderPlan()
      : `<div class="empty ${this._error ? "is-error" : ""}">${escapeHtml(
          this._error ? `${this._t.error} ${this._error}` : this._loading ? this._t.loading : this._t.noPlan,
        )}</div>`;
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        <div class="header">
          <div>
            <div class="title">${title}</div>
            <div class="status status-${escapeHtml(status)}">${escapeHtml(
              this._statusLabel(status),
            )}</div>
          </div>
          <button class="recalculate" type="button" data-action="recalculate" ${
            this._loading ? "disabled" : ""
          } aria-label="${escapeHtml(this._t.recalculate)}">
            <ha-icon icon="mdi:calculator-variant"></ha-icon>
            <span>${escapeHtml(this._t.recalculate)}</span>
          </button>
        </div>
        ${content}
      </ha-card>`;
  }

  _renderPlan() {
    const intervals = this._plan.intervals;
    const now = Date.now();
    const nextUse = intervals.find(
      (item) => item.recommendation === "use_tank" && new Date(item.end).getTime() > now,
    );
    const metrics = [
      [this._t.current, this._recommendationLabel(this._plan.recommendation)],
      [this._t.next, nextUse ? this._dateTime(nextUse.start, true) : this._t.unavailable],
      [this._t.energy, `${this._number(this._plan.available_energy_kwh)} kWh`],
      [this._t.savings, this._number(this._plan.expected_avoided_cost)],
    ];
    return `
      <div class="metrics">
        ${metrics
          .map(
            ([label, value]) => `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(
              value,
            )}</strong></div>`,
          )
          .join("")}
      </div>
      <div class="legend" aria-label="Legend">
        <span><i class="legend-use"></i>${escapeHtml(this._t.use)}</span>
        <span><i class="legend-reserve"></i>${escapeHtml(this._t.reserve)}</span>
        <span><i class="legend-demand"></i>${escapeHtml(this._t.demandLegend)}</span>
        <span><i class="legend-price"></i>${escapeHtml(this._t.priceLegend)}</span>
      </div>
      <div class="chart-wrap">${this._renderChart(intervals)}</div>
      <div class="selection" aria-live="polite">${this._renderSelection()}</div>
      <details ${this._detailsOpen ? "open" : ""}>
        <summary>${escapeHtml(this._t.details)} (${intervals.length})</summary>
        <div class="table-wrap">${this._renderTable(intervals)}</div>
      </details>`;
  }

  _renderChart(intervals) {
    const valid = intervals
      .map((item, index) => ({
        ...item,
        index,
        startMs: new Date(item.start).getTime(),
        endMs: new Date(item.end).getTime(),
      }))
      .filter((item) => Number.isFinite(item.startMs) && Number.isFinite(item.endMs) && item.endMs > item.startMs);
    if (!valid.length) return "";
    const width = Math.max(300, this._width - 32);
    const height = width < 430 ? 235 : 270;
    const margin = { left: 42, right: 40, top: 30, bottom: 38 };
    const plotWidth = width - margin.left - margin.right;
    const plotTop = margin.top + 22;
    const plotBottom = height - margin.bottom;
    const plotHeight = plotBottom - plotTop;
    const start = Math.min(...valid.map((item) => item.startMs));
    const end = Math.max(...valid.map((item) => item.endMs));
    const span = Math.max(end - start, 1);
    const x = (time) => margin.left + ((time - start) / span) * plotWidth;
    const maxEnergy = Math.max(0.1, ...valid.map((item) => Number(item.heat_demand_kwh) || 0));
    const prices = valid.map((item) => Number(item.electricity_cost_per_kwh) || 0);
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const priceSpan = Math.max(maxPrice - minPrice, 0.01);
    const yEnergy = (value) => plotBottom - (Math.max(0, Number(value) || 0) / maxEnergy) * plotHeight;
    const yPrice = (value) => plotBottom - ((Number(value) - minPrice) / priceSpan) * plotHeight;

    const dayLines = [];
    const cursor = new Date(start);
    cursor.setHours(24, 0, 0, 0);
    while (cursor.getTime() < end) {
      const px = x(cursor.getTime());
      dayLines.push(`<line class="day-line" x1="${px}" x2="${px}" y1="20" y2="${plotBottom}" />`);
      dayLines.push(
        `<text class="date-label" x="${px + 4}" y="15">${escapeHtml(
          new Intl.DateTimeFormat(this._hass?.language, { weekday: "short", day: "numeric", month: "short" }).format(cursor),
        )}</text>`,
      );
      cursor.setDate(cursor.getDate() + 1);
    }

    const bars = valid
      .map((item) => {
        const left = x(item.startMs);
        const itemWidth = Math.max(1, x(item.endMs) - left);
        const demandY = yEnergy(item.heat_demand_kwh);
        const allocationY = yEnergy(item.allocated_energy_kwh);
        const actionClass = item.recommendation === "use_tank" ? "use" : "reserve";
        const action = this._recommendationLabel(item.recommendation);
        const label = `${this._dateTime(item.start, true)}–${this._dateTime(item.end)}: ${action}, ${this._number(
          item.allocated_energy_kwh,
        )} kWh`;
        return `<g class="interval ${actionClass} ${item.index === this._selected ? "selected" : ""}" data-interval-index="${
          item.index
        }" role="button" aria-label="${escapeHtml(label)}">
          <title>${escapeHtml(label)}</title>
          <rect class="action-band" x="${left}" y="25" width="${itemWidth}" height="16" />
          <rect class="demand-bar" x="${left + 1}" y="${demandY}" width="${Math.max(
            1,
            itemWidth - 2,
          )}" height="${Math.max(0, plotBottom - demandY)}" />
          <rect class="allocation-bar" x="${left + 1}" y="${allocationY}" width="${Math.max(
            1,
            itemWidth - 2,
          )}" height="${Math.max(0, plotBottom - allocationY)}" />
          <rect class="hit" x="${left}" y="22" width="${Math.max(2, itemWidth)}" height="${plotBottom - 22}" />
        </g>`;
      })
      .join("");

    const pricePoints = valid
      .map((item) => `${(x(item.startMs) + x(item.endMs)) / 2},${yPrice(item.electricity_cost_per_kwh)}`)
      .join(" ");
    const tickCount = width < 430 ? 4 : 7;
    const ticks = Array.from({ length: tickCount }, (_, index) => {
      const time = start + (span * index) / (tickCount - 1);
      const px = x(time);
      return `<line class="grid-line" x1="${px}" x2="${px}" y1="${plotTop}" y2="${plotBottom}" />
        <text class="axis-label" text-anchor="${index === 0 ? "start" : index === tickCount - 1 ? "end" : "middle"}" x="${px}" y="${height - 14}">${escapeHtml(
          new Intl.DateTimeFormat(this._hass?.language, { hour: "2-digit", minute: "2-digit" }).format(new Date(time)),
        )}</text>`;
    }).join("");
    const energyTicks = [0, maxEnergy / 2, maxEnergy]
      .map((value) => `<text class="axis-label" text-anchor="end" x="${margin.left - 6}" y="${yEnergy(value) + 4}">${escapeHtml(this._number(value, 1))}</text>`)
      .join("");
    const nowX = now >= start && now <= end ? x(now) : undefined;
    const nowLine = nowX
      ? `<line class="now-line" x1="${nowX}" x2="${nowX}" y1="20" y2="${plotBottom}" /><text class="now-label" text-anchor="middle" x="${nowX}" y="${plotTop + 12}">${escapeHtml(this._t.now)}</text>`
      : "";
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(this._t.title)}">
      <defs>
        <pattern id="reserve-pattern" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="3" height="6" class="reserve-stripe"></rect>
        </pattern>
      </defs>
      ${ticks}${dayLines.join("")}
      <line class="baseline" x1="${margin.left}" x2="${width - margin.right}" y1="${plotBottom}" y2="${plotBottom}" />
      ${energyTicks}
      <text class="axis-title" transform="translate(12 ${plotTop + plotHeight / 2}) rotate(-90)" text-anchor="middle">kWh</text>
      <text class="axis-label" text-anchor="start" x="${width - margin.right + 5}" y="${plotTop + 4}">${escapeHtml(this._number(maxPrice, 2))}</text>
      <text class="axis-label" text-anchor="start" x="${width - margin.right + 5}" y="${plotBottom}">${escapeHtml(this._number(minPrice, 2))}</text>
      ${bars}
      <polyline class="price-line" points="${pricePoints}" />
      ${nowLine}
    </svg>`;
  }

  _renderSelection() {
    const item = this._plan?.intervals?.[this._selected];
    if (!item) return `<span class="hint">${escapeHtml(this._t.select)}</span>`;
    const fields = [
      [this._t.period, `${this._dateTime(item.start, true)}–${this._dateTime(item.end)}`],
      [this._t.action, this._recommendationLabel(item.recommendation)],
      [this._t.allocation, `${this._number(item.allocated_energy_kwh)} kWh`],
      [this._t.demand, `${this._number(item.heat_demand_kwh)} kWh`],
      [this._t.price, `${this._number(item.electricity_cost_per_kwh, 4)}/kWh`],
      [this._t.cop, this._number(item.cop, 2)],
      [this._t.value, `${this._number(item.adjusted_heat_value_per_kwh, 4)}/kWh`],
      [this._t.saving, this._number(item.expected_avoided_cost)],
    ];
    return fields
      .map(([label, value]) => `<span><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></span>`)
      .join("");
  }

  _renderTable(intervals) {
    return `<table>
      <thead><tr><th>${escapeHtml(this._t.period)}</th><th>${escapeHtml(this._t.action)}</th><th>${escapeHtml(
        this._t.allocation,
      )}</th><th>${escapeHtml(this._t.demand)}</th><th>${escapeHtml(this._t.price)}</th><th>${escapeHtml(
        this._t.cop,
      )}</th><th>${escapeHtml(this._t.value)}</th><th>${escapeHtml(this._t.saving)}</th></tr></thead>
      <tbody>${intervals
        .map(
          (item) => `<tr><td>${escapeHtml(this._dateTime(item.start, true))}–${escapeHtml(
            this._dateTime(item.end),
          )}</td><td>${escapeHtml(this._recommendationLabel(item.recommendation))}</td><td>${escapeHtml(
            this._number(item.allocated_energy_kwh),
          )} kWh</td><td>${escapeHtml(this._number(item.heat_demand_kwh))} kWh</td><td>${escapeHtml(
            this._number(item.electricity_cost_per_kwh, 4),
          )}</td><td>${escapeHtml(this._number(item.cop, 2))}</td><td>${escapeHtml(
            this._number(item.adjusted_heat_value_per_kwh, 4),
          )}</td><td>${escapeHtml(this._number(item.expected_avoided_cost))}</td></tr>`,
        )
        .join("")}</tbody>
    </table>`;
  }
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
  :host { display: block; }
  ha-card { padding: 16px; color: var(--primary-text-color); overflow: hidden; }
  .header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
  .title { font-size: 20px; font-weight: 500; }
  .status { display: inline-block; margin-top: 5px; font-size: 12px; color: var(--secondary-text-color); }
  .status-saved_plan { color: var(--warning-color); font-weight: 500; }
  .status-invalid { color: var(--error-color); font-weight: 500; }
  .recalculate { display: inline-flex; align-items: center; gap: 7px; min-height: 40px; padding: 7px 11px; border: 1px solid var(--divider-color); border-radius: 10px; background: transparent; color: var(--primary-text-color); cursor: pointer; font: inherit; }
  .recalculate:hover { background: color-mix(in srgb, var(--primary-color) 10%, transparent); }
  .recalculate:disabled { cursor: wait; opacity: .55; }
  .recalculate ha-icon { --mdc-icon-size: 19px; }
  .metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 15px; }
  .metric { min-width: 0; padding: 10px; border-radius: 10px; background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); }
  .metric span, .metric strong { display: block; overflow-wrap: anywhere; }
  .metric span { color: var(--secondary-text-color); font-size: 12px; margin-bottom: 5px; }
  .metric strong { font-size: 15px; font-weight: 500; }
  .legend { display: flex; flex-wrap: wrap; gap: 8px 15px; color: var(--secondary-text-color); font-size: 12px; margin-bottom: 4px; }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .legend i { display: inline-block; width: 15px; height: 8px; }
  .legend-use { background: var(--success-color); }
  .legend-reserve { background: repeating-linear-gradient(135deg, var(--warning-color) 0 2px, transparent 2px 5px); }
  .legend-demand { border: 1px solid var(--secondary-text-color); background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); box-sizing: border-box; }
  .legend-price { height: 0 !important; border-top: 2px solid var(--primary-color); }
  .chart-wrap { width: 100%; min-height: 220px; }
  svg { display: block; width: 100%; height: auto; overflow: visible; }
  svg text { fill: var(--secondary-text-color); font-size: 11px; }
  .axis-title { fill: var(--primary-text-color); }
  .grid-line, .day-line, .baseline { stroke: var(--divider-color); stroke-width: 1; }
  .grid-line { opacity: .55; }
  .day-line { stroke-width: 2; }
  .date-label { fill: var(--primary-text-color); font-weight: 500; }
  .demand-bar { fill: color-mix(in srgb, var(--primary-text-color) 8%, transparent); stroke: var(--secondary-text-color); stroke-width: .7; }
  .allocation-bar { fill: var(--success-color); opacity: .82; }
  .action-band { fill: url(#reserve-pattern); }
  .use .action-band { fill: var(--success-color); }
  .reserve-stripe { fill: var(--warning-color); opacity: .9; }
  .hit { fill: transparent; cursor: pointer; }
  .selected .demand-bar { stroke: var(--primary-color); stroke-width: 2; }
  .price-line { fill: none; stroke: var(--primary-color); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; pointer-events: none; }
  .now-line { stroke: var(--error-color); stroke-width: 1.5; }
  .now-label { fill: var(--error-color); font-weight: 500; }
  .selection { min-height: 42px; display: flex; flex-wrap: wrap; gap: 9px 18px; padding: 10px 0 12px; border-bottom: 1px solid var(--divider-color); }
  .selection > span { display: flex; flex-direction: column; }
  .selection small { color: var(--secondary-text-color); font-size: 11px; }
  .selection strong { font-size: 13px; font-weight: 500; }
  .selection .hint { display: block; color: var(--secondary-text-color); font-size: 13px; align-self: center; }
  details { padding-top: 10px; }
  summary { min-height: 40px; line-height: 40px; cursor: pointer; font-weight: 500; }
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; white-space: nowrap; }
  th, td { padding: 8px 10px; border-bottom: 1px solid var(--divider-color); text-align: right; }
  th { color: var(--secondary-text-color); font-weight: 500; }
  th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
  .empty { padding: 28px 4px; color: var(--secondary-text-color); }
  .empty.is-error { color: var(--error-color); }
  @media (max-width: 600px) {
    ha-card { padding: 12px; }
    .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .header { align-items: center; }
    .recalculate span { display: none; }
    .recalculate { min-width: 42px; justify-content: center; padding: 7px; }
  }
`;

if (!customElements.get(CARD_TAG)) customElements.define(CARD_TAG, ThermalStoragePlanCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: CARD_TAG,
  name: "Thermal Storage Plan",
  description: "Hourly use/reserve plan for Thermal Storage Optimizer",
  preview: true,
});
