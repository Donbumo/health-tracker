(() => {
  "use strict";

  const ENERGY_SERIES_KEYS = Object.freeze([
    "consumed",
    "expended",
    "balance",
    "consumed_rolling_7d",
    "expended_rolling_7d",
  ]);
  const ENERGY_FOCUS_PRESETS = Object.freeze({
    all: { visibleKeys: ENERGY_SERIES_KEYS, balanceSign: "all" },
    bars: { visibleKeys: ["consumed", "expended", "balance"], balanceSign: "all" },
    lines: { visibleKeys: ["consumed_rolling_7d", "expended_rolling_7d"], balanceSign: "all" },
    balance: { visibleKeys: ["balance"], balanceSign: "all" },
    deficit: { visibleKeys: ["balance"], balanceSign: "deficit" },
    surplus: { visibleKeys: ["balance"], balanceSign: "surplus" },
  });

  const energyFocusState = (focus) => {
    const preset = ENERGY_FOCUS_PRESETS[focus] || ENERGY_FOCUS_PRESETS.all;
    return { visibleKeys: [...preset.visibleKeys], balanceSign: preset.balanceSign };
  };
  const toggleEnergySeries = (visibleKeys, key) => {
    const visible = new Set(visibleKeys);
    if (visible.has(key)) visible.delete(key);
    else if (ENERGY_SERIES_KEYS.includes(key)) visible.add(key);
    return ENERGY_SERIES_KEYS.filter((seriesKey) => visible.has(seriesKey));
  };
  const filterBalanceValue = (value, balanceSign) => {
    if (balanceSign === "deficit" && value >= 0) return null;
    if (balanceSign === "surplus" && value <= 0) return null;
    return value;
  };
  const calculateBarLayout = (slotWidth, barCount) => {
    if (!Number.isFinite(slotWidth) || slotWidth <= 0 || barCount <= 0) return [];
    const bandWidth = Math.min(slotWidth * 0.74, 72);
    const gap = barCount > 1 ? Math.min(3, slotWidth * 0.06) : 0;
    const width = Math.max(0.5, Math.min(22, (bandWidth - gap * (barCount - 1)) / barCount));
    const groupWidth = width * barCount + gap * (barCount - 1);
    return Array.from({ length: barCount }, (_, index) => ({
      width,
      offset: -groupWidth / 2 + index * (width + gap),
    }));
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      ENERGY_SERIES_KEYS,
      calculateBarLayout,
      energyFocusState,
      filterBalanceValue,
      toggleEnergySeries,
    };
  }
  if (typeof document === "undefined") return;

  const dataNode = document.getElementById("dashboard-chart-data");
  if (!dataNode) return;

  const containers = [...document.querySelectorAll("[data-dashboard-chart]")];
  let payload;
  try {
    payload = JSON.parse(dataNode.textContent || "{}");
  } catch (_error) {
    payload = null;
  }

  const objectRows = (value) =>
    Array.isArray(value)
      ? value.filter((row) => row && typeof row === "object" && !Array.isArray(row))
      : [];
  const numeric = (value) => {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const format = (value) => {
    const parsed = numeric(value);
    if (parsed === null) return "Sin datos";
    const magnitude = Math.abs(parsed);
    return new Intl.NumberFormat("es-MX", {
      maximumFractionDigits: magnitude >= 100 ? 0 : magnitude >= 10 ? 1 : 2,
    }).format(parsed);
  };
  const svgNode = (name, attributes = {}) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  };
  const textNode = (svg, value, x, y, className, anchor = "start") => {
    const node = svgNode("text", { x, y, class: className, "text-anchor": anchor });
    node.textContent = value;
    svg.appendChild(node);
  };

  const bodyMetricSelect = document.querySelector("[data-body-metric-select]");
  const energyControls = document.querySelector("[data-energy-chart-controls]");
  const initialEnergyState = energyFocusState("all");
  const energyState = {
    visibleKeys: new Set(initialEnergyState.visibleKeys),
    balanceSign: initialEnergyState.balanceSign,
    focus: "all",
  };
  const selectedBodyMetric = () => {
    const metrics = objectRows(payload?.body?.metrics);
    const key = bodyMetricSelect?.value || payload?.body?.default_metric;
    return metrics.find((item) => item.key === key) || metrics[0] || null;
  };

  const configs = {
    energy: () => {
      const series = [
        { key: "consumed", label: "Consumidas", type: "bar", className: "chart-series-intake" },
        { key: "expended", label: "Gastadas", type: "bar", className: "chart-series-expenditure" },
        { key: "balance", label: "Balance (déficit − / superávit +)", type: "balance", className: "chart-series-balance" },
        { key: "consumed_rolling_7d", label: "Media consumo", type: "line", className: "chart-line-intake" },
        { key: "expended_rolling_7d", label: "Media gasto", type: "line", className: "chart-line-expenditure chart-line-dashed" },
      ];
      return {
        rows: objectRows(payload?.trends?.energy),
        x: "date",
        unit: "kcal",
        zero: true,
        balanceSign: energyState.balanceSign,
        series: series.filter((item) => energyState.visibleKeys.has(item.key)),
      };
    },
    weight: () => ({
      rows: objectRows(payload?.trends?.weight),
      x: "recorded_at",
      unit: payload?.units?.weight || "kg",
      zero: false,
      series: [
        { key: "value", label: "Medición real", type: "point", className: "chart-series-0" },
        { key: "moving_average_7d", label: "Media móvil 7 días", type: "line", className: "chart-series-1" },
      ],
    }),
    body: () => {
      const metric = selectedBodyMetric();
      return {
        rows: objectRows(metric?.points),
        x: "recorded_at",
        unit: metric?.unit || "",
        zero: false,
        series: [
          { key: "value", label: metric?.label || "Composición", type: "point-line", className: "chart-series-0" },
        ],
      };
    },
    activity: () => ({
      rows: objectRows(payload?.trends?.activity),
      x: "date",
      unit: "pasos",
      zero: true,
      series: [
        { key: "steps", label: "Pasos", type: "bar", className: "chart-series-0" },
        { key: "step_goal", label: "Meta", type: "line", className: "chart-series-2 chart-line-dashed" },
      ],
    }),
    training: () => ({
      rows: objectRows(payload?.trends?.training),
      x: "label",
      unit: "sesiones",
      zero: true,
      series: [
        { key: "sessions", label: "Sesiones", type: "bar", className: "chart-series-0" },
        { key: "planned", label: "Planeadas", type: "bar", className: "chart-series-1" },
      ],
    }),
  };

  const tooltipFor = (kind, row, series, value, unit) => {
    const label = row.date || row.recorded_at || row.label || "Punto";
    if (kind === "energy") {
      const sources = objectRows(row.sources).length ? row.sources.join(", ") : (Array.isArray(row.sources) ? row.sources.join(", ") : "Sin fuente");
      return `${label}. Consumidas: ${format(row.consumed)} kcal. Gastadas: ${format(row.expended)} kcal. Balance: ${format(row.balance)} kcal. Media consumo: ${format(row.consumed_rolling_7d)} kcal (${row.consumed_rolling_7d_days || 0} días con dato). Media gasto: ${format(row.expended_rolling_7d)} kcal (${row.expended_rolling_7d_days || 0} días con dato). Fuente: ${sources || "Sin fuente"}.`;
    }
    if (kind === "activity") {
      const sources = Array.isArray(row.sources) && row.sources.length ? row.sources.join(", ") : "Sin fuente";
      return `${label}. Pasos: ${format(row.steps)}. Meta: ${format(row.step_goal)}. Distancia: ${format(row.distance_km)} km. Calorías activas: ${format(row.active_calories)} kcal. Fuente: ${sources}.`;
    }
    const source = row.source ? ` Fuente: ${row.source}.` : "";
    const displayUnit = unit === "sesiones" && Number(value) === 1 ? "sesión" : unit;
    return `${label}. ${series.label}: ${format(value)}${displayUnit ? ` ${displayUnit}` : ""}.${source}`;
  };

  const addInteractiveLabel = (node, tooltip, tooltipNode) => {
    node.setAttribute("tabindex", "0");
    node.setAttribute("role", "img");
    node.setAttribute("aria-label", tooltip);
    const title = svgNode("title");
    title.textContent = tooltip;
    node.appendChild(title);
    const reveal = () => { tooltipNode.textContent = tooltip; };
    node.addEventListener("focus", reveal);
    node.addEventListener("pointerenter", reveal);
    node.addEventListener("click", reveal);
  };

  const seriesValue = (row, series, config) => {
    const value = numeric(row[series.key]);
    if (value === null) return null;
    if (series.key === "balance") {
      return filterBalanceValue(value, config.balanceSign || "all");
    }
    return value;
  };

  const render = (container, kind, index) => {
    const config = configs[kind]?.();
    container.replaceChildren();
    if (!payload || !config) {
      const error = document.createElement("p");
      error.className = "chart-empty";
      error.textContent = "No se pudieron cargar los datos del gráfico.";
      container.appendChild(error);
      return;
    }

    const rows = config.rows;
    const availableSeries = config.series.filter((series) =>
      rows.some((row) => seriesValue(row, series, config) !== null)
    );
    const values = availableSeries.flatMap((series) =>
      rows.map((row) => seriesValue(row, series, config)).filter((value) => value !== null)
    );
    if (!values.length) {
      const empty = document.createElement("p");
      empty.className = "chart-empty";
      empty.textContent = "No hay datos suficientes para dibujar esta serie.";
      container.appendChild(empty);
      return;
    }

    const measuredWidth = Math.round(container.getBoundingClientRect().width || 720);
    const width = Math.max(300, Math.min(1180, measuredWidth));
    const primary = container.classList.contains("dashboard-chart-primary");
    const compact = container.classList.contains("compact-chart");
    const height = primary ? 390 : compact ? 250 : 300;
    const margin = { top: 24, right: 16, bottom: 48, left: width < 430 ? 48 : 62 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    let minimum = Math.min(...values);
    let maximum = Math.max(...values);
    if (config.zero) {
      minimum = Math.min(0, minimum);
      maximum = Math.max(0, maximum);
    }
    if (minimum === maximum) {
      const pad = minimum === 0 ? 1 : Math.abs(minimum) * 0.12;
      minimum -= config.zero && minimum === 0 ? 0 : pad;
      maximum += pad;
    } else {
      const pad = (maximum - minimum) * 0.08;
      minimum -= config.zero && minimum === 0 ? 0 : pad;
      maximum += pad;
    }
    const slot = plotWidth / Math.max(rows.length, 1);
    const x = (rowIndex) => margin.left + slot * rowIndex + slot / 2;
    const y = (value) => margin.top + ((maximum - value) / (maximum - minimum)) * plotHeight;

    const tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip";
    tooltip.setAttribute("role", "status");
    tooltip.setAttribute("aria-live", "polite");
    tooltip.textContent = "Selecciona un punto para consultar el detalle.";

    const titleId = `dashboard-chart-title-${index}`;
    const svg = svgNode("svg", {
      viewBox: `0 0 ${width} ${height}`,
      role: "img",
      "aria-labelledby": titleId,
      class: "trend-svg",
    });
    const title = svgNode("title", { id: titleId });
    title.textContent = availableSeries.map((series) => series.label).join(", ");
    svg.appendChild(title);

    for (let tick = 0; tick <= 4; tick += 1) {
      const ratio = tick / 4;
      const value = maximum - (maximum - minimum) * ratio;
      const lineY = margin.top + plotHeight * ratio;
      svg.appendChild(svgNode("line", { x1: margin.left, x2: width - margin.right, y1: lineY, y2: lineY, class: "chart-grid-line" }));
      textNode(svg, format(value), margin.left - 8, lineY + 4, "chart-axis-label", "end");
    }
    if (config.zero && minimum <= 0 && maximum >= 0) {
      svg.appendChild(svgNode("line", { x1: margin.left, x2: width - margin.right, y1: y(0), y2: y(0), class: "chart-zero-line" }));
    }

    const maxLabels = width < 430 ? 3 : width < 760 ? 4 : 6;
    const labelIndexes = [...new Set(Array.from({ length: Math.min(maxLabels, rows.length) }, (_, labelIndex) =>
      Math.round((labelIndex * (rows.length - 1)) / Math.max(1, Math.min(maxLabels, rows.length) - 1))
    ))];
    labelIndexes.forEach((rowIndex) => {
      const raw = String(rows[rowIndex]?.[config.x] || "");
      const label = raw.length > 15 ? `${raw.slice(0, 10)}…` : raw;
      const anchor = rowIndex === 0 ? "start" : rowIndex === rows.length - 1 ? "end" : "middle";
      textNode(svg, label, x(rowIndex), height - 15, "chart-axis-label", anchor);
    });

    const barSeries = availableSeries.filter((series) => series.type === "bar" || series.type === "balance");
    const barLayout = calculateBarLayout(slot, barSeries.length);
    availableSeries.forEach((series) => {
      if (series.type === "bar" || series.type === "balance") {
        const layout = barLayout[barSeries.indexOf(series)];
        rows.forEach((row, rowIndex) => {
          const value = seriesValue(row, series, config);
          if (value === null) return;
          const zeroY = y(0);
          const valueY = y(value);
          const signClass = series.type === "balance"
            ? (value < 0 ? "chart-bar-balance-deficit" : "chart-bar-balance-surplus")
            : series.className;
          const rect = svgNode("rect", {
            x: x(rowIndex) + layout.offset,
            y: Math.min(zeroY, valueY),
            width: layout.width,
            height: Math.max(1, Math.abs(zeroY - valueY)),
            class: `chart-bar ${signClass}`,
            "data-series": series.key,
            "data-row-index": rowIndex,
            "data-value": value,
          });
          addInteractiveLabel(rect, tooltipFor(kind, row, series, value, config.unit), tooltip);
          svg.appendChild(rect);
        });
        return;
      }

      const drawsLine = series.type === "line" || series.type === "point-line";
      if (drawsLine) {
        let segment = [];
        const flush = () => {
          if (segment.length >= 2) {
            svg.appendChild(svgNode("path", {
              d: segment.map((point, pointIndex) => `${pointIndex ? "L" : "M"} ${point.x} ${point.y}`).join(" "),
              class: `chart-line ${series.className}`,
            }));
          }
          segment = [];
        };
        rows.forEach((row, rowIndex) => {
          const value = numeric(row[series.key]);
          if (value === null) flush();
          else segment.push({ x: x(rowIndex), y: y(value) });
        });
        flush();
      }

      rows.forEach((row, rowIndex) => {
        const value = seriesValue(row, series, config);
        if (value === null) return;
        const point = svgNode("circle", {
          cx: x(rowIndex), cy: y(value), r: series.type === "point" || series.type === "point-line" ? 4.5 : 3,
          class: `chart-point ${series.className}`,
          "data-series": series.key,
          "data-row-index": rowIndex,
        });
        addInteractiveLabel(point, tooltipFor(kind, row, series, value, config.unit), tooltip);
        svg.appendChild(point);
      });
    });

    const legend = document.createElement("ul");
    legend.className = "chart-legend";
    availableSeries.forEach((series) => {
      const item = document.createElement("li");
      const swatch = document.createElement("span");
      swatch.className = `chart-legend-swatch ${series.className} ${series.type === "bar" || series.type === "balance" ? "is-bar" : ""}`;
      swatch.setAttribute("aria-hidden", "true");
      item.append(swatch, document.createTextNode(series.label));
      legend.appendChild(item);
    });
    container.append(svg, legend, tooltip);
  };

  const updateEnergyControls = () => {
    if (!energyControls) return;
    energyControls.querySelectorAll("[data-energy-series-toggle]").forEach((button) => {
      const active = energyState.visibleKeys.has(button.dataset.energySeriesToggle);
      button.setAttribute("aria-pressed", String(active));
      button.classList.toggle("is-active", active);
    });
    energyControls.querySelectorAll("[data-energy-focus]").forEach((button) => {
      const active = energyState.focus === button.dataset.energyFocus;
      button.setAttribute("aria-pressed", String(active));
      button.classList.toggle("is-active", active);
    });
    const status = energyControls.querySelector("[data-energy-control-status]");
    if (status) {
      const count = energyState.visibleKeys.size;
      const sign = energyState.balanceSign === "deficit"
        ? " Solo déficit."
        : energyState.balanceSign === "surplus" ? " Solo superávit." : "";
      status.textContent = count
        ? `${count} ${count === 1 ? "serie visible" : "series visibles"}.${sign}`
        : "No hay series visibles. Activa una serie o elige un enfoque rápido.";
    }
  };

  const CHART_FADE_MS = 150; // must match the `transition: opacity 150ms ease-out;` on .dashboard-chart in app.css
  const fadeTimers = new WeakMap();
  const fadeSwap = (container, redraw) => {
    window.clearTimeout(fadeTimers.get(container));
    container.style.opacity = "0";
    const timer = window.setTimeout(() => {
      redraw();
      container.style.opacity = "1";
      fadeTimers.delete(container);
    }, CHART_FADE_MS);
    fadeTimers.set(container, timer);
  };

  const renderEnergy = () => {
    const index = containers.findIndex((container) => container.dataset.dashboardChart === "energy");
    if (index >= 0) fadeSwap(containers[index], () => render(containers[index], "energy", index));
  };

  energyControls?.querySelectorAll("[data-energy-series-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const next = toggleEnergySeries([...energyState.visibleKeys], button.dataset.energySeriesToggle);
      energyState.visibleKeys = new Set(next);
      energyState.balanceSign = "all";
      energyState.focus = "manual";
      updateEnergyControls();
      renderEnergy();
    });
  });
  energyControls?.querySelectorAll("[data-energy-focus]").forEach((button) => {
    button.addEventListener("click", () => {
      const focus = button.dataset.energyFocus;
      const next = energyFocusState(focus);
      energyState.visibleKeys = new Set(next.visibleKeys);
      energyState.balanceSign = next.balanceSign;
      energyState.focus = focus;
      updateEnergyControls();
      renderEnergy();
    });
  });

  const updateBodySummary = () => {
    const summary = document.querySelector("[data-body-current]");
    const metric = selectedBodyMetric();
    if (!summary || !metric) return;
    const unit = metric.unit ? ` ${metric.unit}` : "";
    summary.replaceChildren();
    const label = document.createElement("span");
    label.textContent = "Última medición";
    const value = document.createElement("strong");
    value.textContent = `${format(metric.latest)}${unit}`;
    const detail = document.createElement("small");
    detail.textContent = `${metric.entries} ${metric.entries === 1 ? "punto" : "puntos"}`;
    summary.append(label, value, detail);
  };

  const renderAll = () => {
    containers.forEach((container, index) => render(container, container.dataset.dashboardChart, index));
    updateBodySummary();
  };
  const renderAllAnimated = () => {
    containers.forEach((container, index) => {
      fadeSwap(container, () => render(container, container.dataset.dashboardChart, index));
    });
    updateBodySummary();
  };
  updateEnergyControls();
  renderAll();

  bodyMetricSelect?.addEventListener("change", renderAllAnimated);
  let resizeFrame = null;
  window.addEventListener("resize", () => {
    if (resizeFrame !== null) window.cancelAnimationFrame(resizeFrame);
    resizeFrame = window.requestAnimationFrame(() => {
      renderAll();
      resizeFrame = null;
    });
  }, { passive: true });
})();
