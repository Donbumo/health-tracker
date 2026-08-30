(() => {
  "use strict";

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
  const selectedBodyMetric = () => {
    const metrics = objectRows(payload?.body?.metrics);
    const key = bodyMetricSelect?.value || payload?.body?.default_metric;
    return metrics.find((item) => item.key === key) || metrics[0] || null;
  };

  const configs = {
    energy: () => ({
      rows: objectRows(payload?.trends?.energy),
      x: "date",
      unit: "kcal",
      zero: true,
      series: [
        { key: "consumed", label: "Consumidas", type: "bar", className: "chart-series-intake" },
        { key: "expended", label: "Gastadas", type: "bar", className: "chart-series-expenditure" },
        { key: "balance", label: "Balance (déficit − / superávit +)", type: "balance", className: "chart-series-balance" },
        { key: "consumed_rolling_7d", label: "Media consumo", type: "line", className: "chart-line-intake" },
        { key: "expended_rolling_7d", label: "Media gasto", type: "line", className: "chart-line-expenditure chart-line-dashed" },
      ],
    }),
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
      rows.some((row) => numeric(row[series.key]) !== null)
    );
    const values = availableSeries.flatMap((series) =>
      rows.map((row) => numeric(row[series.key])).filter((value) => value !== null)
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
    if (minimum < 0 && maximum > 0) {
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

    const barSeries = availableSeries.filter((series) => series.type === "bar");
    availableSeries.forEach((series) => {
      if (series.type === "bar" || series.type === "balance") {
        const regularIndex = barSeries.indexOf(series);
        const regularWidth = Math.max(2, Math.min(22, (slot * 0.68) / Math.max(barSeries.length, 1)));
        const balanceWidth = Math.max(2, Math.min(6, slot * 0.12));
        rows.forEach((row, rowIndex) => {
          const value = numeric(row[series.key]);
          if (value === null) return;
          const zeroY = y(0);
          const valueY = y(value);
          const barWidth = series.type === "balance" ? balanceWidth : regularWidth;
          const barX = series.type === "balance"
            ? x(rowIndex) + slot * 0.34 - barWidth
            : x(rowIndex) - (regularWidth * barSeries.length) / 2 + regularIndex * regularWidth;
          const signClass = series.type === "balance"
            ? (value < 0 ? "chart-bar-balance-deficit" : "chart-bar-balance-surplus")
            : series.className;
          const rect = svgNode("rect", {
            x: barX,
            y: Math.min(zeroY, valueY),
            width: Math.max(1, barWidth - 1),
            height: Math.max(1, Math.abs(zeroY - valueY)),
            class: `chart-bar ${signClass}`,
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
        const value = numeric(row[series.key]);
        if (value === null) return;
        const point = svgNode("circle", {
          cx: x(rowIndex), cy: y(value), r: series.type === "point" || series.type === "point-line" ? 4.5 : 3,
          class: `chart-point ${series.className}`,
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
  renderAll();

  bodyMetricSelect?.addEventListener("change", renderAll);
  let resizeFrame = null;
  window.addEventListener("resize", () => {
    if (resizeFrame !== null) window.cancelAnimationFrame(resizeFrame);
    resizeFrame = window.requestAnimationFrame(() => {
      renderAll();
      resizeFrame = null;
    });
  }, { passive: true });
})();
