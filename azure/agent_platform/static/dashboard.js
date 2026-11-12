const API_BASE = "/api";
const PAGE_SIZE = 25;
const REFRESH_INTERVAL_MS = 30_000;

const shell = document.querySelector("#app-shell");
const sidebar = document.querySelector("#sidebar");
const authNotice = document.querySelector("#auth-notice");
const views = Object.fromEntries(
  ["dashboard", "students", "profile", "alerts", "followups", "analytics", "faculties", "programs", "reports", "settings"].map((name) => [name, document.querySelector(`#view-${name}`)]),
);

let authenticated = false;
let pocEnabled = false;
let batchRunning = false;
let autoAnalyzeTried = false;
let lastDatabaseSummary = null;
let activeOperations = 0;
let pendingSyntheticCases = 0;
let selectedStudentId = null;
let currentSearch = "";
let currentOffset = 0;
let currentTotal = 0;
let dashboardData = null;
let refreshInFlight = false;
let trendRangeMonths = 12;
let programSortKey = "rate";
let programSortDescending = true;
let currentStudents = [];
let currentProfile = null;

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "same-origin",
    ...options,
    signal: options.signal,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  const text = await response.text();
  let result = {};
  try {
    result = text ? JSON.parse(text) : {};
  } catch {
    const message = /<\s*!doctype|<\s*html|<\s*body/i.test(text)
      ? `No se pudo conectar con la API (HTTP ${response.status}).`
      : text || "Respuesta no válida del servicio.";
    throw new ApiError(response.status, message);
  }
  if (!response.ok) {
    throw new ApiError(response.status, result.message || text || `La solicitud no fue aceptada (HTTP ${response.status}).`);
  }
  return result;
}

function appendText(parent, tag, text, className = "") {
  const node = document.createElement(tag);
  node.textContent = text === null || text === undefined || text === "" ? "—" : String(text);
  if (className) node.className = className;
  parent.append(node);
  return node;
}

function formatNumber(value, digits = 0) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("es-CO", { maximumFractionDigits: digits })
    : "—";
}

function setBlocked(message, showLogin = false) {
  authenticated = false;
  authNotice.className = "notice blocked";
  authNotice.hidden = false;
  authNotice.textContent = message;
  document.querySelector("#login-link").hidden = !showLogin;
  document.querySelector("#sidebar-status-dot").classList.add("offline");
  updateProcessingButtons();
}

function setReady() {
  authenticated = true;
  authNotice.className = "notice ready";
  authNotice.textContent = "";
  authNotice.hidden = true;
  document.querySelector("#login-link").hidden = true;
  document.querySelector("#sidebar-status-dot").classList.remove("offline");
  updateProcessingButtons();
}

function updateProcessingButtons() {
  const runButton = document.querySelector("#batch-run-button");
  const studentsBatchButton = document.querySelector("#students-batch-button");
  const toggleButton = document.querySelector("#poc-toggle-button");
  const analyzeButton = document.querySelector("#profile-analyze");
  if (analyzeButton) {
    analyzeButton.disabled = !authenticated || !pocEnabled || batchRunning
      || currentProfile?.student?.student_id !== selectedStudentId
      || currentProfile?.student?.status !== "pending";
  }
  const batchDisabled = !authenticated || !pocEnabled || batchRunning || pendingSyntheticCases === 0;
  if (runButton) runButton.disabled = batchDisabled;
  if (studentsBatchButton) studentsBatchButton.disabled = batchDisabled;
  if (toggleButton) {
    toggleButton.disabled = !authenticated || batchRunning || activeOperations > 0;
  }
}

function showView(name) {
  if (!views[name]) return;
  for (const [viewName, node] of Object.entries(views)) node.hidden = viewName !== name;
  document.querySelectorAll("[data-view]").forEach((button) => {
    const active = button.dataset.view === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  sidebar.classList.remove("mobile-open");
  document.querySelector("#mobile-menu").setAttribute("aria-expanded", "false");
  const loaders = {
    dashboard: loadDashboard,
    students: loadStudents,
    profile: () => selectedStudentId ? loadProfile(selectedStudentId) : showView("students"),
    alerts: loadAlerts,
    followups: loadFollowups,
    analytics: loadAnalytics,
    faculties: loadFaculties,
    programs: loadPrograms,
    reports: loadReports,
    settings: loadSettings,
  };
  loaders[name]?.();
}

function makeMetric(label, value, note, view, filter = {}) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "metric metric-link";
  appendText(card, "strong", formatNumber(value));
  appendText(card, "span", label);
  if (note) appendText(card, "small", note);
  card.addEventListener("click", () => {
    if (view === "students") {
      showView("students");
      applyQuickFilter(filter);
    } else {
      showView(view);
    }
  });
  return card;
}

function applyQuickFilter(filter) {
  for (const [key, value] of Object.entries(filter)) {
    const control = document.querySelector(`#filter-${key}`);
    if (control) {
      const option = [...control.options].find((item) => item.value === String(value) || item.textContent === String(value));
      control.value = option?.value || String(value);
    }
  }
  currentOffset = 0;
  loadStudents();
}

function renderRiskChart(selector, groups, filterType, maxItems = Infinity) {
  const container = document.querySelector(selector);
  container.replaceChildren();
  container.setAttribute("role", "group");
  container.setAttribute("aria-label", `Distribución de riesgo por ${filterType}`);
  const items = Object.entries(groups || {})
    .sort((left, right) => (right[1].total || 0) - (left[1].total || 0))
    .slice(0, maxItems);
  const maximum = Math.max(...items.map(([, value]) => value.total || 0), 1);
  for (const [label, value] of items) {
    const total = value.total || 0;
    const atRisk = value.high || 0;
    const riskPercent = total ? (atRisk / total) * 100 : 0;
    const row = document.createElement("button");
    row.type = "button";
    row.className = "bar-row";
    row.title = `Filtrar estudiantes de ${label}`;
    row.setAttribute(
      "aria-label",
      `${label}: ${formatNumber(total)} evaluados, ${formatNumber(atRisk)} en riesgo (${formatNumber(riskPercent, 1)}%). Filtrar estudiantes.`,
    );
    appendText(row, "span", label, "bar-label");
    const track = document.createElement("span");
    track.className = "bar-track";
    track.setAttribute("aria-hidden", "true");
    const scaled = document.createElement("span");
    scaled.className = "bar-scaled";
    scaled.style.width = `${(total / maximum) * 100}%`;
    const riskSegment = document.createElement("span");
    riskSegment.className = "bar-segment bar-segment-high";
    riskSegment.style.width = `${riskPercent}%`;
    const restSegment = document.createElement("span");
    restSegment.className = "bar-segment bar-segment-rest";
    restSegment.style.width = `${100 - riskPercent}%`;
    scaled.append(riskSegment, restSegment);
    track.append(scaled);
    row.append(track);
    appendText(row, "span", `${formatNumber(total)} · ${formatNumber(riskPercent, 1)}%`, "bar-value");
    row.addEventListener("click", () => applyDimensionFilter(filterType, label));
    container.append(row);
  }
  if (!items.length) appendText(container, "p", "Sin datos para esta dimensión.", "muted");
  renderChartLegend(container);
  renderChartTable(
    container,
    ["Grupo", "Evaluados", "En riesgo", "% riesgo"],
    items.map(([label, values]) => [label, values.total || 0, values.high || 0, values.total ? `${formatNumber((values.high / values.total) * 100, 1)}%` : "0%"]),
  );
}

function renderChartLegend(container) {
  const legend = document.createElement("div");
  legend.className = "chart-legend";
  legend.setAttribute("aria-label", "Leyenda de niveles de riesgo");
  for (const [label, className] of [["En riesgo", "bar-segment-high"], ["Resto de evaluados", "bar-segment-rest"]]) {
    const item = document.createElement("span");
    item.className = "legend-item";
    const swatch = document.createElement("span");
    swatch.className = `legend-swatch ${className}`;
    swatch.setAttribute("aria-hidden", "true");
    item.append(swatch, document.createTextNode(label));
    legend.append(item);
  }
  container.append(legend);
}

function renderChartTable(container, headers, rows, caption = "Datos de la gráfica") {
  const existing = container.parentElement.querySelector(":scope > .chart-data");
  existing?.remove();
  const details = document.createElement("details");
  details.className = "chart-data";
  const summary = appendText(details, "summary", "Ver datos en tabla");
  summary.setAttribute("aria-label", `${caption} en formato tabla`);
  const table = document.createElement("table");
  appendText(table, "caption", caption);
  const head = document.createElement("tr");
  for (const label of headers) appendText(head, "th", label).scope = "col";
  table.append(head);
  for (const values of rows) {
    const row = document.createElement("tr");
    for (const value of values) appendText(row, "td", typeof value === "number" ? formatNumber(value) : value);
    table.append(row);
  }
  details.append(table);
  container.after(details);
}

function applyDimensionFilter(filterType, value) {
  applyQuickFilter({ [filterType]: value });
}

function renderTrend(selector, rows) {
  const container = document.querySelector(selector);
  container.replaceChildren();
  const allPeriods = [...(rows || [])].sort((a, b) => a.period_id.localeCompare(b.period_id));
  const periods = selector === "#trend-chart" ? allPeriods.slice(-trendRangeMonths) : allPeriods;
  container.setAttribute("role", "img");
  container.setAttribute("aria-label", "Evolución mensual de estudiantes en riesgo y con seguimiento activo.");
  if (!periods.length) {
    appendText(container, "p", "No hay cortes históricos disponibles.", "muted");
    return;
  }
  const svgNs = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNs, "svg");
  svg.classList.add("trend-svg");
  svg.setAttribute("viewBox", "0 0 760 280");
  svg.setAttribute("preserveAspectRatio", "none");
  const left = 32;
  const right = 724;
  const top = 18;
  const bottom = 226;
  const maximum = Math.max(...periods.flatMap((point) => [point.high || 0, point.active_followups || 0]), 1);
  const x = (index) => left + (periods.length < 2 ? (right - left) / 2 : (index / (periods.length - 1)) * (right - left));
  const y = (value) => bottom - ((value || 0) / maximum) * (bottom - top);
  const addSvg = (name, attributes) => {
    const node = document.createElementNS(svgNs, name);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    svg.append(node);
    return node;
  };
  for (let tick = 0; tick <= 4; tick += 1) {
    const gridY = top + (tick / 4) * (bottom - top);
    addSvg("line", { x1: left, x2: right, y1: gridY, y2: gridY, class: "trend-gridline" });
  }
  const riskPoints = periods.map((point, index) => `${x(index)},${y(point.high)}`);
  const followupPoints = periods.map((point, index) => `${x(index)},${y(point.active_followups)}`);
  addSvg("path", { d: `M ${x(0)} ${bottom} L ${riskPoints.join(" L ")} L ${x(periods.length - 1)} ${bottom} Z`, class: "trend-area" });
  addSvg("polyline", { points: riskPoints.join(" "), class: "trend-line trend-line-risk" });
  addSvg("polyline", { points: followupPoints.join(" "), class: "trend-line trend-line-followups" });
  for (const [series, className] of [["high", "trend-line-risk"], ["active_followups", "trend-line-followups"]]) {
    const index = periods.length - 1;
    addSvg("circle", { cx: x(index), cy: y(periods[index][series]), r: 4, class: `${className}-point` });
    const label = addSvg("text", {
      x: right - 4,
      y: y(periods[index][series]) - (series === "high" ? 8 : -15),
      class: series === "high" ? "trend-end-label trend-end-risk" : "trend-end-label trend-end-followups",
      "text-anchor": "end",
    });
    label.textContent = `${series === "high" ? "En riesgo" : "Seguimiento"} ${formatNumber(periods[index][series] || 0)}`;
  }
  const xLabels = document.createElement("div");
  xLabels.className = "trend-axis-labels";
  const labelIndexes = new Set([0, Math.floor((periods.length - 1) / 2), periods.length - 1]);
  periods.forEach((point, index) => {
    if (labelIndexes.has(index)) appendText(xLabels, "span", point.period_id);
  });
  container.append(svg, xLabels);
  const legend = document.createElement("div");
  legend.className = "chart-legend trend-legend";
  appendText(legend, "span", "En riesgo (alto + crítico)", "legend-risk");
  appendText(legend, "span", "Con seguimiento activo", "legend-followups");
  container.append(legend);
  renderChartTable(
    container,
    ["Periodo", "En riesgo", "Seguimiento activo", "Evaluados"],
    periods.map((point) => [point.period_id, point.high || 0, point.active_followups || 0, point.total || 0]),
    "Evolución mensual del riesgo y seguimiento",
  );
}

function renderRiskDonut(data) {
  const container = document.querySelector("#risk-donut");
  container.replaceChildren();
  const total = data.total_students || 0;
  const high = data.high_risk || 0;
  const critical = data.critical_cases || 0;
  const highOnly = Math.max(0, high - critical);
  const medium = data.medium_risk || 0;
  const criticalStop = total ? (critical / total) * 100 : 0;
  const highStop = total ? ((critical + highOnly) / total) * 100 : 0;
  const mediumStop = total ? ((critical + highOnly + medium) / total) * 100 : 0;
  const donut = document.createElement("div");
  donut.className = "risk-donut";
  donut.dataset.total = `${formatNumber(total ? (high / total) * 100 : 0, 1)}%`;
  donut.dataset.caption = "alto + crítico";
  donut.style.setProperty("--critical-stop", `${criticalStop}%`);
  donut.style.setProperty("--high-stop", `${highStop}%`);
  donut.style.setProperty("--medium-stop", `${mediumStop}%`);
  donut.setAttribute("role", "img");
  donut.setAttribute(
    "aria-label",
    `Distribución: ${formatNumber(high)} alto, ${formatNumber(medium)} medio, ${formatNumber(data.low_risk || 0)} bajo, sobre ${formatNumber(total)} estudiantes.`,
  );
  const legend = document.createElement("div");
  legend.className = "risk-donut-legend";
  for (const [label, value, tone] of [
    ["Bajo", data.low_risk || 0, "low"],
    ["Medio", medium, "medium"],
    ["Alto", highOnly, "high"],
    ["Crítico", critical, "critical"],
  ]) {
    const row = document.createElement("div");
    row.className = "legend-item";
    const name = document.createElement("span");
    name.className = "legend-name";
    const swatch = document.createElement("span");
    swatch.className = `legend-dot dot-${tone}`;
    swatch.setAttribute("aria-hidden", "true");
    name.append(swatch, document.createTextNode(label));
    row.append(name);
    appendText(row, "strong", formatNumber(value));
    legend.append(row);
  }
  container.append(donut, legend);
  renderChartTable(
    container,
    ["Nivel", "Estudiantes"],
    [["Crítico", critical], ["Alto", highOnly], ["Medio", medium], ["Bajo", data.low_risk || 0]],
    "Distribución de estudiantes por nivel de riesgo",
  );
}

function renderRiskHeatmap(rows) {
  const container = document.querySelector("#risk-heatmap");
  container.replaceChildren();
  const table = document.createElement("table");
  table.className = "heatmap-table";
  const caption = appendText(table, "caption", "Cantidad en riesgo alto / total por programa y semestre");
  caption.className = "sr-only";
  const head = document.createElement("tr");
  appendText(head, "th", "Programa").scope = "col";
  const semesters = (dashboardData?.filter_options?.semesters || [1, 2, 3, 4, 5, 6, 7, 8, 9]).map(Number);
  for (const semester of semesters) {
    appendText(head, "th", `Sem. ${semester}`).scope = "col";
  }
  const thead = document.createElement("thead");
  thead.append(head);
  table.append(thead);
  const tbody = document.createElement("tbody");
  const programCodes = new Map((dashboardData?.program_faculty || []).map((item) => [item.program, item.program_code || item.program]));
  const heatMax = Math.max(0.01, ...(rows || []).flatMap((program) => Object.values(program.semesters || {}).map((counts) => (counts.total ? counts.high / counts.total : 0))));
  for (const program of rows || []) {
    const row = document.createElement("tr");
    appendText(row, "th", program.program).scope = "row";
    for (const semester of semesters) {
      const counts = program.semesters?.[String(semester)] || { total: 0, high: 0 };
      const cell = document.createElement("td");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "heatmap-cell";
      const ratio = counts.total ? counts.high / counts.total : 0;
      button.dataset.level = counts.total === 0 ? "empty" : ratio >= 0.25 ? "high" : ratio >= 0.12 ? "medium" : "low";
      button.style.setProperty("--heat", String(Math.min(1, ratio / Math.max(heatMax, 0.01))));
      button.textContent = counts.total ? `${formatNumber(ratio * 100, 0)}%` : "—";
      button.disabled = counts.total === 0;
      button.setAttribute("aria-label", `${program.program}, semestre ${semester}: ${counts.high} de ${counts.total} en riesgo alto. Filtrar estudiantes.`);
      button.addEventListener("click", () => applyQuickFilter({ program: programCodes.get(program.program), semester: String(semester) }));
      cell.append(button);
      row.append(cell);
    }
    tbody.append(row);
  }
  table.append(tbody);
  container.append(table);
  if (!rows?.length) appendText(container, "p", "Aún no hay datos para la matriz.", "muted");
}

function renderResults(reviews = []) {
  const list = document.querySelector("#results-list");
  const empty = document.querySelector("#results-empty");
  list.replaceChildren();
  empty.hidden = reviews.length > 0;
  empty.textContent = "Aún no hay análisis. Usa «Analizar casos prioritarios» para generar los primeros.";
  for (const review of reviews.slice(0, 50)) {
    const row = document.createElement("li");
    row.className = "pending-item";
    const details = document.createElement("div");
    appendText(details, "strong", review.student_id || `Resultado ${review.review_id}`);
    const band = riskBandFromProbability(review.model_probability);
    const meta = document.createElement("div");
    meta.className = "result-summary";
    meta.append(toneChip(band.tone, band.label), document.createTextNode(` ${formatNumber((review.model_probability || 0) * 100, 0)}% · ${(review.recommendation?.proposed_actions || []).length} acción(es)`));
    details.append(meta);
    const open = document.createElement("button");
    open.type = "button";
    open.className = "secondary";
    open.textContent = "Ver plan";
    open.addEventListener("click", () => review.student_id ? loadProfile(review.student_id) : loadStandaloneResult(review.review_id));
    row.append(details, open);
    list.append(row);
  }
}

async function loadStandaloneResult(reviewId) {
  try {
    const result = await api(`/reviews/${encodeURIComponent(reviewId)}`);
    selectedStudentId = null;
    showViewWithoutLoad("profile");
    document.querySelector("#profile-title").textContent = "Plan de intervención";
    document.querySelector("#profile-subtitle").textContent = "Caso sin expediente asociado.";
    document.querySelector("#profile-content").replaceChildren();
    selectProfileTab("executive");
    renderExecutive(executiveFromReview(result.review), { review: result.review });
  } catch (error) {
    setStatus("#student-list-status", error.message);
  }
}

function renderSparkline(values, color) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 100 32");
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("sparkline");
  const numbers = values.length ? values : [0, 0];
  const min = Math.min(...numbers);
  const max = Math.max(...numbers, min + 1);
  const points = numbers.map((value, index) => {
    const x = numbers.length === 1 ? 50 : (index / (numbers.length - 1)) * 96 + 2;
    const y = 28 - ((value - min) / (max - min)) * 24;
    return `${x},${y}`;
  });
  const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  line.setAttribute("points", points.join(" "));
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", color);
  line.setAttribute("stroke-width", "2");
  line.setAttribute("stroke-linecap", "round");
  line.setAttribute("stroke-linejoin", "round");
  svg.append(line);
  return svg;
}

function makeDashboardKpi(label, value, note, values, color, destination, filter = {}) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "dashboard-kpi";
  card.setAttribute("aria-label", `${label}: ${formatNumber(value)}. ${note}. Abrir detalle.`);
  const text = document.createElement("span");
  text.className = "kpi-copy";
  appendText(text, "span", label, "kpi-label");
  appendText(text, "strong", formatNumber(value), "kpi-value");
  appendText(text, "small", note, "kpi-note");
  card.append(text, renderSparkline(values, color));
  card.addEventListener("click", () => {
    showView(destination);
    if (destination === "students") applyQuickFilter(filter);
  });
  return card;
}

function renderMetrics(data) {
  const cards = document.querySelector("#aggregate-cards");
  const points = data.trend || [];
  const highRate = data.total_students ? (data.high_risk / data.total_students) * 100 : 0;
  const atRiskFollowed = data.at_risk_with_followup ?? Math.min(data.active_followups || 0, data.high_risk || 0);
  const followupCoverage = data.high_risk ? (atRiskFollowed / data.high_risk) * 100 : 0;
  const riskDelta = points.length > 1 ? (points.at(-1).high || 0) - (points.at(-2).high || 0) : 0;
  cards.replaceChildren(
    makeDashboardKpi("Estudiantes evaluados", data.total_students, `Periodo ${data.period_id || "—"}`, points.map((point) => point.total), "#068CC1", "students"),
    makeDashboardKpi("Estudiantes en riesgo (alto + crítico)", data.high_risk, `${formatNumber(highRate, 1)}% del total · ${riskDelta >= 0 ? "+" : ""}${formatNumber(riskDelta)} frente al mes anterior`, points.map((point) => point.high), "#EE0063", "students", { risk: "Alto" }),
    makeDashboardKpi("En riesgo con seguimiento", atRiskFollowed, `Cobertura ${formatNumber(followupCoverage, 1)}% de los casos en riesgo`, points.map((point) => point.active_followups), "#0DAA0D", "followups"),
    makeDashboardKpi("Alertas abiertas", data.open_alerts, `${formatNumber(data.critical_cases)} casos críticos`, points.map((point) => point.open_alerts), "#E6A51A", "alerts"),
  );
  document.querySelector("#risk-donut-total").textContent = formatNumber(data.total_students);
  const notificationCount = document.querySelector("#notification-count");
  notificationCount.textContent = data.open_alerts > 99 ? "99+" : formatNumber(data.open_alerts);
  notificationCount.hidden = !data.open_alerts;
  const alertCount = document.querySelector("#sidebar-alerts-count");
  alertCount.textContent = data.open_alerts > 99 ? "99+" : formatNumber(data.open_alerts);
  alertCount.hidden = !data.open_alerts;
  const followupCount = document.querySelector("#sidebar-followups-count");
  followupCount.textContent = data.active_followups > 99 ? "99+" : formatNumber(data.active_followups);
  followupCount.hidden = !data.active_followups;
  document.querySelector("#notifications-button").setAttribute(
    "aria-label",
    `${formatNumber(data.open_alerts)} alertas abiertas. Abrir alertas`,
  );
}

function renderProgramSummary(rows) {
  const body = document.querySelector("#program-summary-rows");
  if (!body) return;
  const sorted = [...(rows || [])].sort((a, b) => {
    const left = a[programSortKey] ?? -Infinity;
    const right = b[programSortKey] ?? -Infinity;
    return programSortDescending ? right - left : left - right;
  });
  body.replaceChildren();
  for (const program of sorted) {
    const row = document.createElement("tr");
    const nameCell = document.createElement("td");
    const nameButton = document.createElement("button");
    nameButton.type = "button";
    nameButton.className = "program-link";
    nameButton.textContent = program.program;
    nameButton.addEventListener("click", () => applyDimensionFilter("program", program.program));
    nameCell.append(nameButton);
    row.append(nameCell);
    appendText(row, "td", program.faculty);
    appendText(row, "td", formatNumber(program.total));
    appendText(row, "td", formatNumber(program.high));
    const rateCell = document.createElement("td");
    appendText(rateCell, "span", `${formatNumber(program.risk_rate, 1)}%`, `rate-pill ${program.risk_rate >= 18 ? "rate-high" : "rate-normal"}`);
    row.append(rateCell);
    appendText(row, "td", formatNumber(program.active_followups));
    body.append(row);
  }
}

async function runDashboardUpdate() {
  await refreshAll();
  if (!authenticated) {
    setBatchStatus("No hay sesión autorizada: inicia sesión para actualizar y analizar casos.");
    return;
  }
  if (!pocEnabled) {
    setBatchStatus("Datos actualizados; el análisis automático está pausado.");
  } else if (pendingSyntheticCases === 0) {
    setBatchStatus("Datos actualizados; no hay casos pendientes de análisis.");
  } else {
    setBatchStatus(`Datos actualizados; ${formatNumber(pendingSyntheticCases)} casos pendientes de análisis.`);
    await startBatch();
  }
}

const DASHBOARD_FILTERS = [
  ["campus", "#dashboard-campus-filter"],
  ["faculty", "#dashboard-faculty-filter"],
  ["program", "#dashboard-program-filter"],
  ["semester", "#dashboard-semester-filter"],
  ["risk", "#dashboard-risk-filter"],
];
const DASHBOARD_CACHE_MS = 30_000;
const dashboardCache = new Map();
let dashboardController = null;
let dashboardRequestToken = 0;
let dashboardFilterTimer = null;

function dashboardFilters() {
  return Object.fromEntries(DASHBOARD_FILTERS.map(([key, selector]) => [key, document.querySelector(selector)?.value || ""]));
}

function fillSelect(select, items, allLabel) {
  if (!select) return;
  const selected = select.value;
  select.replaceChildren(new Option(allLabel, ""));
  for (const [value, label] of items) select.add(new Option(label, value));
  select.value = [...select.options].some((option) => option.value === selected) ? selected : "";
}

function populateDashboardFilters(options = {}) {
  const faculty = document.querySelector("#dashboard-faculty-filter")?.value || "";
  fillSelect(document.querySelector("#dashboard-campus-filter"), (options.campuses || []).map((item) => [item.code, item.name]), "Todas las sedes");
  fillSelect(document.querySelector("#dashboard-faculty-filter"), (options.faculties || []).map((item) => [item.name, item.name]), "Todas las facultades");
  const programs = (options.programs || []).filter((item) => !faculty || item.faculty === faculty);
  fillSelect(document.querySelector("#dashboard-program-filter"), programs.map((item) => [item.code, item.name]), "Todos los programas");
  fillSelect(document.querySelector("#dashboard-semester-filter"), (options.semesters || []).map((value) => [String(value), `Semestre ${value}`]), "Todos los semestres");
  fillSelect(document.querySelector("#dashboard-risk-filter"), (options.risks || []).map((item) => [item.code, item.name]), "Todos los niveles");
}

function renderFilterSummary(filters) {
  const node = document.querySelector("#dashboard-filter-summary");
  const clear = document.querySelector("#dashboard-clear-filters");
  const active = DASHBOARD_FILTERS.filter(([key]) => filters[key]).length;
  if (node) node.textContent = active ? `${active} filtro${active === 1 ? "" : "s"} activo${active === 1 ? "" : "s"}` : "";
  if (clear) clear.hidden = !active;
}

function renderDashboard(result) {
  dashboardData = result;
  populateDashboardFilters(result.filter_options);
  renderMetrics(result);
  renderRiskChart("#campus-chart", result.by_campus, "campus");
  renderRiskChart("#faculty-chart", result.by_faculty, "faculty");
  renderTrend("#trend-chart", result.trend);
  renderRiskDonut(result);
  renderRiskHeatmap(result.risk_by_program_semester);
  renderProgramSummary(result.program_summary || []);
  renderResults([...(result.generated_reviews || []), ...(result.pending_reviews || [])]);
  document.querySelector("#dashboard-period").textContent = result.period_id || "—";
  document.querySelector("#dashboard-last-updated").textContent = new Date().toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
  renderFilterSummary(result.applied_filters || dashboardFilters());
  document.querySelector("#view-dashboard")?.classList.remove("is-loading");
}

async function loadDashboard({ force = false } = {}) {
  const filters = dashboardFilters();
  const key = JSON.stringify(filters);
  const cached = dashboardCache.get(key);
  const token = ++dashboardRequestToken;
  if (cached && !force && Date.now() - cached.at < DASHBOARD_CACHE_MS) {
    renderDashboard(cached.data);
    loadDashboardAlerts();
    return true;
  }
  dashboardController?.abort();
  dashboardController = new AbortController();
  document.querySelector("#view-dashboard")?.classList.add("is-loading");
  try {
    const params = new URLSearchParams(Object.entries(filters).filter(([, value]) => value));
    const [result] = await Promise.all([
      api(`/poc/dashboard?${params}`, { signal: dashboardController.signal }),
      loadStatus().catch(() => null),
    ]);
    if (token !== dashboardRequestToken) return true;
    dashboardCache.set(key, { at: Date.now(), data: result });
    if (dashboardCache.size > 40) dashboardCache.delete(dashboardCache.keys().next().value);
    setReady();
    renderDashboard(result);
    loadDashboardAlerts();
    maybeAutoAnalyze();
    return true;
  } catch (error) {
    if (error.name === "AbortError") return true;
    document.querySelector("#view-dashboard")?.classList.remove("is-loading");
    if (error.status === 404) {
      setBlocked("El servicio de datos no está disponible en este momento.");
      return false;
    }
    setBlocked(error.message || "No se pudo cargar el dashboard.", error.status === 401);
    return false;
  }
}

function scheduleDashboardReload() {
  window.clearTimeout(dashboardFilterTimer);
  dashboardFilterTimer = window.setTimeout(() => loadDashboard(), 120);
}

async function loadStatus() {
  try {
    const result = await api("/poc/status");
    const database = result.database || {};
    pocEnabled = Boolean(result.enabled);
    activeOperations = result.active_operations || 0;
    pendingSyntheticCases = database.pending || 0;
    lastDatabaseSummary = database;
    document.querySelector("#dashboard-poc-state").textContent = pocEnabled
      ? `Procesamiento ${activeOperations ? "en curso" : "disponible"}`
      : "Procesamiento pausado";
    document.querySelector("#sidebar-status-dot").classList.toggle("offline", !pocEnabled);
    const cutLabel = String(database.cut || "").replace(/^SEMANA_(\d+)$/i, "Semana $1");
    document.querySelector("#setting-period").textContent = database.period_id || "—";
    document.querySelector("#setting-cut").textContent = cutLabel || "—";
    document.querySelector("#setting-students").textContent = formatNumber(database.student_count);
    if (dashboardData) document.querySelector("#setting-critical-threshold").textContent = `${formatNumber((dashboardData.critical_probability_threshold || 0) * 100, 0)} %`;
    updateProcessingButtons();
    return result;
  } catch (error) {
    pocEnabled = false;
    updateProcessingButtons();
    throw error;
  }
}

function databaseMetric(label, value) {
  const item = document.createElement("div");
  item.className = "database-metric";
  appendText(item, "strong", formatNumber(value));
  appendText(item, "span", label);
  return item;
}

function relativeTime(timestamp) {
  if (!timestamp) return "fecha desconocida";
  const minutes = Math.max(0, Math.round((Date.now() - new Date(timestamp).getTime()) / 60_000));
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  return `hace ${Math.round(hours / 24)} d`;
}

async function loadDashboardAlerts() {
  try {
    const alertFilters = Object.fromEntries(Object.entries(dashboardData?.applied_filters || {}).filter(([, value]) => value));
    const params = new URLSearchParams({ status: "open", limit: "5", ...alertFilters });
    const { items = [] } = await api(`/poc/alerts?${params}`);
    const list = document.querySelector("#dashboard-alerts-list");
    const empty = document.querySelector("#dashboard-alerts-empty");
    list.replaceChildren();
    empty.hidden = items.length > 0;
    empty.textContent = "No hay alertas abiertas.";
    for (const alert of items) {
      const row = document.createElement("li");
      row.className = "alert-card";
      const meta = document.createElement("div");
      meta.className = "alert-meta";
      const severity = document.createElement("span");
      severity.className = `risk-badge ${alert.severity === "critical" ? "risk-critical" : "risk-alto"}`;
      severity.textContent = alert.severity === "critical" ? "Crítico" : "Alto";
      meta.append(severity);
      appendText(meta, "time", relativeTime(alert.created_at), "alert-age");
      row.append(meta);
      appendText(row, "strong", alert.title, "alert-title");
      appendText(row, "p", `${alert.student_id} · ${alert.program || "Programa"} · Sem. ${alert.semester || "—"} · ${alert.source || "Regla de score"}`, "alert-subtitle");
      const actions = document.createElement("div");
      actions.className = "alert-actions";
      addActionButton(actions, "Ver perfil 360°", "text-button", () => loadProfile(alert.student_id));
      addActionButton(actions, "Asignar responsable", "text-button", () => assignResponsible(alert.student_id));
      row.append(actions);
      list.append(row);
    }
  } catch (error) {
    document.querySelector("#dashboard-alerts-empty").textContent = error.message;
  }
}

async function refreshAll() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    const active = Object.entries(views).find(([, node]) => !node.hidden)?.[0] || "dashboard";
    if (active === "dashboard") {
      await loadDashboard({ force: true });
    } else {
      await loadStatus().catch(() => null);
      await loadViewData(active);
    }
  } finally {
    refreshInFlight = false;
  }
}

async function loadViewData(name) {
  const loaders = {
    students: loadStudents,
    profile: () => selectedStudentId ? loadProfile(selectedStudentId, { silent: true }) : Promise.resolve(),
    alerts: loadAlerts,
    followups: loadFollowups,
    analytics: loadAnalytics,
    faculties: loadFaculties,
    programs: loadPrograms,
    reports: loadReports,
    settings: loadSettings,
  };
  await loaders[name]?.();
}

function populateSelect(select, items, key, label, defaultLabel) {
  if (!select) return;
  const selected = select.value;
  select.replaceChildren(new Option(defaultLabel, ""));
  for (const item of items || []) select.add(new Option(item[label], item[key]));
  if ([...select.options].some((option) => option.value === selected)) select.value = selected;
}

function renderRiskBadge(node, student) {
  const critical = dashboardData
    && student.model_probability >= dashboardData.critical_probability_threshold;
  node.className = `risk-badge risk-${critical ? "critical" : String(student.risk_level || "none").toLowerCase()}`;
  node.textContent = critical ? "Crítico" : (student.risk_level || "Sin riesgo");
}

async function loadStudents() {
  const params = new URLSearchParams({
    search: currentSearch,
    program: document.querySelector("#filter-program").value,
    faculty: document.querySelector("#filter-faculty").value,
    city: document.querySelector("#filter-city").value,
    campus: document.querySelector("#filter-campus").value,
    semester: document.querySelector("#filter-semester").value,
    risk: document.querySelector("#filter-risk").value,
    min_probability: String(Number(document.querySelector("#filter-min-score").value || 0) / 100),
    status: document.querySelector("#filter-status").value,
    limit: String(PAGE_SIZE),
    offset: String(currentOffset),
  });
  setStatus("#student-list-status", "Cargando…");
  try {
    const result = await api(`/poc/students?${params}`);
    populateSelect(document.querySelector("#filter-program"), result.programs, "code", "name", "Todos los programas");
    populateSelect(document.querySelector("#filter-faculty"), result.faculties, "name", "name", "Todas las facultades");
    populateSelect(document.querySelector("#filter-city"), result.cities, "name", "name", "Todas las ciudades");
    populateSelect(document.querySelector("#filter-campus"), result.campuses, "code", "name", "Todas las sedes");
    document.querySelector("#students-search").value = currentSearch;
    currentTotal = result.total || 0;
    currentStudents = result.items || [];
    document.querySelector("#student-count").textContent = `${formatNumber(currentTotal)} estudiantes`;
    document.querySelector("#table-cut").textContent = `Periodo ${result.period_id || "—"} · ${String(result.cut || "").replace(/^SEMANA_(\d+)$/i, "Semana $1")}`;
    renderRiskSegmentCounts(result.risk_counts || {});
    const body = document.querySelector("#student-rows");
    body.replaceChildren();
    for (const student of result.items || []) {
      const row = document.createElement("tr");
        row.dataset.studentId = student.student_id;
        row.tabIndex = 0;
        row.setAttribute("aria-label", `Seleccionar ${student.student_id}, ${student.program}, score ${formatNumber((student.model_probability || 0) * 100, 0)}`);
      const studentCell = document.createElement("td");
      const identityWrap = document.createElement("div");
      identityWrap.className = "student-identity";
      const liveName = student.display_name || student.student_id;
      appendText(identityWrap, "span", liveName.split(" ").map((part) => part[0]).slice(0, 2).join("").toUpperCase(), "student-avatar").setAttribute("aria-hidden", "true");
      const identityText = document.createElement("span");
      identityText.className = "student-name-wrap";
      appendText(identityText, "strong", liveName, "student-name");
      appendText(identityText, "small", student.document_id || student.student_id, "student-document");
      identityWrap.append(identityText);
      studentCell.append(identityWrap);
      row.append(studentCell);
      appendText(row, "td", student.program);
      appendText(row, "td", student.city);
      appendText(row, "td", String(student.semester));
      const scoreCell = document.createElement("td");
      const scoreValue = Math.round((student.model_probability || 0) * 100);
      appendText(scoreCell, "strong", String(scoreValue), "score-value");
      const scoreTrack = document.createElement("span");
      scoreTrack.className = "score-track";
      const scoreFill = document.createElement("span");
      scoreFill.className = `score-fill ${scoreValue >= 80 ? "score-critical" : scoreValue >= 60 ? "score-high" : scoreValue >= 30 ? "score-medium" : "score-low"}`;
      scoreFill.style.width = `${scoreValue}%`;
      scoreTrack.append(scoreFill);
      scoreCell.append(scoreTrack);
      row.append(scoreCell);
      const riskCell = document.createElement("td");
      const badge = document.createElement("span");
      renderRiskBadge(badge, student);
      riskCell.append(badge);
      row.append(riskCell);
      appendText(row, "td", student.display_status || statusLabel(student.status));
      appendText(row, "td", student.last_intervention || "Sin intervención");
      row.addEventListener("click", () => loadQuickView(student));
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          loadQuickView(student);
        }
      });
      body.append(row);
    }
    if (selectedStudentId) selectStudentTableRow(selectedStudentId);
    document.querySelector("#page-label").textContent = currentTotal
      ? `Página ${Math.floor(currentOffset / PAGE_SIZE) + 1} · ${formatNumber(currentTotal)} resultados`
      : "Sin resultados";
    document.querySelector("#previous-page").disabled = currentOffset === 0;
    document.querySelector("#next-page").disabled = currentOffset + PAGE_SIZE >= currentTotal;
    document.querySelector("#students-assign-button").disabled = !selectedStudentId;
    setStatus("#student-list-status", "");
  } catch (error) {
    if (error.status === 404) {
      setStatus("#student-list-status", "No se pudo cargar el listado. Inténtalo de nuevo.");
      return;
    }
    setStatus("#student-list-status", error.message || "No se pudo cargar el listado.");
    if ([401, 403, 503].includes(error.status)) setBlocked(error.message, error.status === 401);
  }
}

function renderRiskSegmentCounts(counts) {
  for (const [id, key] of [["risk-count-all", "all"], ["risk-count-critical", "critical"], ["risk-count-high", "high"], ["risk-count-medium", "medium"], ["risk-count-low", "low"]]) {
    document.querySelector(`#${id}`).textContent = formatNumber(counts[key] || 0);
  }
}

function makeArcGauge(score, caption, className = "arc-gauge") {
  const NS = "http://www.w3.org/2000/svg";
  const value = Math.max(0, Math.min(100, score));
  const color = value >= 70 ? "var(--magenta)" : value >= 50 ? "#e07b00" : value >= 30 ? "var(--brand)" : "var(--success)";
  const wrapper = document.createElement("div");
  wrapper.className = className;
  wrapper.setAttribute("role", "img");
  wrapper.setAttribute("aria-label", `${caption}: ${value} de 100`);
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 120 120");
  svg.setAttribute("aria-hidden", "true");
  for (const [cls, dash] of [["arc-track", 75], ["arc-value", value * 0.75]]) {
    const circle = document.createElementNS(NS, "circle");
    circle.setAttribute("class", cls);
    circle.setAttribute("cx", "60");
    circle.setAttribute("cy", "60");
    circle.setAttribute("r", "48");
    circle.setAttribute("pathLength", "100");
    circle.setAttribute("stroke-dasharray", `${dash} 100`);
    circle.setAttribute("transform", "rotate(135 60 60)");
    if (cls === "arc-value") circle.setAttribute("stroke", color);
    svg.append(circle);
  }
  wrapper.append(svg);
  appendText(wrapper, "strong", String(value));
  appendText(wrapper, "span", caption);
  return wrapper;
}

async function loadQuickView(student, followup = null) {
  selectedStudentId = student.student_id;
  selectStudentTableRow(selectedStudentId);
  document.querySelector("#quickview-empty").hidden = true;
  const content = document.querySelector("#quickview-content");
  content.hidden = false;
  content.replaceChildren();
  const heading = document.createElement("div");
  heading.className = "quickview-heading";
  appendText(heading, "h2", student.display_name || student.student_id);
  if (student.document_id) appendText(heading, "p", student.document_id, "muted");
  appendText(heading, "p", `${student.program} · ${student.city} · Sem. ${student.semester}`, "muted");
  content.append(heading);
  const score = Math.round((student.model_probability || 0) * 100);
  content.append(makeArcGauge(score, "Riesgo (0–100)"));
  const risk = document.createElement("span");
  renderRiskBadge(risk, student);
  content.append(risk);
  appendText(content, "p", followup ? `Estado: ${statusLabelFollowup(followup.status)} · ${followup.action_label}` : "Sin seguimiento activo", "quickview-status");
  const actions = document.createElement("div");
  actions.className = "quickview-actions";
  addActionButton(actions, "Ver resumen ejecutivo", "", () => loadProfile(student.student_id));
  addActionButton(actions, "Registrar seguimiento", "secondary", () => createQuickFollowup(student.student_id));
  addActionButton(actions, "Asignar responsable", "secondary", () => assignResponsible(student.student_id, followup));
  content.append(actions);
  document.querySelector("#students-assign-button").disabled = false;
}

async function createQuickFollowup(studentId) {
  try {
    await api("/poc/followups", {
      method: "POST",
      body: JSON.stringify({ student_id: studentId, action: "tutoring_review" }),
    });
    await Promise.all([loadStudents(), loadDashboard()]);
    setStatus("#student-list-status", `Seguimiento de tutoría registrado para ${studentId}.`);
  } catch (error) {
    setStatus("#student-list-status", error.message);
  }
}

async function assignResponsible(studentId = selectedStudentId, existingFollowup = null) {
  if (!studentId) return;
  const owner = window.prompt("Responsable o equipo asignado:", existingFollowup?.owner || "Equipo de permanencia");
  if (!owner?.trim()) return;
  try {
    if (existingFollowup) {
      await api(`/poc/followups/${encodeURIComponent(existingFollowup.followup_id)}/status`, {
        method: "POST",
        body: JSON.stringify({ status: existingFollowup.status, owner: owner.trim() }),
      });
    } else {
      await api("/poc/followups", {
        method: "POST",
        body: JSON.stringify({ student_id: studentId, action: "academic_advisor_review", owner: owner.trim() }),
      });
    }
    await Promise.all([loadStudents(), loadDashboard()]);
    setStatus("#student-list-status", `Responsable ${owner.trim()} asignado al caso ${studentId}.`);
  } catch (error) {
    setStatus("#student-list-status", error.message);
  }
}

function statusLabel(status) {
  return ({ pending: "Pendiente de análisis", processing: "En análisis", processed: "Analizado" })[status] || status || "Sin estado";
}

function fact(label, value) {
  const wrapper = document.createElement("div");
  wrapper.className = "profile-fact";
  appendText(wrapper, "span", label);
  appendText(wrapper, "strong", value === null || value === undefined || value === "" ? "Sin dato" : value);
  return wrapper;
}

function makeProfileCard(title, rows) {
  const card = document.createElement("section");
  card.className = "panel profile-card";
  appendText(card, "h2", title);
  const list = document.createElement("ul");
  list.className = "profile-list";
  for (const [label, value] of rows) {
    const item = document.createElement("li");
    appendText(item, "span", label);
    appendText(item, "strong", value === null || value === undefined || value === "" ? "Sin dato" : value);
    list.append(item);
  }
  card.append(list);
  return card;
}

function selectProfileTab(name) {
  document.querySelectorAll("[data-profile-tab]").forEach((tab) => {
    const active = tab.dataset.profileTab === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-profile-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.profilePanel !== name;
  });
}

function renderProfileGauges(student) {
  const container = document.querySelector("#profile-gauges");
  container.replaceChildren();
  const score = Math.round((student.model_probability || 0) * 100);
  container.append(makeArcGauge(score, "Riesgo (0–100)", "arc-gauge arc-gauge-lg"));
}

let profileRequestToken = 0;

async function loadProfile(studentId, { silent = false } = {}) {
  const token = ++profileRequestToken;
  const sameProfile = currentProfile?.student?.student_id === studentId;
  const keepVisible = silent && sameProfile;
  selectedStudentId = studentId;
  showViewWithoutLoad("profile");
  if (!keepVisible) {
    selectProfileTab("executive");
    document.querySelector("#profile-title").textContent = studentId;
    document.querySelector("#profile-subtitle").textContent = "Cargando…";
    document.querySelector("#profile-content").replaceChildren();
    document.querySelector("#profile-executive").replaceChildren();
  }
  updateProfileNavigation(studentId);
  try {
    const [result, followupResult] = await Promise.all([
      api(`/poc/students/${encodeURIComponent(studentId)}`),
      api(`/poc/followups?status=all&limit=100&student_id=${encodeURIComponent(studentId)}`).catch(() => ({ items: [] })),
    ]);
    if (token !== profileRequestToken) return;
    const student = result.student;
    currentProfile = result;
    const displayName = student.display_name || student.student_id;
    document.querySelector("#profile-title").textContent = displayName;
    document.querySelector("#profile-breadcrumb").textContent = displayName;
    const liveAvatar = document.querySelector(".profile-avatar");
    if (liveAvatar) liveAvatar.textContent = displayName.replace(/[^A-Za-zÁÉÍÓÚÑáéíóúñ ]/g, " ").split(/\s+/).filter(Boolean).map((part) => part[0]).slice(0, 2).join("").toUpperCase() || "ST";
    document.querySelector("#profile-period-chip").textContent = `Matrícula ${student.period_id}`;
    renderProfileGauges(student);
    updateProcessingButtons();
    const studentFollowups = (followupResult.items || []).filter((item) => item.student_id === studentId);
    const followupChip = document.querySelector("#profile-followup-chip");
    followupChip.hidden = studentFollowups.length === 0;
    followupChip.textContent = studentFollowups.length ? `En seguimiento · ${statusLabelFollowup(studentFollowups[0].status)}` : "Sin seguimiento";
    const followupList = document.querySelector("#profile-followups-list");
    followupList.replaceChildren();
    document.querySelector("#profile-followups-empty").hidden = studentFollowups.length > 0;
    for (const followup of studentFollowups) {
      const item = document.createElement("li");
      item.className = "pending-item";
      appendText(item, "strong", followup.action_label);
      appendText(item, "span", `${statusLabelFollowup(followup.status)} · ${followup.owner} · vence ${followup.due_date}`);
      followupList.append(item);
    }
    document.querySelector("#profile-subtitle").textContent = [student.document_id || student.student_id, student.program, student.campus && `Sede ${student.campus}`, student.semester && `Semestre ${student.semester}`].filter(Boolean).join(" · ");
    const badge = document.querySelector("#profile-risk");
    renderRiskBadge(badge, student);
    const signals = result.academic_signals || [];
    const avg = (key) => signals.length ? signals.reduce((sum, item) => sum + Number(item[key] || 0), 0) / signals.length : null;
    const attendance = avg("attendance_pct");
    const grade = avg("grade");
    const atRisk = signals.filter((item) => Number(item.grade) < 3).length;
    const arrears = Number(result.finance?.arrears_months || 0);
    const metrics = document.createElement("section");
    metrics.className = "profile-metrics-grid";
    for (const [label, value, note, tone] of [
      ["Asistencia promedio", attendance === null ? "Sin dato" : `${formatNumber(attendance, 0)}%`, attendance !== null && attendance < 75 ? "▼ Por debajo del 75 %" : "Dentro de lo esperado", attendance !== null && attendance < 75 ? "negative" : "positive"],
      ["Promedio del periodo", grade === null ? "Sin dato" : formatNumber(grade, 1), atRisk ? `▼ ${atRisk} materia(s) bajo 3,0` : "Sin materias en riesgo", atRisk ? "negative" : "positive"],
      ["Acompañamiento de bienestar", result.wellbeing?.attended ? "Sí" : "No", result.wellbeing?.support_type || "Sin registro", result.wellbeing?.attended ? "positive" : "warning"],
      ["Mora en matrícula", arrears ? `${arrears} mes(es)` : "No", arrears ? `${formatNumber(result.finance?.arrears_balance_cop)} COP` : "• Al día", arrears ? "negative" : "positive"],
    ]) {
      const card = document.createElement("section");
      card.className = "panel profile-metric-card";
      appendText(card, "span", label, "profile-metric-label");
      appendText(card, "strong", String(value), "profile-metric-value");
      appendText(card, "small", note, `profile-metric-note ${tone}`);
      metrics.append(card);
    }
    const main = document.createElement("div");
    main.className = "profile-main-col";
    main.append(
      metrics,
      makeProfileCard("Información personal", [["Documento", student.document_id], ["Periodo", student.period_id], ["Modalidad", student.modality], ["Contexto familiar", student.family_context], ["Financiación", result.finance?.financing_type], ["Beca", result.finance?.has_scholarship ? "Sí" : "No"]]),
      makeProfileCard("Datos académicos", [["Programa", student.program], ["Facultad", student.faculty], ["Sede", student.campus], ["Ciudad", student.city], ["Semestre", student.semester], ["Estado del análisis", statusLabel(student.status)]]),
    );
    const courses = makeProfileCard("Materias del periodo", signals.map((signal) => [signal.course_code, `${formatNumber(signal.grade, 1)} / 5 · asistencia ${formatNumber(signal.attendance_pct, 0)}%`]));
    main.append(courses);
    const side = document.createElement("aside");
    side.className = "profile-side-col";
    const next = studentFollowups.find((item) => !["completed", "closed"].includes(item.status));
    side.append(makeProfileCard("Próxima acción", next ? [[next.action_label, ""], ["Responsable", next.owner], ["Vence", next.due_date]] : [["Sin acciones pendientes", ""]]));
    const queue = document.createElement("section");
    queue.className = "panel profile-card";
    appendText(queue, "h2", "Cola de casos prioritarios");
    const queueList = document.createElement("ul");
    queueList.className = "priority-queue";
    for (const item of currentStudents.slice(0, 5)) {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "queue-item" + (item.student_id === studentId ? " active" : "");
      button.addEventListener("click", () => loadProfile(item.student_id));
      appendText(button, "span", item.display_name || item.student_id);
      appendText(button, "strong", String(Math.round((item.model_probability || 0) * 100)));
      li.append(button);
      queueList.append(li);
    }
    queue.append(queueList);
    side.append(queue);
    const content = document.createDocumentFragment();
    content.append(main, side);
    document.querySelector("#profile-content").replaceChildren(content);
    const review = result.analysis_result?.review || null;
    renderExecutive(result.executive || (review ? executiveFromReview(review) : null), { review, signals, studentId });
  } catch (error) {
    if (error.status === 404) {
      appendText(document.querySelector("#profile-content"), "p", "No se pudo cargar el perfil. Inténtalo de nuevo en unos segundos.", "profile-loading");
      return;
    }
    appendText(document.querySelector("#profile-content"), "p", error.message || "No se pudo cargar el expediente.", "profile-loading");
    if ([401, 403, 503].includes(error.status)) setBlocked(error.message, error.status === 401);
  }
}

function updateProfileNavigation(studentId) {
  const index = currentStudents.findIndex((student) => student.student_id === studentId);
  document.querySelector("#profile-previous").disabled = index <= 0;
  document.querySelector("#profile-next").disabled = index < 0 || index >= currentStudents.length - 1;
}

function navigateProfile(delta) {
  const index = currentStudents.findIndex((student) => student.student_id === selectedStudentId);
  const next = currentStudents[index + delta];
  if (next) loadProfile(next.student_id);
}

function showViewWithoutLoad(name) {
  for (const [viewName, node] of Object.entries(views)) node.hidden = viewName !== name;
  document.querySelectorAll("[data-view]").forEach((button) => {
    const active = button.dataset.view === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  sidebar.classList.remove("mobile-open");
}

function selectStudentTableRow(studentId) {
  document.querySelectorAll("#student-rows tr").forEach((row) => {
    const rowId = row.dataset.studentId || row.querySelector(".student-id")?.textContent;
    row.classList.toggle("selected", rowId === studentId);
  });
}

const TONE_ICON = { critical: "▲", high: "◆", medium: "■", low: "●", neutral: "○" };
const ACTION_STATE = {
  done: { icon: "✓", label: "Completada" },
  in_progress: { icon: "◔", label: "En curso" },
  pending: { icon: "○", label: "Pendiente" },
};
const FALLBACK_ACTION_LABELS = {
  retention_contact: "Contacto desde permanencia",
  academic_advisor_review: "Cita con asesor académico",
  tutoring_review: "Tutoría en asignaturas críticas",
  financial_aid_review: "Evaluación de apoyo financiero",
  wellbeing_review: "Seguimiento en bienestar universitario",
};

function riskBandFromProbability(probability) {
  const p = Number(probability) || 0;
  if (p >= 0.8) return { label: "Crítico", tone: "critical" };
  if (p >= 0.6) return { label: "Alto", tone: "high" };
  if (p >= 0.3) return { label: "Medio", tone: "medium" };
  return { label: "Bajo", tone: "low" };
}

// Vista mínima cuando solo existe el resultado del análisis (sin expediente).
function executiveFromReview(review) {
  const probability = Number(review?.model_probability) || 0;
  const band = riskBandFromProbability(probability);
  const codes = [...(probability >= 0.6 ? ["retention_contact"] : []), ...(review?.recommendation?.proposed_actions || [])];
  return {
    risk: { ...band, probability_pct: Math.round(probability * 1000) / 10 },
    priority: { score: Math.round(probability * 100), label: { critical: "Inmediata", high: "Alta", medium: "Programada", low: "Monitoreo" }[band.tone], tone: band.tone },
    explanation: review?.recommendation?.summary ? { text: review.recommendation.summary, source: "consolidated" } : null,
    status: review?.status === "pending_approval" ? { label: "Plan por validar", tone: "high" } : { label: "Sin intervención", tone: "neutral" },
    factors: [],
    actions: [...new Set(codes)].filter((code) => FALLBACK_ACTION_LABELS[code]).slice(0, 4).map((code) => ({ code, label: FALLBACK_ACTION_LABELS[code], state: "pending", assignable: false })),
    timeline: [],
    analyzed: true,
    pending_validation: review?.status === "pending_approval",
  };
}

function toneChip(tone, label, className = "tone-chip") {
  const chip = document.createElement("span");
  chip.className = `${className} tone-${tone || "neutral"}`;
  appendText(chip, "span", TONE_ICON[tone] || TONE_ICON.neutral, "tone-icon").setAttribute("aria-hidden", "true");
  appendText(chip, "span", label);
  return chip;
}

function execTile(label, valueNode, foot, tone = "") {
  const tile = document.createElement("section");
  tile.className = `panel exec-tile${tone ? ` tone-${tone}` : ""}`;
  appendText(tile, "span", label, "exec-tile-label");
  const value = document.createElement("div");
  value.className = "exec-tile-value";
  value.append(valueNode);
  tile.append(value);
  if (foot) tile.append(foot);
  return tile;
}

function meter(value, tone, label) {
  const bar = document.createElement("div");
  bar.className = `exec-meter tone-${tone || "neutral"}`;
  bar.setAttribute("role", "meter");
  bar.setAttribute("aria-valuemin", "0");
  bar.setAttribute("aria-valuemax", "100");
  bar.setAttribute("aria-valuenow", String(value));
  bar.setAttribute("aria-label", label);
  bar.title = `${label}: ${value}/100`;
  const fill = document.createElement("span");
  fill.style.width = `${Math.max(2, Math.min(100, value))}%`;
  bar.append(fill);
  return bar;
}

function execCard(title, className = "") {
  const card = document.createElement("section");
  card.className = `panel exec-card ${className}`.trim();
  appendText(card, "h2", title);
  return card;
}

function renderExecutive(view, { review = null, signals = [], studentId = null } = {}) {
  const root = document.querySelector("#profile-executive");
  root.replaceChildren();
  if (!view) {
    appendText(root, "p", "Sin información disponible.", "profile-loading");
    return;
  }

  // 1. Cabecera: riesgo (nivel + probabilidad), prioridad y estado. Cada dato una sola vez.
  const kpis = document.createElement("div");
  kpis.className = "exec-kpis";
  const riskValue = document.createElement("div");
  riskValue.className = "exec-risk-value";
  riskValue.append(toneChip(view.risk.tone, view.risk.label, "exec-semaphore"));
  appendText(riskValue, "strong", `${formatNumber(view.risk.probability_pct, 0)}%`);
  kpis.append(execTile("Riesgo de abandono", riskValue, meter(Math.round(view.risk.probability_pct), view.risk.tone, "Probabilidad estimada"), view.risk.tone));
  const priority = document.createElement("div");
  priority.className = "exec-risk-value";
  appendText(priority, "strong", String(view.priority.score));
  priority.append(toneChip(view.priority.tone, view.priority.label));
  kpis.append(execTile("Prioridad de atención", priority, meter(view.priority.score, view.priority.tone, "Score de prioridad"), view.priority.tone));
  kpis.append(execTile("Estado", toneChip(view.status.tone, view.status.label, "exec-status")));
  root.append(kpis);

  // 2. Diagnóstico único (integra a todos los agentes) + evidencia, y acciones.
  const grid = document.createElement("div");
  grid.className = "exec-grid exec-grid-main";
  const diagnosis = execCard("Diagnóstico", "exec-diagnosis");
  if (view.explanation?.source === "preliminary") {
    appendText(diagnosis.querySelector("h2"), "span", "Preliminar", "exec-tag");
  }
  appendText(diagnosis, "p", view.explanation?.text || "Sin diagnóstico disponible.", "exec-explanation");
  if (view.factors.length) {
    const list = document.createElement("ul");
    list.className = "exec-factors";
    list.setAttribute("aria-label", "Evidencia");
    for (const factor of view.factors) {
      const item = document.createElement("li");
      const text = document.createElement("div");
      text.className = "exec-factor-text";
      appendText(text, "strong", factor.label);
      appendText(text, "span", factor.detail, "exec-detail");
      const tone = factor.impact >= 70 ? "critical" : factor.impact >= 50 ? "high" : "medium";
      item.append(text, meter(factor.impact, tone, `Impacto: ${factor.label}`));
      list.append(item);
    }
    diagnosis.append(list);
  }

  const actionsCard = execCard("Acciones sugeridas");
  if (view.actions.length) {
    const list = document.createElement("ul");
    list.className = "exec-checklist";
    for (const action of view.actions) {
      const state = ACTION_STATE[action.state] || ACTION_STATE.pending;
      const item = document.createElement("li");
      item.className = `exec-check state-${action.state}`;
      appendText(item, "span", state.icon, "exec-check-icon").setAttribute("aria-hidden", "true");
      appendText(item, "span", action.label, "exec-check-label");
      if (action.state === "pending" && action.assignable && studentId) {
        addActionButton(item, "Asignar", "secondary compact", () => createActionFollowup(studentId, action.code));
      } else {
        appendText(item, "span", state.label, "exec-check-state");
      }
      list.append(item);
    }
    actionsCard.append(list);
  } else {
    appendText(actionsCard, "p", "Monitoreo regular; sin acciones adicionales.", "exec-empty");
  }
  if (view.pending_validation && review?.review_id) {
    const validation = document.createElement("div");
    validation.className = "exec-validation";
    addActionButton(validation, "Validar plan", "primary-action", () => submitReviewDecision(review.review_id, "approved"));
    addActionButton(validation, "Descartar", "secondary", () => submitReviewDecision(review.review_id, "rejected"));
    actionsCard.append(validation);
  }
  grid.append(diagnosis, actionsCard);
  root.append(grid);

  // 3. Detalle por asignatura + línea de tiempo de intervenciones.
  const lower = document.createElement("div");
  lower.className = "exec-grid";
  if (signals.length) {
    const coursesCard = execCard("Asignaturas del periodo");
    const heat = document.createElement("div");
    heat.className = "exec-heatmap";
    heat.setAttribute("role", "list");
    for (const signal of signals) {
      const grade = Number(signal.grade);
      const attendance = Number(signal.attendance_pct);
      const tone = grade < 3 && attendance < 75 ? "critical" : grade < 3 ? "high" : attendance < 75 ? "medium" : "low";
      const cell = document.createElement("div");
      cell.className = `exec-heat-cell tone-${tone}`;
      cell.setAttribute("role", "listitem");
      cell.title = `${signal.course_code}: nota ${formatNumber(grade, 1)} · asistencia ${formatNumber(attendance, 0)}%`;
      appendText(cell, "span", signal.course_code, "exec-heat-code");
      appendText(cell, "strong", formatNumber(grade, 1));
      appendText(cell, "span", `${formatNumber(attendance, 0)}%`, "exec-heat-att");
      heat.append(cell);
    }
    const legend = document.createElement("p");
    legend.className = "exec-legend";
    for (const [tone, label] of [["critical", "Nota y asistencia bajas"], ["high", "Nota < 3,0"], ["medium", "Asistencia < 75%"], ["low", "En rango"]]) {
      legend.append(toneChip(tone, label, "exec-legend-item"));
    }
    coursesCard.append(heat, legend);
    lower.append(coursesCard);
  }
  const timelineCard = execCard("Intervenciones");
  if (view.timeline.length) {
    const list = document.createElement("ol");
    list.className = "exec-timeline";
    for (const event of view.timeline) {
      const item = document.createElement("li");
      appendText(item, "time", event.date);
      appendText(item, "strong", event.label);
      appendText(item, "span", [event.status, event.owner].filter(Boolean).join(" · "), "exec-detail");
      list.append(item);
    }
    timelineCard.append(list);
  } else {
    appendText(timelineCard, "p", "Sin intervenciones registradas.", "exec-empty");
  }
  lower.append(timelineCard);
  root.append(lower);
}

async function createActionFollowup(studentId, action) {
  try {
    await api("/poc/followups", { method: "POST", body: JSON.stringify({ student_id: studentId, action }) });
    await Promise.all([loadProfile(studentId, { silent: true }), loadDashboard()]);
  } catch (error) {
    setStatus("#profile-batch-status", error.message || "No se pudo asignar la acción.");
  }
}

async function submitReviewDecision(reviewId, decision) {
  const message = decision === "approved"
    ? "¿Aprobar esta propuesta? La decisión quedará auditada y podrá crear un seguimiento para revisión del equipo."
    : "¿Rechazar esta propuesta? La decisión quedará auditada y no se creará un seguimiento.";
  if (!window.confirm(message)) return;
  try {
    await api(`/reviews/${encodeURIComponent(reviewId)}/approval`, {
      method: "POST",
      body: JSON.stringify({ decision }),
    });
    if (selectedStudentId) await loadProfile(selectedStudentId);
    else await loadStandaloneResult(reviewId);
    await loadDashboard();
  } catch (error) {
    setStatus("#student-list-status", error.message || "No se pudo registrar la decisión del revisor.");
  }
}

async function loadAlerts() {
  const status = document.querySelector("#alert-status").value;
  setStatus("#alert-list-status", "Cargando…");
  try {
    const { items = [] } = await api(`/poc/alerts?status=${encodeURIComponent(status)}&limit=500`);
    const body = document.querySelector("#alert-rows");
    body.replaceChildren();
    for (const alert of items) {
      const row = document.createElement("tr");
      const student = document.createElement("td");
      const openProfile = document.createElement("button");
      openProfile.type = "button";
      openProfile.className = "row-open";
      openProfile.textContent = alert.student_id;
      openProfile.addEventListener("click", () => loadProfile(alert.student_id));
      student.append(openProfile);
      row.append(student);
      const severityCell = document.createElement("td");
      const severityBadge = document.createElement("span");
      severityBadge.className = `risk-badge ${alert.severity === "critical" ? "risk-critical" : "risk-alto"}`;
      severityBadge.textContent = alert.severity === "critical" ? "Crítico" : "Alto";
      severityCell.append(severityBadge);
      row.append(severityCell);
      appendText(row, "td", `${formatNumber(alert.model_probability * 100, 1)}%`);
      appendText(row, "td", alert.title);
      appendText(row, "td", alert.status === "resolved" ? "Resuelta" : alert.status === "acknowledged" ? "Reconocida" : "Abierta");
      const actions = document.createElement("td");
      const group = document.createElement("div");
      group.className = "action-cell";
      if (alert.status === "open") addActionButton(group, "Reconocer", "secondary", () => updateAlert(alert.alert_id, "acknowledged"));
      if (alert.status !== "resolved") addActionButton(group, "Resolver", "danger", () => updateAlert(alert.alert_id, "resolved"));
      actions.append(group);
      row.append(actions);
      body.append(row);
    }
    setStatus("#alert-list-status", `${formatNumber(items.length)} alertas`);
  } catch (error) {
    setStatus("#alert-list-status", error.message);
  }
}

async function updateAlert(alertId, status) {
  try {
    await api(`/poc/alerts/${encodeURIComponent(alertId)}/status`, { method: "POST", body: JSON.stringify({ status }) });
    await Promise.all([loadAlerts(), loadDashboard()]);
  } catch (error) {
    setStatus("#alert-list-status", error.message);
  }
}

async function loadFollowups() {
  const status = document.querySelector("#followup-status").value;
  setStatus("#followup-list-status", "Cargando…");
  try {
    const { items = [] } = await api(`/poc/followups?status=${encodeURIComponent(status)}&limit=500`);
    const body = document.querySelector("#followup-rows");
    body.replaceChildren();
    for (const followup of items) {
      const row = document.createElement("tr");
      const student = document.createElement("td");
      const open = document.createElement("button");
      open.type = "button";
      open.className = "row-open";
      open.textContent = followup.student_id;
      open.addEventListener("click", () => loadProfile(followup.student_id));
      student.append(open);
      row.append(student);
      appendText(row, "td", followup.action_label);
      appendText(row, "td", followup.owner);
      appendText(row, "td", followup.due_date);
      appendText(row, "td", statusLabelFollowup(followup.status));
      const actionCell = document.createElement("td");
      const group = document.createElement("div");
      group.className = "action-cell";
      if (followup.status === "open") addActionButton(group, "Iniciar", "secondary", () => updateFollowup(followup.followup_id, "in_progress"));
      if (followup.status !== "completed") addActionButton(group, "Completar", "", () => updateFollowup(followup.followup_id, "completed"));
      actionCell.append(group);
      row.append(actionCell);
      body.append(row);
    }
    setStatus("#followup-list-status", `${formatNumber(items.length)} seguimientos`);
  } catch (error) {
    setStatus("#followup-list-status", error.message);
  }
}

function statusLabelFollowup(status) {
  return ({ open: "Abierto", in_progress: "En curso", completed: "Completado" })[status] || status;
}

function addActionButton(parent, label, className, handler) {
  const button = document.createElement("button");
  button.type = "button";
  if (className) button.className = className;
  button.textContent = label;
  button.addEventListener("click", handler);
  parent.append(button);
}

async function updateFollowup(followupId, status) {
  try {
    await api(`/poc/followups/${encodeURIComponent(followupId)}/status`, { method: "POST", body: JSON.stringify({ status }) });
    await Promise.all([loadFollowups(), loadDashboard()]);
  } catch (error) {
    setStatus("#followup-list-status", error.message);
  }
}

async function createFollowup(form, studentId, statusSelector) {
  if (!studentId) {
    setStatus(statusSelector, "Abre primero el perfil de un estudiante.");
    return;
  }
  const data = new FormData(form);
  const payload = { student_id: studentId, action: data.get("action") };
  if (data.get("due_date")) payload.due_date = data.get("due_date");
  setStatus(statusSelector, "Guardando seguimiento…");
  try {
    const result = await api("/poc/followups", { method: "POST", body: JSON.stringify(payload) });
    form.reset();
    setStatus(statusSelector, `Seguimiento ${result.followup.followup_id} guardado como abierto.`);
    await Promise.all([loadFollowups(), loadDashboard()]);
  } catch (error) {
    setStatus(statusSelector, error.message);
  }
}

async function loadAnalytics() {
  if (!dashboardData) await loadDashboard();
  if (!dashboardData) return;
  const data = dashboardData;
  document.querySelector("#analytics-kpis").replaceChildren(
    makeMetric("Estudiantes", data.total_students, "Corte", "students"),
    makeMetric("Riesgo alto", data.high_risk, "", "students", { risk: "Alto" }),
    makeMetric("Riesgo medio", data.medium_risk, "", "students", { risk: "Medio"}),
    makeMetric("Riesgo bajo", data.low_risk, "", "students", { risk: "Bajo"}),
  );
  renderRiskChart("#analytics-program-chart", data.by_program, "program", 7);
  renderRiskChart("#analytics-city-chart", data.by_city, "city");
  renderRiskChart("#analytics-faculty-chart", data.by_faculty, "faculty");
  renderTrend("#analytics-trend-chart", data.trend);
}

async function loadFaculties() {
  if (!dashboardData) await loadDashboard();
  if (!dashboardData) return;
  const body = document.querySelector("#faculty-rows");
  body.replaceChildren();
  const mapping = dashboardData.program_faculty || [];
  for (const [faculty, values] of Object.entries(dashboardData.by_faculty || {})) {
    const programs = mapping.filter((item) => item.faculty === faculty);
    const row = document.createElement("tr");
    appendText(row, "td", faculty);
    appendText(row, "td", formatNumber(programs.length));
    appendText(row, "td", formatNumber(values.total || 0));
    appendText(row, "td", formatNumber(values.high || 0));
    appendText(row, "td", `${formatNumber((values.high || 0) * 100 / Math.max(values.total || 0, 1), 1)}%`);
    const action = document.createElement("td");
    const filter = document.createElement("button");
    filter.type = "button";
    filter.className = "row-open";
    filter.textContent = "Ver programas";
    filter.addEventListener("click", () => applyDimensionFilter("faculty", faculty));
    action.append(filter);
    row.append(action);
    body.append(row);
  }
}

async function loadPrograms() {
  if (!dashboardData) await loadDashboard();
  if (!dashboardData) return;
  const body = document.querySelector("#program-rows");
  body.replaceChildren();
  for (const program of dashboardData.program_summary || []) {
    const row = document.createElement("tr");
    appendText(row, "td", program.program);
    appendText(row, "td", program.faculty);
    appendText(row, "td", formatNumber(program.total));
    appendText(row, "td", formatNumber(program.high));
    appendText(row, "td", `${formatNumber(program.risk_rate, 1)}%`);
    appendText(row, "td", formatNumber(program.active_followups));
    const action = document.createElement("td");
    const filter = document.createElement("button");
    filter.type = "button";
    filter.className = "row-open";
    filter.textContent = "Ver estudiantes";
    filter.addEventListener("click", () => applyDimensionFilter("program", program.program));
    action.append(filter);
    row.append(action);
    body.append(row);
  }
}

async function loadReports() {
  if (!dashboardData) await loadDashboard();
  if (!dashboardData) return;
  const summary = document.querySelector("#report-summary");
  summary.replaceChildren(
    databaseMetric("Estudiantes", dashboardData.total_students),
    databaseMetric("Alertas abiertas", dashboardData.open_alerts),
    databaseMetric("Seguimientos activos", dashboardData.active_followups),
  );
}

async function exportReviews() {
  const status = document.querySelector("#report-status");
  setStatus("#report-status", "Preparando exportación…");
  try {
    const { rows = [] } = await api("/reports/reviews");
    if (!rows.length) {
      setStatus("#report-status", "No hay resultados para exportar.");
      return;
    }
    const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
    const quote = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
    const csv = [columns.map(quote).join(","), ...rows.map((row) => columns.map((key) => quote(row[key])).join(","))].join("\r\n");
    const url = URL.createObjectURL(new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "analisis_casos.csv";
    link.click();
    URL.revokeObjectURL(url);
    setStatus("#report-status", `${formatNumber(rows.length)} resultados exportados.`);
  } catch (error) {
    setStatus("#report-status", error.message);
  }
}

function downloadCsv(filename, headers, rows) {
  const quote = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const csv = [headers.map(quote).join(","), ...rows.map((row) => row.map(quote).join(","))].join("\r\n");
  const url = URL.createObjectURL(new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function exportDashboardReport() {
  if (!dashboardData) return;
  const rows = (dashboardData.program_summary || []).map((item) => [
    item.program,
    item.faculty,
    item.total,
    item.high,
    `${formatNumber(item.risk_rate, 1)}%`,
    item.active_followups,
  ]);
  downloadCsv(
    `resumen_permanencia_${dashboardData.period_id}.csv`,
    ["Programa", "Facultad", "Evaluados", "En riesgo", "% riesgo", "Seguimiento activo"],
    rows,
  );
}

async function exportStudentsCsv() {
  const base = new URLSearchParams({
    search: currentSearch,
    program: document.querySelector("#filter-program").value,
    faculty: document.querySelector("#filter-faculty").value,
    city: document.querySelector("#filter-city").value,
    campus: document.querySelector("#filter-campus").value,
    semester: document.querySelector("#filter-semester").value,
    risk: document.querySelector("#filter-risk").value,
    min_probability: String(Number(document.querySelector("#filter-min-score").value || 0) / 100),
    status: document.querySelector("#filter-status").value,
    limit: "100",
    offset: "0",
  });
  setStatus("#student-list-status", "Preparando exportación…");
  try {
    const first = await api(`/poc/students?${base}`);
    const rows = [...(first.items || [])];
    for (let offset = 100; offset < first.total; offset += 100) {
      base.set("offset", String(offset));
      const next = await api(`/poc/students?${base}`);
      rows.push(...(next.items || []));
    }
    downloadCsv(
      "estudiantes.csv",
      ["Código", "Programa", "Facultad", "Ciudad", "Semestre", "Riesgo (%)", "Nivel", "Estado"],
      rows.map((item) => [item.student_id, item.program, item.faculty, item.city, item.semester, formatNumber(item.model_probability * 100, 1), item.risk_level, item.status]),
    );
    setStatus("#student-list-status", `${formatNumber(rows.length)} estudiantes exportados.`);
  } catch (error) {
    setStatus("#student-list-status", error.message);
  }
}

function exportProfile() {
  if (!currentProfile?.student) return;
  const student = currentProfile.student;
  downloadCsv(
    `${student.student_id}_perfil.csv`,
    ["Campo", "Valor"],
    [["Código", student.student_id], ["Programa", student.program], ["Facultad", student.faculty], ["Ciudad", student.city], ["Sede", student.campus], ["Semestre", student.semester], ["Riesgo (%)", formatNumber(student.model_probability * 100, 1)], ["Riesgo", student.risk_level]],
  );
}

async function loadSettings() {
  setStatus("#settings-status", "Cargando…");
  try {
    const status = await loadStatus();
    setStatus("#settings-status", "");
  } catch (error) {
    setStatus("#settings-status", error.message);
  }
}

function setStatus(selector, message) {
  const node = document.querySelector(selector);
  if (node) node.textContent = message;
}

function maybeAutoAnalyze() {
  const database = lastDatabaseSummary;
  if (autoAnalyzeTried || batchRunning || !authenticated || !pocEnabled || !database) return;
  try { if (window.sessionStorage.getItem("autoAnalyzeDone")) return; } catch { /* almacenamiento no disponible */ }
  if (!database.pending || database.processed || database.processing) return;
  autoAnalyzeTried = true;
  startBatch({ auto: true });
}

function batchProgressText(result) {
  const progress = result.progress || {};
  if (!progress.total) return "";
  const range = typeof progress.maxProbability === "number"
    ? ` · scores ${formatNumber(progress.minProbability * 100, 1)}%–${formatNumber(progress.maxProbability * 100, 1)}%`
    : "";
  return ` ${formatNumber(progress.done)}/${formatNumber(progress.total)}${progress.failed ? ` (${formatNumber(progress.failed)} fallidos)` : ""}${range}`;
}

function setBatchStatus(message) {
  for (const selector of ["#batch-status", "#student-list-status", "#profile-batch-status"]) {
    setStatus(selector, message);
  }
  const banner = document.querySelector("#batch-status");
  if (banner) banner.hidden = !message;
}

async function pollBatch(batchId, studentId = null) {
  try {
    const result = await api(`/batches/${encodeURIComponent(batchId)}`);
    if (["Completed", "Failed", "Terminated", "Canceled"].includes(result.runtimeStatus)) {
      batchRunning = false;
      const ok = result.runtimeStatus === "Completed" && !result.failedCount;
      setBatchStatus(`${ok ? "Análisis completado" : `Lote ${result.runtimeStatus}`} · ${formatNumber(result.processedCount || 0)} procesados · ${formatNumber(result.failedCount || 0)} fallidos${batchProgressText(result) ? ` ·${batchProgressText(result)}` : ""}.`);
      updateProcessingButtons();
      await refreshAll();
      if (studentId) await loadProfile(studentId);
      else showView("dashboard");
      return;
    }
    setBatchStatus(`Agentes trabajando en paralelo (${result.runtimeStatus || "Pending"}):${batchProgressText(result) || " iniciando…"}. Puede tardar varios minutos.`);
    window.setTimeout(() => pollBatch(batchId, studentId), 3000);
  } catch (error) {
    batchRunning = false;
    setBatchStatus(`No se pudo consultar el análisis: ${error.message}`);
    updateProcessingButtons();
  }
}

async function startBatch(options = {}) {
  const studentId = typeof options?.studentId === "string" ? options.studentId : null;
  const auto = options?.auto === true;
  if (!authenticated) return setBatchStatus("No hay sesión autorizada: inicia sesión para analizar casos.");
  if (!pocEnabled) return setBatchStatus("El análisis automático está pausado. Reanúdalo desde el Dashboard.");
  if (batchRunning) return setBatchStatus("Ya hay un análisis en curso; espera a que termine.");
  if (!studentId && pendingSyntheticCases === 0) return setBatchStatus("No hay casos pendientes de análisis.");
  const limit = Math.min(lastDatabaseSummary?.max_batch_size || 20, pendingSyntheticCases);
  const message = studentId
    ? `Se analizará ${studentId} para generar su plan de intervención. ¿Continuar?`
    : `Se analizarán hasta ${limit} casos pendientes, empezando por el mayor riesgo. El proceso tarda unos minutos. ¿Continuar?`;
  if (!auto && !window.confirm(message)) return;
  batchRunning = true;
  updateProcessingButtons();
  if (!auto) setBatchStatus("Analizando casos…");
  try {
    const body = studentId ? { student_id: studentId } : auto ? { auto: true } : { limit };
    const result = await api("/batches", { method: "POST", body: JSON.stringify(body) });
    if (auto) setBatchStatus("Analizando los casos de mayor riesgo…");
    await pollBatch(result.batchId, studentId);
  } catch (error) {
    batchRunning = false;
    updateProcessingButtons();
    if (auto) {
      // El análisis automático inicial es silencioso: si ya se hizo o hay otro en curso, no se avisa.
      try { window.sessionStorage.setItem("autoAnalyzeDone", "1"); } catch { /* almacenamiento no disponible */ }
      return;
    }
    setBatchStatus(`No se inició el análisis: ${error.message}`);
    await refreshAll();
  }
}

async function toggleProcessing() {
  if (!authenticated || batchRunning || activeOperations > 0) return;
  const enabled = !pocEnabled;
  const confirmation = enabled
    ? "¿Reanudar la capacidad de iniciar lotes? No se procesan casos hasta pulsar Procesar."
    : "¿Pausar nuevos lotes? No se borrarán registros ni resultados.";
  if (!window.confirm(confirmation)) return;
  try {
    await api("/poc/state", { method: "POST", body: JSON.stringify({ enabled }) });
    await refreshAll();
  } catch (error) {
    setStatus("#batch-status", error.message);
  }
}

function bindEvents() {
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  document.querySelectorAll("[data-view-link]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.viewLink)));
  document.querySelector("#sidebar-collapse").addEventListener("click", () => {
    const collapsed = shell.classList.toggle("sidebar-collapsed");
    document.querySelector("#sidebar-collapse").setAttribute("aria-expanded", String(!collapsed));
  });
  document.querySelector("#mobile-menu").addEventListener("click", () => {
    const opened = sidebar.classList.toggle("mobile-open");
    document.querySelector("#mobile-menu").setAttribute("aria-expanded", String(opened));
  });
  document.querySelector("#global-search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    currentSearch = document.querySelector("#global-search").value.trim();
    currentOffset = 0;
    showView("students");
  });
  document.querySelector("#dashboard-refresh")?.addEventListener("click", runDashboardUpdate);
  document.querySelector("#batch-run-button")?.addEventListener("click", () => startBatch());
  document.querySelector("#profile-analyze")?.addEventListener("click", () => {
    if (selectedStudentId) startBatch({ studentId: selectedStudentId });
  });
  for (const [key, selector] of DASHBOARD_FILTERS) {
    document.querySelector(selector)?.addEventListener("change", () => {
      if (key === "faculty") {
        populateDashboardFilters(dashboardData?.filter_options);
      }
      scheduleDashboardReload();
    });
  }
  document.querySelector("#dashboard-clear-filters")?.addEventListener("click", () => {
    for (const [, selector] of DASHBOARD_FILTERS) {
      const select = document.querySelector(selector);
      if (select) select.value = "";
    }
    populateDashboardFilters(dashboardData?.filter_options);
    scheduleDashboardReload();
  });
  document.querySelector("#dashboard-export").addEventListener("click", exportDashboardReport);
  document.querySelectorAll("[data-trend-range]").forEach((button) => button.addEventListener("click", () => {
    trendRangeMonths = Number(button.dataset.trendRange);
    document.querySelectorAll("[data-trend-range]").forEach((item) => item.classList.toggle("active", item === button));
    renderTrend("#trend-chart", dashboardData?.trend || []);
  }));
  document.querySelectorAll("[data-program-sort]").forEach((button) => button.addEventListener("click", () => {
    const key = button.dataset.programSort === "high" ? "high" : button.dataset.programSort === "total" ? "total" : "risk_rate";
    if (programSortKey === key) programSortDescending = !programSortDescending;
    else { programSortKey = key; programSortDescending = true; }
    renderProgramSummary(dashboardData?.program_summary || []);
  }));
  document.querySelector("#theme-toggle").addEventListener("click", toggleTheme);
  document.querySelector("#notifications-button").addEventListener("click", () => {
    document.querySelector("#alert-status").value = "open";
    showView("alerts");
  });
  document.querySelector("#quick-followup-button").addEventListener("click", () => {
    showView("followups");
    window.setTimeout(() => document.querySelector("#new-followup-student").focus(), 0);
  });
  document.querySelector("#students-batch-button").addEventListener("click", () => startBatch());
  document.querySelector("#students-export-button").addEventListener("click", exportStudentsCsv);
  document.querySelector("#students-assign-button").addEventListener("click", () => assignResponsible());
  document.querySelector("#student-refresh").addEventListener("click", loadStudents);
  document.querySelector("#apply-filters").addEventListener("click", () => { currentOffset = 0; loadStudents(); });
  document.querySelector("#students-search").addEventListener("input", (event) => {
    currentSearch = event.currentTarget.value.trim();
    currentOffset = 0;
    loadStudents();
  });
  document.querySelectorAll("[data-risk-segment]").forEach((button) => button.addEventListener("click", () => {
    document.querySelector("#filter-risk").value = button.dataset.riskSegment;
    document.querySelectorAll("[data-risk-segment]").forEach((item) => item.classList.toggle("active", item === button));
    currentOffset = 0;
    loadStudents();
  }));
  document.querySelector("#filter-min-score").addEventListener("input", (event) => {
    document.querySelector("#score-min-label").textContent = event.currentTarget.value;
  });
  document.querySelector("#filter-min-score").addEventListener("change", () => { currentOffset = 0; loadStudents(); });
  document.querySelector("#clear-student-filters").addEventListener("click", () => {
    for (const selector of ["#filter-campus", "#filter-program", "#filter-faculty", "#filter-city", "#filter-semester", "#filter-status", "#filter-risk"]) document.querySelector(selector).value = "";
    document.querySelector("#filter-min-score").value = "0";
    document.querySelector("#score-min-label").textContent = "0";
    document.querySelectorAll("[data-risk-segment]").forEach((item) => item.classList.toggle("active", !item.dataset.riskSegment));
    currentSearch = "";
    currentOffset = 0;
    loadStudents();
  });
  document.querySelector("#previous-page").addEventListener("click", () => { currentOffset = Math.max(0, currentOffset - PAGE_SIZE); loadStudents(); });
  document.querySelector("#next-page").addEventListener("click", () => { if (currentOffset + PAGE_SIZE < currentTotal) { currentOffset += PAGE_SIZE; loadStudents(); } });
  document.querySelector("#back-to-students").addEventListener("click", () => showView("students"));
  document.querySelector("#profile-register-followup").addEventListener("click", () => {
    selectProfileTab("followups");
    document.querySelector("#profile-followup-form").scrollIntoView({ behavior: "smooth", block: "center" });
  });
  document.querySelector("#profile-assign-responsible").addEventListener("click", () => assignResponsible());
  document.querySelector("#profile-export").addEventListener("click", exportProfile);
  document.querySelector("#profile-previous").addEventListener("click", () => navigateProfile(-1));
  document.querySelector("#profile-next").addEventListener("click", () => navigateProfile(1));
  document.querySelectorAll("[data-profile-tab]").forEach((tab) => tab.addEventListener("click", () => selectProfileTab(tab.dataset.profileTab)));
  document.querySelector("#poc-toggle-button").addEventListener("click", toggleProcessing);
  document.querySelector("#alerts-refresh").addEventListener("click", loadAlerts);
  document.querySelector("#apply-alert-filter").addEventListener("click", loadAlerts);
  document.querySelector("#followups-refresh").addEventListener("click", loadFollowups);
  document.querySelector("#apply-followup-filter").addEventListener("click", loadFollowups);
  document.querySelector("#analytics-refresh").addEventListener("click", async () => { await loadDashboard({ force: true }); await loadAnalytics(); });
  document.querySelector("#faculties-refresh").addEventListener("click", async () => { await loadDashboard({ force: true }); await loadFaculties(); });
  document.querySelector("#programs-refresh").addEventListener("click", async () => { await loadDashboard({ force: true }); await loadPrograms(); });
  document.querySelector("#settings-refresh").addEventListener("click", loadSettings);
  document.querySelector("#export-reviews").addEventListener("click", exportReviews);
  document.querySelector("#profile-followup-form").addEventListener("submit", (event) => {
    event.preventDefault();
    createFollowup(event.currentTarget, selectedStudentId, "#profile-followup-status");
  });
  document.querySelector("#new-followup-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    createFollowup(form, new FormData(form).get("student_id"), "#new-followup-status");
  });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      document.querySelector("#global-search").focus();
    }
  });
}

function initializeTheme() {
  const savedTheme = window.localStorage.getItem("fumc-theme");
  const theme = savedTheme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = theme;
  updateThemeButton(theme);
}

function enhanceStaticTables() {
  for (const table of document.querySelectorAll(".student-table")) {
    const heading = table.closest(".view")?.querySelector("h1")?.textContent || "Datos de estudiantes";
    if (!table.caption) {
      const caption = table.createCaption();
      caption.className = "sr-only";
      caption.textContent = heading;
    }
    table.querySelectorAll("thead th").forEach((cell) => { cell.scope = "col"; });
  }
}

function updateThemeButton(theme) {
  const button = document.querySelector("#theme-toggle");
  if (!button) return;
  button.setAttribute("aria-pressed", String(theme === "dark"));
  button.title = theme === "dark" ? "Cambiar a modo claro" : "Cambiar a modo oscuro";
}

function toggleTheme() {
  const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  window.localStorage.setItem("fumc-theme", theme);
  updateThemeButton(theme);
}

enhanceStaticTables();
initializeTheme();
bindEvents();
loadDashboard();
window.setInterval(() => {
  if (document.visibilityState === "visible" && authenticated && !refreshInFlight) refreshAll();
}, REFRESH_INTERVAL_MS);
