(() => {
  "use strict";

  const dataNode = document.getElementById("dashboard-chart-data");
  if (!dataNode) return;

  const chartContainers = [...document.querySelectorAll("[data-dashboard-chart]")];
  const renderPayloadError = () => {
    chartContainers.forEach((container) => {
      const error = document.createElement("p");
      error.className = "chart-empty";
      error.textContent = "No se pudieron cargar los datos del gráfico.";
      container.replaceChildren(error);
    });
  };

  let payload;
  try {
    payload = JSON.parse(dataNode.textContent || "{}");
  } catch (_error) {
    renderPayloadError();
    return;
  }

  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    renderPayloadError();
    return;
  }

  const asRows = (value) =>
    Array.isArray(value)
      ? value.filter((row) => row && typeof row === "object" && !Array.isArray(row))
      : [];

  const alignPrevious = (kind) => {
    const current = asRows(payload.trends?.[kind]);
    const previous = asRows(payload.comparison?.trends?.[kind]);
    return current.map((row, index) => {
      const prefixed = {};
      Object.entries(previous[index] || {}).forEach(([key, value]) => {
        prefixed[`previous_${key}`] = value;
      });
      return { ...row, ...prefixed };
    });
  };

  const configurations = {
    energy: {
      rows: () => alignPrevious("energy"),
      x: "date",
      unit: "kcal",
      zeroBaseline: true,
      series: [
        { key: "consumed", label: "Ingesta actual", colorIndex: 0 },
        { key: "expended", label: "Gasto actual", colorIndex: 1 },
        { key: "balance", label: "Balance actual", colorIndex: 2 },
        { key: "previous_consumed", label: "Ingesta anterior", colorIndex: 0, previous: true, x: "previous_date" },
        { key: "previous_expended", label: "Gasto anterior", colorIndex: 1, previous: true, x: "previous_date" },
        { key: "previous_balance", label: "Balance anterior", colorIndex: 2, previous: true, x: "previous_date" },
      ],
    },
    protein: {
      rows: () => alignPrevious("protein"),
      x: "date",
      unit: "g",
      zeroBaseline: true,
      series: [
        { key: "grams", label: "Proteína actual", colorIndex: 0 },
        { key: "target", label: "Objetivo actual", colorIndex: 1 },
        { key: "previous_grams", label: "Proteína anterior", colorIndex: 0, previous: true, x: "previous_date" },
        { key: "previous_target", label: "Objetivo anterior", colorIndex: 1, previous: true, x: "previous_date" },
      ],
    },
    weight: {
      rows: () => {
        const previous = asRows(payload.comparison?.trends?.weight);
        const current = asRows(payload.trends?.weight);
        return [
          ...previous.map((row) => ({
            ...row,
            previous: row.value,
            previous_moving_average_7d: row.moving_average_7d,
            value: null,
            moving_average_7d: null,
          })),
          ...current,
        ].sort((left, right) => String(left.recorded_at).localeCompare(String(right.recorded_at)));
      },
      x: "recorded_at",
      unit: payload.units?.weight || "kg",
      zeroBaseline: false,
      series: [
        { key: "value", label: "Peso actual", pointsOnly: true, colorIndex: 0 },
        { key: "moving_average_7d", label: "Media móvil actual", colorIndex: 1 },
        { key: "previous", label: "Peso anterior", pointsOnly: true, colorIndex: 0, previous: true },
        { key: "previous_moving_average_7d", label: "Media móvil anterior", colorIndex: 1, previous: true },
      ],
    },
    "training-sessions": {
      rows: () => alignPrevious("training"),
      x: "label",
      unit: "conteo",
      zeroBaseline: true,
      bars: true,
      series: [
        { key: "sessions", label: "Sesiones actuales", colorIndex: 0 },
        { key: "planned", label: "Planes actuales", colorIndex: 1 },
        { key: "previous_sessions", label: "Sesiones anteriores", colorIndex: 0, previous: true, x: "previous_label" },
        { key: "previous_planned", label: "Planes anteriores", colorIndex: 1, previous: true, x: "previous_label" },
      ],
    },
    "training-duration": {
      rows: () => alignPrevious("training"),
      x: "label",
      unit: "min",
      zeroBaseline: true,
      series: [
        { key: "duration_minutes", label: "Duración actual", colorIndex: 0 },
        { key: "previous_duration_minutes", label: "Duración anterior", colorIndex: 0, previous: true, x: "previous_label" },
      ],
    },
    "training-adherence": {
      rows: () => alignPrevious("training"),
      x: "label",
      unit: "%",
      zeroBaseline: true,
      series: [
        { key: "adherence_percent", label: "Adherencia actual", colorIndex: 0 },
        { key: "previous_adherence_percent", label: "Adherencia anterior", colorIndex: 0, previous: true, x: "previous_label" },
      ],
    },
    "training-volume": {
      rows: () => alignPrevious("training"),
      x: "label",
      unit: payload.units?.volume || "kg·reps",
      zeroBaseline: true,
      series: [
        { key: "volume", label: "Volumen actual", colorIndex: 0 },
        { key: "previous_volume", label: "Volumen anterior", colorIndex: 0, previous: true, x: "previous_label" },
      ],
    },
  };

  const numberValue = (value) => {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const svgElement = (name, attributes = {}) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  };

  const addText = (svg, text, x, y, className, anchor = "start") => {
    const node = svgElement("text", { x, y, class: className, "text-anchor": anchor });
    node.textContent = text;
    svg.appendChild(node);
  };

  const formatNumber = (value) => {
    const magnitude = Math.abs(value);
    const digits = magnitude >= 100 ? 0 : magnitude >= 10 ? 1 : 2;
    return new Intl.NumberFormat("es-MX", { maximumFractionDigits: digits }).format(value);
  };

  const renderChart = (container, kind, index) => {
    const config = configurations[kind];
    if (!config) return;
    const rows = config.rows();
    const availableSeries = config.series.filter((series) =>
      rows.some((row) => numberValue(row[series.key]) !== null)
    );
    const values = availableSeries.flatMap((series) =>
      rows.map((row) => numberValue(row[series.key])).filter((value) => value !== null)
    );

    container.replaceChildren();
    if (!values.length) {
      const empty = document.createElement("p");
      empty.className = "chart-empty";
      empty.textContent = "No hay datos suficientes para dibujar esta serie.";
      container.appendChild(empty);
      return;
    }

    const containerWidth = Math.round(container.getBoundingClientRect().width || 720);
    const width = Math.max(320, Math.min(720, containerWidth));
    const height = container.classList.contains("compact-chart") ? 220 : 280;
    const margin = { top: 24, right: 18, bottom: 44, left: 62 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    let minimum = Math.min(...values);
    let maximum = Math.max(...values);
    if (config.zeroBaseline) {
      minimum = Math.min(0, minimum);
      maximum = Math.max(0, maximum);
    }
    if (minimum === maximum) {
      const padding = minimum === 0 ? 1 : Math.abs(minimum) * 0.1;
      minimum -= padding;
      maximum += padding;
    } else {
      const padding = (maximum - minimum) * 0.08;
      minimum -= config.zeroBaseline && minimum === 0 ? 0 : padding;
      maximum += padding;
    }

    const xPosition = (rowIndex) =>
      rows.length <= 1
        ? margin.left + plotWidth / 2
        : margin.left + (rowIndex / (rows.length - 1)) * plotWidth;
    const yPosition = (value) =>
      margin.top + ((maximum - value) / (maximum - minimum)) * plotHeight;

    const titleId = `dashboard-chart-title-${index}`;
    const svg = svgElement("svg", {
      viewBox: `0 0 ${width} ${height}`,
      role: "img",
      "aria-labelledby": titleId,
      class: "trend-svg",
    });
    const title = svgElement("title", { id: titleId });
    title.textContent = `${availableSeries.map((series) => series.label).join(", ")} en ${config.unit}`;
    svg.appendChild(title);

    for (let tick = 0; tick <= 4; tick += 1) {
      const ratio = tick / 4;
      const value = maximum - (maximum - minimum) * ratio;
      const y = margin.top + plotHeight * ratio;
      svg.appendChild(svgElement("line", {
        x1: margin.left,
        x2: width - margin.right,
        y1: y,
        y2: y,
        class: "chart-grid-line",
      }));
      addText(svg, formatNumber(value), margin.left - 9, y + 4, "chart-axis-label", "end");
    }

    const labelIndexes = [...new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1])];
    labelIndexes.forEach((rowIndex) => {
      const fullLabel = String(rows[rowIndex]?.[config.x] || "");
      const label = fullLabel.length > 18
        ? `${fullLabel.slice(0, 10)}…${fullLabel.slice(-5)}`
        : fullLabel;
      const anchor = rowIndex === 0 ? "start" : rowIndex === rows.length - 1 ? "end" : "middle";
      addText(svg, label, xPosition(rowIndex), height - 14, "chart-axis-label", anchor);
    });

    availableSeries.forEach((series, seriesIndex) => {
      const colorIndex = series.colorIndex ?? seriesIndex;
      const seriesClass = `chart-series-${colorIndex}${series.previous ? " chart-previous" : ""}`;
      if (config.bars) {
        const groupWidth = Math.max(2, plotWidth / Math.max(rows.length, 1));
        const barWidth = Math.max(1, Math.min(18, (groupWidth * 0.72) / availableSeries.length));
        rows.forEach((row, rowIndex) => {
          const value = numberValue(row[series.key]);
          if (value === null) return;
          const zeroY = yPosition(Math.max(0, minimum));
          const valueY = yPosition(value);
          const x = xPosition(rowIndex) - (barWidth * availableSeries.length) / 2 + seriesIndex * barWidth;
          const rawPointLabel = row[series.x || config.x];
          const pointLabel = rawPointLabel === null || rawPointLabel === undefined || rawPointLabel === ""
            ? "Punto sin fecha"
            : String(rawPointLabel);
          const rect = svgElement("rect", {
            x,
            y: Math.min(zeroY, valueY),
            width: Math.max(1, barWidth - 1),
            height: Math.max(1, Math.abs(zeroY - valueY)),
            class: `chart-bar ${seriesClass}`,
            tabindex: 0,
            role: "img",
            "aria-label": `${pointLabel}: ${series.label}, ${formatNumber(value)} ${config.unit}`,
          });
          const tooltip = svgElement("title");
          tooltip.textContent = `${pointLabel} · ${series.label}: ${formatNumber(value)} ${config.unit}`;
          rect.appendChild(tooltip);
          svg.appendChild(rect);
        });
        return;
      }

      if (!series.pointsOnly) {
        let segment = [];
        const flushSegment = () => {
          if (!segment.length) return;
          const path = svgElement("path", {
            d: segment.map((point, pointIndex) => `${pointIndex ? "L" : "M"} ${point.x} ${point.y}`).join(" "),
            class: `chart-line ${seriesClass}`,
          });
          svg.appendChild(path);
          segment = [];
        };
        rows.forEach((row, rowIndex) => {
          const value = numberValue(row[series.key]);
          if (value === null) {
            flushSegment();
          } else {
            segment.push({ x: xPosition(rowIndex), y: yPosition(value) });
          }
        });
        flushSegment();
      }

      rows.forEach((row, rowIndex) => {
        const value = numberValue(row[series.key]);
        if (value === null) return;
        const rawPointLabel = row[series.x || config.x];
        const pointLabel = rawPointLabel === null || rawPointLabel === undefined || rawPointLabel === ""
          ? "Punto sin fecha"
          : String(rawPointLabel);
        const point = svgElement("circle", {
          cx: xPosition(rowIndex),
          cy: yPosition(value),
          r: series.pointsOnly ? 4.5 : 3,
          class: `chart-point ${seriesClass}`,
          tabindex: 0,
          role: "img",
          "aria-label": `${pointLabel}: ${series.label}, ${formatNumber(value)} ${config.unit}`,
        });
        const tooltip = svgElement("title");
        tooltip.textContent = `${pointLabel} · ${series.label}: ${formatNumber(value)} ${config.unit}`;
        point.appendChild(tooltip);
        svg.appendChild(point);
      });
    });

    const legend = document.createElement("ul");
    legend.className = "chart-legend";
    availableSeries.forEach((series, seriesIndex) => {
      const item = document.createElement("li");
      const swatch = document.createElement("span");
      const colorIndex = series.colorIndex ?? seriesIndex;
      swatch.className = `chart-legend-swatch chart-series-${colorIndex}${series.previous ? " chart-previous" : ""}`;
      swatch.setAttribute("aria-hidden", "true");
      item.append(swatch, document.createTextNode(series.label));
      legend.appendChild(item);
    });
    container.append(svg, legend);
  };

  const renderAll = () => {
    chartContainers.forEach((container, index) => {
      renderChart(container, container.dataset.dashboardChart, index);
    });
  };

  renderAll();
  if (!chartContainers.length) return;

  let resizeFrame = null;
  window.addEventListener("resize", () => {
    if (resizeFrame !== null) window.cancelAnimationFrame(resizeFrame);
    resizeFrame = window.requestAnimationFrame(() => {
      renderAll();
      resizeFrame = null;
    });
  });
})();
