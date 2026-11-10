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
let localDemoStudents = [];

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
    throw new ApiError(response.status, result.message || text || "La solicitud no fue aceptada.");
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
  authNotice.textContent = `Acceso bloqueado: ${message}`;
  document.querySelector("#login-link").hidden = !showLogin;
  document.querySelector("#sidebar-status-text").textContent = "Sin conexión";
  document.querySelector("#sidebar-status-dot").classList.add("offline");
  updateProcessingButtons();
}

function setReady() {
  authenticated = true;
  authNotice.className = "notice ready";
  authNotice.textContent = "Conexión Entra verificada · datos sintéticos; análisis GPT solo tras iniciar un lote.";
  document.querySelector("#login-link").hidden = true;
  document.querySelector("#sidebar-status-text").textContent = "Conectada";
  document.querySelector("#sidebar-status-dot").classList.remove("offline");
  updateProcessingButtons();
}

function updateProcessingButtons() {
  const runButton = document.querySelector("#batch-run-button");
  const toggleButton = document.querySelector("#poc-toggle-button");
  if (runButton) runButton.disabled = !authenticated || !pocEnabled || batchRunning || pendingSyntheticCases === 0;
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
  for (const [label, value, riskClass] of [
    ["Crítico", critical, "risk-critical"],
    ["Alto", highOnly, "risk-alto"],
    ["Medio", medium, "risk-medio"],
    ["Bajo", data.low_risk || 0, "risk-bajo"],
  ]) {
    const row = document.createElement("div");
    row.className = "legend-item";
    appendText(row, "span", label, `risk-badge ${riskClass}`);
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
  for (let semester = 1; semester <= 9; semester += 1) {
    appendText(head, "th", String(semester)).scope = "col";
  }
  const thead = document.createElement("thead");
  thead.append(head);
  table.append(thead);
  const tbody = document.createElement("tbody");
  const programCodes = new Map((dashboardData?.program_faculty || []).map((item) => [item.program, item.program_code || item.program]));
  for (const program of rows || []) {
    const row = document.createElement("tr");
    appendText(row, "th", program.program).scope = "row";
    for (let semester = 1; semester <= 9; semester += 1) {
      const counts = program.semesters?.[String(semester)] || { total: 0, high: 0 };
      const cell = document.createElement("td");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "heatmap-cell";
      const ratio = counts.total ? counts.high / counts.total : 0;
      button.dataset.level = counts.total === 0 ? "empty" : ratio >= 0.25 ? "high" : ratio >= 0.12 ? "medium" : "low";
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
  empty.textContent = "Sin análisis GPT todavía. Inicia un lote de hasta 5 casos pendientes para generar resultados.";
  for (const review of reviews.slice(0, 5)) {
    const row = document.createElement("li");
    row.className = "pending-item";
    const details = document.createElement("div");
    appendText(details, "strong", review.student_id || `Resultado ${review.review_id}`);
    appendText(details, "p", `${review.recommendation?.summary || "Análisis generado"} · ${formatNumber((review.model_probability || 0) * 100, 1)}%`, "result-summary");
    const open = document.createElement("button");
    open.type = "button";
    open.className = "secondary";
    open.textContent = "Ver resultado";
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
    document.querySelector("#profile-title").textContent = "Resultado multiagente";
    document.querySelector("#profile-subtitle").textContent = "Caso sintético sin vínculo a un perfil de estudiante.";
    document.querySelector("#profile-content").replaceChildren();
    renderAnalysis(result.review, "#profile-analysis", "#analysis-content");
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
  const followupCoverage = data.high_risk ? (data.active_followups / data.high_risk) * 100 : 0;
  const riskDelta = points.length > 1 ? (points.at(-1).high || 0) - (points.at(-2).high || 0) : 0;
  cards.replaceChildren(
    makeDashboardKpi("Estudiantes evaluados", data.total_students, "Corte actual", points.map((point) => point.total), "#068CC1", "students"),
    makeDashboardKpi("Estudiantes en riesgo (alto + crítico)", data.high_risk, `${formatNumber(highRate, 1)}% del total · ${riskDelta >= 0 ? "+" : ""}${formatNumber(riskDelta)} frente al mes anterior`, points.map((point) => point.high), "#EE0063", "students", { risk: "Alto" }),
    makeDashboardKpi("Con seguimiento activo", data.active_followups, `Cobertura ${formatNumber(followupCoverage, 1)}% de casos en riesgo`, points.map((point) => point.active_followups), "#0DAA0D", "followups"),
    makeDashboardKpi("Alertas IA · abiertas", data.open_alerts, `${formatNumber(data.critical_cases)} críticas`, points.map((point) => point.open_alerts), "#E6A51A", "alerts"),
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
    appendText(row, "td", program.period_delta_pp === null ? "—" : `${program.period_delta_pp > 0 ? "▲ +" : "▼ "}${formatNumber(Math.abs(program.period_delta_pp), 1)} pp`, program.period_delta_pp === null ? "muted" : program.period_delta_pp > 0 ? "trend-up" : "trend-down");
    body.append(row);
  }
  const sortNames = { total: "evaluados", high: "en riesgo", risk_rate: "% de riesgo" };
  document.querySelector("#program-sort-label").textContent = `Orden actual: ${sortNames[programSortKey] || "% de riesgo"}`;
}

function getLocalDemoDashboard() {
  const groups = (items) => Object.fromEntries(items.map(([name, total, high]) => [name, { total, high }]));
  const programs = [
    ["Fisioterapia", "Ciencias de la Salud", 902, 170, 121, 18.8, 0.4],
    ["Fonoaudiología", "Ciencias de la Salud", 500, 92, 62, 18.4, 1.1],
    ["Administración de Empresas", "Ciencias Empresariales", 701, 104, 74, 14.8, -0.3],
    ["Ingeniería de Software", "Ingeniería y Tecnología", 603, 88, 63, 14.6, 1.6],
    ["Psicología", "Ciencias Sociales y Humanas", 410, 58, 41, 14.1, 0.3],
    ["Tecnología en Electromedicina", "Ingeniería y Tecnología", 239, 33, 22, 13.8, -0.5],
    ["Contaduría Pública", "Ciencias Empresariales", 487, 67, 45, 13.8, 0.2],
  ];
  return {
    total_students: 3842, high_risk: 612, critical_cases: 171, medium_risk: 916, low_risk: 2314,
    active_followups: 428, open_alerts: 37, critical_probability_threshold: .8,
    period_id: "2026-2", cut: "SEMANA_4", trend_is_simulated: true,
    by_campus: groups([["Medellín", 2103, 307], ["Cali", 612, 104], ["Neiva", 534, 94], ["Popayán", 593, 107]]),
    by_city: groups([["Medellín", 2103, 307], ["Cali", 612, 104], ["Neiva", 534, 94], ["Popayán", 593, 107]]),
    by_faculty: groups([["Ciencias de la Salud", 1402, 262], ["Ciencias Empresariales", 1188, 171], ["Ingeniería y Tecnología", 842, 121], ["Ciencias Sociales y Humanas", 410, 58]]),
    by_program: groups(programs.map(([name, , total, , , rate]) => [name, total, Math.round(total * rate / 100)])),
    program_summary: programs.map(([program, faculty, total, high, active_followups, risk_rate, period_delta_pp]) => ({ program, faculty, total, high, active_followups, risk_rate, period_delta_pp })),
    trend: [
      ["2025-11", 528, 331], ["2025-12", 514, 342], ["2026-01", 566, 356], ["2026-02", 582, 371],
      ["2026-03", 598, 388], ["2026-04", 571, 402], ["2026-05", 604, 416], ["2026-06", 612, 428],
    ].map(([period_id, high, active_followups]) => ({ period_id, total: 3842, high, active_followups, open_alerts: 37 })),
    risk_by_program_semester: programs.slice(0, 6).map(([program]) => ({
      program,
      semesters: Object.fromEntries(Array.from({ length: 9 }, (_, index) => {
        const total = index < 6 ? 55 + ((index * 13 + program.length) % 70) : 0;
        return [String(index + 1), { total, high: total ? Math.round(total * (.09 + index * .018)) : 0 }];
      })),
    })),
    filter_options: { campuses: [{ code: "MEDELLIN", name: "Medellín" }, { code: "CALI", name: "Cali" }, { code: "NEIVA", name: "Neiva" }, { code: "POPAYAN", name: "Popayán" }], programs: programs.map(([name]) => ({ code: name, name })) },
    applied_filters: { campus: "", program: "" }, generated_reviews: [], pending_reviews: [],
  };
}

function renderLocalDemoDashboard() {
  dashboardData = getLocalDemoDashboard();
  const campusControl = document.querySelector("#dashboard-campus-filter");
  const programControl = document.querySelector("#dashboard-program-filter");
  populateSelect(campusControl, dashboardData.filter_options.campuses, "code", "name", "Todas las sedes");
  populateSelect(programControl, dashboardData.filter_options.programs, "code", "Todos los programas");
  const selectedCampus = campusControl.value;
  const selectedProgram = programControl.value;
  if (selectedCampus) {
    const selected = Object.entries(dashboardData.by_campus).find(([name]) => name.toUpperCase() === selectedCampus);
    if (selected) {
      dashboardData.by_campus = { [selected[0]]: selected[1] };
      dashboardData.by_city = { [selected[0]]: selected[1] };
      dashboardData.total_students = selected[1].total;
      dashboardData.high_risk = selected[1].high;
    }
  }
  if (selectedProgram) {
    const selected = dashboardData.program_summary.find((item) => item.program === selectedProgram);
    if (selected) {
      dashboardData.by_program = { [selected.program]: { total: selected.total, high: selected.high } };
      dashboardData.total_students = selected.total;
      dashboardData.high_risk = selected.high;
      dashboardData.active_followups = selected.active_followups;
      dashboardData.program_summary = [selected];
      dashboardData.risk_by_program_semester = dashboardData.risk_by_program_semester.filter((item) => item.program === selected.program);
    }
  }
  authenticated = true;
  pocEnabled = false;
  authNotice.hidden = true;
  renderMetrics(dashboardData);
  renderRiskChart("#campus-chart", dashboardData.by_campus, "campus");
  renderRiskChart("#faculty-chart", dashboardData.by_faculty, "faculty");
  renderTrend("#trend-chart", dashboardData.trend);
  renderRiskDonut(dashboardData);
  renderRiskHeatmap(dashboardData.risk_by_program_semester);
  renderProgramSummary(dashboardData.program_summary);
  renderResults([]);
  document.querySelector("#dashboard-period").textContent = dashboardData.period_id;
  document.querySelector("#sidebar-status-text").textContent = "Demo local";
  document.querySelector("#sidebar-period").textContent = dashboardData.period_id;
  document.querySelector("#synthetic-db-status").textContent = "Datos ilustrativos locales · inicia Azure Functions para conectar tablas y agentes.";
  updateProcessingButtons();
}

async function runDashboardUpdate() {
  if (authenticated && pocEnabled && pendingSyntheticCases > 0) {
    await startBatch();
  } else {
    await refreshAll();
  }
}

async function loadDashboard() {
  try {
    const campusControl = document.querySelector("#dashboard-campus-filter");
    const programControl = document.querySelector("#dashboard-program-filter");
    const params = new URLSearchParams({
      campus: campusControl.value,
      program: programControl.value,
    });
    const result = await api(`/poc/dashboard?${params}`);
    dashboardData = result;
    setReady();
    populateSelect(campusControl, result.filter_options?.campuses, "code", "name", "Todas las sedes");
    populateSelect(programControl, result.filter_options?.programs, "code", "Todos los programas");
    renderMetrics(result);
    renderRiskChart("#campus-chart", result.by_campus, "campus");
    renderRiskChart("#faculty-chart", result.by_faculty, "faculty");
    renderTrend("#trend-chart", result.trend);
    renderRiskDonut(result);
    renderRiskHeatmap(result.risk_by_program_semester);
    renderProgramSummary(result.program_summary || []);
    renderResults([...(result.generated_reviews || []), ...(result.pending_reviews || [])]);
    document.querySelector("#dashboard-period").textContent = result.period_id;
    document.querySelector("#dashboard-last-updated").textContent = `Actualizado ${new Date().toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" })}`;
    await loadStatus();
    await loadDashboardAlerts();
    return true;
  } catch (error) {
    if (error.status === 404) {
      setBlocked("API de gestión no disponible; no se muestran datos locales de demostración.");
      return false;
    }
    setBlocked(error.message || "No se pudo cargar el dashboard.", error.status === 401);
    return false;
  }
}

async function loadStatus() {
  try {
    const result = await api("/poc/status");
    const database = result.database || {};
    pocEnabled = Boolean(result.enabled);
    activeOperations = result.active_operations || 0;
    pendingSyntheticCases = database.pending || 0;
    document.querySelector("#synthetic-db-cards").replaceChildren(
      databaseMetric("Estudiantes", database.student_count),
      databaseMetric("Pendientes", database.pending),
      databaseMetric("Procesados", database.processed),
    );
    document.querySelector("#synthetic-db-status").textContent = `${formatNumber(database.snapshot_count)} registros · ${database.period_id || "—"} · ${database.cut || "—"} · tablas Azure conectadas.`;
    document.querySelector("#dashboard-poc-state").textContent = pocEnabled
      ? `Procesamiento ${activeOperations ? "en curso" : "disponible"}`
      : "Procesamiento pausado";
    document.querySelector("#sidebar-status-text").textContent = pocEnabled ? "Conectada" : "Pausada";
    document.querySelector("#sidebar-status-dot").classList.toggle("offline", !pocEnabled);
    document.querySelector("#sidebar-period").textContent = database.period_id || "—";
    document.querySelector("#setting-data-mode").textContent = "Demo · registros generados";
    document.querySelector("#setting-period").textContent = `${database.period_id || "—"} / ${database.cut || "—"}`;
    document.querySelector("#setting-batch-limit").textContent = formatNumber(database.max_batch_size);
    if (dashboardData) document.querySelector("#setting-critical-threshold").textContent = `≥ ${formatNumber(dashboardData.critical_probability_threshold, 2)}`;
    updateProcessingButtons();
    return result;
  } catch (error) {
    document.querySelector("#synthetic-db-status").textContent = error.message;
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
    const alertFilters = dashboardData?.applied_filters || {};
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
    if (!(await loadDashboard())) return;
    const active = Object.entries(views).find(([, node]) => !node.hidden)?.[0];
    if (active && active !== "dashboard") await loadViewData(active);
  } finally {
    refreshInFlight = false;
  }
}

async function loadViewData(name) {
  const loaders = {
    students: loadStudents,
    profile: () => selectedStudentId ? loadProfile(selectedStudentId) : Promise.resolve(),
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

function renderLocalStudents() {
  const facultyByProgram = {
    "Ingeniería de Software": "Ingeniería y Tecnología",
    Fonoaudiología: "Ciencias de la Salud",
    "Contaduría Pública": "Ciencias Empresariales",
    Fisioterapia: "Ciencias de la Salud",
    Psicología: "Ciencias Sociales y Humanas",
    "Administración de Empresas": "Ciencias Empresariales",
    "Tecnología en Electromedicina": "Ingeniería y Tecnología",
  };
  const students = [
    ["Laura Gómez Restrepo", "CC ••••4821", "Ingeniería de Software", "Medellín", 3, 86, "En seguimiento", "02 nov 2026"],
    ["Andrés Felipe Muñoz", "CC ••••1175", "Fonoaudiología", "Popayán", 2, 83, "Sin responsable", "Sin intervención"],
    ["Daniela Pérez Ocampo", "CC ••••9034", "Contaduría Pública", "Medellín", 4, 71, "En seguimiento", "29 oct 2026"],
    ["Camilo Ortiz Vélez", "CC ••••6620", "Fisioterapia", "Cali", 3, 68, "En seguimiento", "30 oct 2026"],
    ["Sara Cifuentes Mejía", "CC ••••2287", "Fisioterapia", "Neiva", 5, 64, "Seguimiento vencido", "18 oct 2026"],
    ["Julián Esteban Arias", "CC ••••7741", "Psicología", "Medellín", 2, 57, "Monitoreo", "24 oct 2026"],
    ["Mariana López Ríos", "CC ••••3318", "Administración de Empresas", "Cali", 4, 49, "Monitoreo", "27 oct 2026"],
    ["Valentina Ruiz Mora", "CC ••••5802", "Ingeniería de Software", "Medellín", 6, 43, "Sin responsable", "Sin intervención"],
    ["Mateo Sánchez Gil", "CC ••••1426", "Tecnología en Electromedicina", "Popayán", 3, 38, "Monitoreo", "31 oct 2026"],
    ["Sofía Restrepo Díaz", "CC ••••4190", "Fonoaudiología", "Neiva", 1, 29, "Al día", "01 nov 2026"],
    ["Tomás Herrera León", "CC ••••7064", "Psicología", "Medellín", 7, 21, "Al día", "01 nov 2026"],
    ["Isabella Castro Peña", "CC ••••8653", "Fisioterapia", "Cali", 2, 14, "Al día", "30 oct 2026"],
  ].map(([display_name, document_id, program, city, semester, score, status, last_intervention], index) => ({
    student_id: `ST-SYN-${String(index + 1).padStart(6, "0")}`,
    display_name, document_id, program, city, campus: city.toUpperCase(), semester,
    model_probability: score / 100, risk_level: score >= 80 ? "Crítico" : score >= 60 ? "Alto" : score >= 30 ? "Medio" : "Bajo",
    status: "processed", display_status: status, last_intervention, faculty: facultyByProgram[program],
  }));
  const search = currentSearch.toLocaleLowerCase("es");
  const riskFilter = document.querySelector("#filter-risk").value;
  const programFilter = document.querySelector("#filter-program").value;
  const campusFilter = document.querySelector("#filter-campus").value;
  const cityFilter = document.querySelector("#filter-city").value;
  const facultyFilter = document.querySelector("#filter-faculty").value;
  const semesterFilter = document.querySelector("#filter-semester").value;
  const minimumScore = Number(document.querySelector("#filter-min-score").value || 0);
  const filtered = students.filter((student) => {
    const matchesSearch = !search || `${student.display_name} ${student.document_id} ${student.program}`.toLocaleLowerCase("es").includes(search);
    const matchesRisk = riskFilter === "critical"
      ? student.model_probability >= 0.8
      : riskFilter
        ? student.risk_level === riskFilter
        : true;
    return matchesSearch
      && (!programFilter || student.program === programFilter)
      && (!campusFilter || student.campus === campusFilter || student.city === campusFilter)
      && (!cityFilter || student.city === cityFilter)
      && (!facultyFilter || student.faculty === facultyFilter)
      && (!semesterFilter || String(student.semester) === semesterFilter)
      && student.model_probability * 100 >= minimumScore;
  });
  populateSelect(document.querySelector("#filter-program"), [...new Set(students.map((student) => student.program))].map((name) => ({ code: name, name })), "code", "name", "Todos los programas");
  populateSelect(document.querySelector("#filter-campus"), [...new Set(students.map((student) => ({ code: student.campus, name: student.city })))], "code", "name", "Todas las sedes");
  populateSelect(document.querySelector("#filter-city"), [...new Set(students.map((student) => student.city))].map((name) => ({ name })), "name", "name", "Todas las ciudades");
  populateSelect(document.querySelector("#filter-faculty"), [...new Set(students.map((student) => student.faculty))].map((name) => ({ name })), "name", "name", "Todas las facultades");
  localDemoStudents = students;
  currentStudents = filtered;
  currentTotal = filtered.length;
  document.querySelector("#student-count").textContent = `Mostrando ${filtered.length} de ${students.length} registros`;
  document.querySelector("#page-label").textContent = filtered.length ? `Página 1 · ${filtered.length} resultados` : "Sin resultados";
  document.querySelector("#previous-page").disabled = true;
  document.querySelector("#next-page").disabled = true;
  renderRiskSegmentCounts({
    all: filtered.length,
    critical: filtered.filter((student) => student.model_probability >= .8).length,
    high: filtered.filter((student) => student.risk_level === "Alto").length,
    medium: filtered.filter((student) => student.risk_level === "Medio").length,
    low: filtered.filter((student) => student.risk_level === "Bajo").length,
  });
  const body = document.querySelector("#student-rows");
  body.replaceChildren();
  for (const student of filtered) {
    const row = document.createElement("tr");
    row.dataset.studentId = student.student_id;
    row.tabIndex = 0;
    row.setAttribute("aria-label", `Seleccionar ${student.display_name}, score ${student.model_probability * 100}`);
    const identity = document.createElement("td");
    const identityWrap = document.createElement("div");
    identityWrap.className = "student-identity";
    const initials = appendText(identityWrap, "span", student.display_name.split(" ").map((part) => part[0]).slice(0, 2).join(""), "student-avatar");
    initials.setAttribute("aria-hidden", "true");
    const identityText = document.createElement("span");
    identityText.className = "student-name-wrap";
    appendText(identityText, "strong", student.display_name, "student-name");
    appendText(identityText, "small", student.document_id, "student-document");
    identityWrap.append(identityText);
    identity.append(identityWrap);
    row.append(identity);
    appendText(row, "td", student.program);
    appendText(row, "td", student.city);
    appendText(row, "td", String(student.semester));
    const scoreCell = document.createElement("td");
    appendText(scoreCell, "strong", String(Math.round(student.model_probability * 100)), "score-value");
    const scoreTrack = document.createElement("span");
    scoreTrack.className = "score-track";
    const scoreFill = document.createElement("span");
    scoreFill.className = `score-fill ${student.model_probability >= .8 ? "score-critical" : student.model_probability >= .6 ? "score-high" : student.model_probability >= .3 ? "score-medium" : "score-low"}`;
    scoreFill.style.width = `${student.model_probability * 100}%`;
    scoreTrack.append(scoreFill);
    scoreCell.append(scoreTrack);
    row.append(scoreCell);
    const riskCell = document.createElement("td");
    const badge = document.createElement("span");
    renderRiskBadge(badge, student);
    riskCell.append(badge);
    row.append(riskCell);
    appendText(row, "td", student.display_status);
    appendText(row, "td", student.last_intervention);
    row.addEventListener("click", () => loadQuickView(student));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); loadQuickView(student); }
    });
    body.append(row);
  }
  if (riskFilter) {
    const expectedRisk = riskFilter === "critical" ? "Crítico" : riskFilter;
    [...body.children].forEach((row) => {
      if (row.querySelector(".risk-badge")?.textContent !== expectedRisk) row.remove();
    });
    const visibleCount = body.children.length;
    document.querySelector("#student-count").textContent = `Mostrando ${visibleCount} de ${students.length} registros`;
    document.querySelector("#page-label").textContent = visibleCount ? `Página 1 · ${visibleCount} resultados` : "Sin resultados";
  }
  if (filtered.length) loadQuickView(filtered[0]);
  else {
    document.querySelector("#quickview-empty").hidden = false;
    document.querySelector("#quickview-content").hidden = true;
  }
  setStatus("#student-list-status", "Listado listo para revisar y filtrar.");
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
  setStatus("#student-list-status", "Consultando registros y filtros en Azure Tables…");
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
    document.querySelector("#table-cut").textContent = `${result.period_id || "2025-2"} · ${result.cut || "SEMANA_4"}`;
    renderRiskSegmentCounts(result.risk_counts || {});
    const activeFollowups = await api("/poc/followups?status=all&limit=500").catch(() => ({ items: [] }));
    const lastFollowupByStudent = new Map();
    for (const followup of activeFollowups.items || []) {
      const previous = lastFollowupByStudent.get(followup.student_id);
      if (!previous || String(followup.updated_at || "") > String(previous.updated_at || "")) {
        lastFollowupByStudent.set(followup.student_id, followup);
      }
    }
    const body = document.querySelector("#student-rows");
    body.replaceChildren();
    for (const student of result.items || []) {
      const row = document.createElement("tr");
        row.dataset.studentId = student.student_id;
        row.tabIndex = 0;
        row.setAttribute("aria-label", `Seleccionar ${student.student_id}, ${student.program}, score ${formatNumber((student.model_probability || 0) * 100, 0)}`);
      const studentCell = document.createElement("td");
      appendText(studentCell, "strong", student.student_id, "student-id");
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
      const followup = lastFollowupByStudent.get(student.student_id);
      appendText(row, "td", followup ? statusLabelFollowup(followup.status) : statusLabel(student.status));
      appendText(row, "td", followup?.updated_at ? new Date(followup.updated_at).toLocaleDateString("es-CO") : "Sin responsable");
      row.addEventListener("click", () => loadQuickView(student, followup));
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          loadQuickView(student, followup);
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
    setStatus("#student-list-status", "Consulta aplicada en backend; los filtros se conservan al paginar.");
  } catch (error) {
    if (error.status === 404) {
      setStatus("#student-list-status", "API no disponible; no se muestran perfiles locales de demostración.");
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
  const gauge = document.createElement("div");
  gauge.className = "score-gauge";
  gauge.style.setProperty("--score", `${score * 3.6}deg`);
  appendText(gauge, "strong", String(score));
  appendText(gauge, "span", "Score IA (0–100)");
  content.append(gauge);
  const risk = document.createElement("span");
  renderRiskBadge(risk, student);
  content.append(risk);
  const factors = document.createElement("div");
  factors.className = "quickview-factors";
  appendText(factors, "h3", "Señales disponibles");
  appendText(factors, "p", "Consulta el perfil para ver señales académicas, financieras y de bienestar. El score no implica causalidad.", "muted");
  content.append(factors);
  appendText(content, "p", followup ? `Estado: ${statusLabelFollowup(followup.status)} · ${followup.action_label}` : `Estado del análisis: ${statusLabel(student.status)} · sin seguimiento activo`, "quickview-status");
  const actions = document.createElement("div");
  actions.className = "quickview-actions";
  addActionButton(actions, "Abrir perfil 360°", "", () => loadProfile(student.student_id));
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
  const gauge = document.createElement("div");
  gauge.className = "profile-score-gauge";
  gauge.style.setProperty("--score", `${score * 3.6}deg`);
  gauge.setAttribute("role", "img");
  gauge.setAttribute("aria-label", `Score IA ${score} de 100`);
  appendText(gauge, "strong", String(score));
  appendText(gauge, "span", "Score IA (0–100)");
  const probability = document.createElement("div");
  probability.className = "probability-ring";
  probability.setAttribute("role", "img");
  probability.setAttribute("aria-label", `Probabilidad reportada ${formatNumber((student.model_probability || 0) * 100, 1)}%`);
  appendText(probability, "strong", `${formatNumber((student.model_probability || 0) * 100, 0)}%`);
  appendText(probability, "span", "Prob. modelo");
  container.append(gauge, probability);
}

async function loadProfile(studentId) {
  selectedStudentId = studentId;
  showViewWithoutLoad("profile");
  selectProfileTab("summary");
  document.querySelector("#profile-title").textContent = studentId;
  document.querySelector("#profile-subtitle").textContent = "Consultando expediente académico, financiero y de bienestar…";
  updateProfileNavigation(studentId);
  document.querySelector("#profile-content").replaceChildren();
  document.querySelector("#profile-analysis").hidden = true;
  document.querySelector("#profile-recommendations").hidden = true;
  try {
    const result = await api(`/poc/students/${encodeURIComponent(studentId)}`);
    const student = result.student;
    currentProfile = result;
    document.querySelector("#profile-title").textContent = student.student_id;
    document.querySelector("#profile-breadcrumb").textContent = student.student_id;
    document.querySelector("#profile-period-chip").textContent = `Matrícula ${student.period_id}`;
    renderProfileGauges(student);
    const followupResult = await api("/poc/followups?status=all&limit=500").catch(() => ({ items: [] }));
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
    document.querySelector("#profile-subtitle").textContent = `${student.program} · ${student.faculty || ""} · ${student.city} · ${student.period_id} · ${student.cut}`;
    const badge = document.querySelector("#profile-risk");
    renderRiskBadge(badge, student);
    badge.append(document.createTextNode(` · ${formatNumber((student.model_probability || 0) * 100, 1)}%`));
    const hero = document.createElement("section");
    hero.className = "panel profile-hero";
    const identity = document.createElement("div");
    appendText(identity, "strong", student.student_id, "student-id");
    appendText(identity, "p", `${student.program} · ${student.faculty || ""} · ${student.city} · ${student.campus}`, "profile-id");
    hero.append(identity, fact("Score reportado", `${formatNumber((student.model_probability || 0) * 100, 1)}%`));
    const summary = document.createElement("section");
    summary.className = "panel profile-card";
    appendText(summary, "h2", "Perfil académico y de contexto");
    const facts = document.createElement("div");
    facts.className = "profile-facts";
    for (const pair of [["Programa", student.program], ["Facultad", student.faculty], ["Ciudad", student.city], ["Sede", student.campus], ["Modalidad", student.modality], ["Semestre", student.semester], ["Estado de análisis", statusLabel(student.status)]]) facts.append(fact(pair[0], pair[1]));
    summary.append(facts);
    const content = document.querySelector("#profile-content");
    content.append(hero, summary);
    content.append(makeProfileCard("Panel académico", (result.academic_signals || []).map((signal) => [signal.course_code, `${formatNumber(signal.grade, 2)} / 5 · asistencia ${formatNumber(signal.attendance_pct, 1)}%`])));
    content.append(makeProfileCard("Panel socioeconómico", [["Mora", `${result.finance.arrears_months} meses`], ["Saldo", `${formatNumber(result.finance.arrears_balance_cop)} COP`], ["Financiación", result.finance.financing_type], ["Beca", result.finance.has_scholarship ? "Sí" : "No"], ["Contexto familiar", student.family_context]]));
    content.append(makeProfileCard("Bienestar", [["Apoyo registrado", result.wellbeing.support_type || "Sin registro"], ["Sesiones", result.wellbeing.sessions], ["Asistencia", result.wellbeing.attended ? "Sí" : "No"], ["Canal", result.wellbeing.channel]]));
    if (result.analysis_result?.review) {
      renderAnalysis(result.analysis_result.review, "#profile-analysis", "#analysis-content");
      renderAnalysis(result.analysis_result.review, "#profile-recommendations", "#recommendations-content");
    } else {
      document.querySelector("#profile-analysis").hidden = false;
      document.querySelector("#profile-recommendations").hidden = false;
      document.querySelector("#analysis-content").replaceChildren();
      appendText(document.querySelector("#analysis-content"), "p", "Este perfil todavía no tiene un análisis de agentes. En Dashboard, inicia un lote de hasta 5 casos pendientes; el lote procesa los casos más antiguos y puede no incluir este perfil.");
      document.querySelector("#recommendations-content").replaceChildren();
      appendText(document.querySelector("#recommendations-content"), "p", "Las recomendaciones aparecerán cuando los agentes terminen el análisis.");
    }
  } catch (error) {
    if (error.status === 404) {
      appendText(document.querySelector("#profile-content"), "p", "No se cargó el perfil: la API no está disponible. No se muestran expedientes locales de demostración.", "profile-loading");
      return;
    }
    appendText(document.querySelector("#profile-content"), "p", error.message || "No se pudo cargar el expediente.", "profile-loading");
    if ([401, 403, 503].includes(error.status)) setBlocked(error.message, error.status === 401);
  }
}

function renderLocalProfile(studentId) {
  const student = localDemoStudents.find((item) => item.student_id === studentId) || localDemoStudents[0];
  if (!student) return;
  selectedStudentId = student.student_id;
  showViewWithoutLoad("profile");
  selectProfileTab("summary");
  document.querySelector("#profile-title").textContent = student.display_name;
  document.querySelector("#profile-breadcrumb").textContent = student.display_name;
  document.querySelector("#profile-subtitle").textContent = `${student.document_id} · ${student.program} · Sede ${student.city} · Semestre ${student.semester}`;
  document.querySelector("#profile-period-chip").textContent = "Matrícula activa 2026-2";
  const avatar = document.querySelector(".profile-avatar");
  if (avatar) avatar.textContent = student.display_name.split(" ").map((part) => part[0]).slice(0, 2).join("");
  renderProfileGauges(student);
  const badge = document.querySelector("#profile-risk");
  renderRiskBadge(badge, student);
  badge.append(document.createTextNode(` · ${Math.round(student.model_probability * 100)}`));
  const followupChip = document.querySelector("#profile-followup-chip");
  followupChip.hidden = false;
  followupChip.textContent = "En seguimiento prioritario";
  const content = document.querySelector("#profile-content");
  content.replaceChildren();
  const metrics = document.createElement("section");
  metrics.className = "profile-metrics-grid";
  for (const [label, value, note, tone] of [["Asistencia (últimas 3 semanas)", "71%", "▼ 38% menos que su promedio", "negative"], ["Promedio acumulado", "3,2", "▼ Venía en 3,6 al cerrar el sem. 1", "negative"], ["Actividad en plataforma virtual", "4 días", "Sin ingreso reciente", "warning"], ["Mora en matrícula", "No", "• Al día", "positive"], ["Próxima acción", "Llamada de seguimiento", "Vence en 7 días", "warning"]]) {
    const card = document.createElement("section");
    card.className = "panel profile-metric-card";
    appendText(card, "span", label, "profile-metric-label");
    appendText(card, "strong", value, "profile-metric-value");
    appendText(card, "small", note, `profile-metric-note ${tone}`);
    metrics.append(card);
  }
  content.append(metrics);
  content.append(makeProfileCard("Información personal", [["Documento", student.document_id], ["Ingreso", "2025-2"], ["Modalidad", "Presencial"], ["Contacto", "Registrado en el sistema académico"], ["Acudiente", "Registrado"]]));
  content.append(makeProfileCard("Datos académicos", [["Programa", student.program], ["Sede", student.city], ["Semestre", student.semester], ["Materias en curso", "6 (3 en riesgo)"], ["Promedio acumulado", "3,2"], ["Estado académico", "Activo · en seguimiento"]]));
  content.append(makeProfileCard("Cola de casos prioritarios", localDemoStudents.slice(0, 5).map((item) => [item.display_name, Math.round(item.model_probability * 100)])));
  document.querySelector("#profile-analysis").hidden = true;
  document.querySelector("#profile-recommendations").hidden = true;
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

function renderAnalysis(review, panelSelector, contentSelector) {
  const panel = document.querySelector(panelSelector);
  const content = document.querySelector(contentSelector);
  if (panel) panel.hidden = false;
  if (content) content.replaceChildren();
  const recommendation = review.recommendation || {};
  const statusLabel = review.status === "pending_approval"
    ? "pendiente de revisión humana"
    : review.status === "generated"
      ? "generado"
      : `decisión humana: ${review.status || "registrada"}`;
  appendText(content, "p", `Resultado ${statusLabel} · probabilidad ${formatNumber((review.model_probability || 0) * 100, 1)}% · sin decisión automatizada.`);
  appendText(content, "h3", "Síntesis del LLM");
  appendText(content, "p", recommendation.summary || "Sin síntesis.");
  appendList(content, "Acciones sugeridas", recommendation.proposed_actions || []);
  appendList(content, "Limitaciones", recommendation.limitations || []);
  for (const [title, analysis] of [
    ["Agente financiero", review.socioeconomic_analysis],
    ["Agente académico", review.academic_analysis?.analysis],
    ["Agente de bienestar", review.wellbeing_analysis],
  ]) {
    if (!analysis) continue;
    appendText(content, "h3", title);
    appendText(content, "p", analysis.summary || "Sin análisis.");
    appendList(content, "Observaciones", analysis.observations || []);
    appendList(content, "Limitaciones", analysis.limitations || []);
  }
  const sources = review.academic_analysis?.sources || [];
  if (sources.length) appendList(content, "Fuentes recuperadas", sources.map((source) => `${source.title || source.id}${source.section ? ` · ${source.section}` : ""}`));
  if (review.token_usage) renderUsage(content, review.token_usage, review.cost_estimate);
  if (review.status === "pending_approval" && review.review_id && panelSelector !== "#profile-recommendations") {
    const actions = document.createElement("div");
    actions.className = "review-actions";
    appendText(actions, "p", "La recomendación requiere validación profesional antes de registrar una intervención.", "muted");
    addActionButton(actions, "Aprobar propuesta", "primary-action", () => submitReviewDecision(review.review_id, "approved"));
    addActionButton(actions, "Rechazar propuesta", "danger", () => submitReviewDecision(review.review_id, "rejected"));
    content.append(actions);
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

function appendList(parent, title, values) {
  if (!values.length) return;
  appendText(parent, "h3", title);
  const list = document.createElement("ul");
  for (const value of values) appendText(list, "li", value);
  parent.append(list);
}

function renderUsage(parent, usage, cost) {
  const table = document.createElement("table");
  table.className = "usage-table";
  appendText(table, "caption", "Uso de tokens reportado por agente").className = "sr-only";
  const head = document.createElement("tr");
  for (const label of ["Agente", "Entrada", "Salida", "Total"]) appendText(head, "th", label).scope = "col";
  table.append(head);
  for (const [name, call] of Object.entries(usage.calls || {})) {
    const row = document.createElement("tr");
    appendText(row, "td", name);
    appendText(row, "td", formatNumber(call.input_tokens));
    appendText(row, "td", formatNumber(call.output_tokens));
    appendText(row, "td", formatNumber(call.total_tokens));
    table.append(row);
  }
  parent.append(table);
  if (cost?.amount_usd != null) appendText(parent, "p", `Estimación registrada: USD ${Number(cost.amount_usd).toFixed(6)} · no es un tope de gasto.`, "usage-note");
}

async function loadAlerts() {
  const status = document.querySelector("#alert-status").value;
  setStatus("#alert-list-status", "Consultando alertas persistidas…");
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
    setStatus("#alert-list-status", `${formatNumber(items.length)} alertas consultadas. Reconocer/resolver persiste estado y auditoría en Azure Tables.`);
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
  setStatus("#followup-list-status", "Consultando tareas de seguimiento…");
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
    setStatus("#followup-list-status", `${formatNumber(items.length)} seguimientos. Los cambios de estado quedan guardados con actor y fecha.`);
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
  setStatus(statusSelector, "Guardando seguimiento en Azure Tables…");
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
  setStatus("#report-status", "Consultando resultados protegidos…");
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
    link.download = "resultados_multiagente_demo.csv";
    link.click();
    URL.revokeObjectURL(url);
    setStatus("#report-status", `${formatNumber(rows.length)} resultados exportados desde la API.`);
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
    ["Programa", "Facultad ilustrativa", "Evaluados", "En riesgo", "% riesgo", "Seguimiento activo"],
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
  setStatus("#student-list-status", "Consultando todas las páginas filtradas para exportar CSV…");
  try {
    const first = await api(`/poc/students?${base}`);
    const rows = [...(first.items || [])];
    for (let offset = 100; offset < first.total; offset += 100) {
      base.set("offset", String(offset));
      const next = await api(`/poc/students?${base}`);
      rows.push(...(next.items || []));
    }
    downloadCsv(
      "estudiantes_demo.csv",
      ["Código", "Programa", "Facultad", "Ciudad", "Semestre", "Score IA", "Nivel", "Estado"],
      rows.map((item) => [item.student_id, item.program, item.faculty, item.city, item.semester, formatNumber(item.model_probability * 100, 1), item.risk_level, item.status]),
    );
    setStatus("#student-list-status", `${formatNumber(rows.length)} registros filtrados exportados.`);
  } catch (error) {
    setStatus("#student-list-status", error.message);
  }
}

function exportProfile() {
  if (!currentProfile?.student) return;
  const student = currentProfile.student;
  downloadCsv(
    `${student.student_id}_demo.csv`,
    ["Campo", "Valor"],
    [["Código", student.student_id], ["Programa", student.program], ["Facultad", student.faculty], ["Ciudad", student.city], ["Sede", student.campus], ["Semestre", student.semester], ["Score IA", formatNumber(student.model_probability * 100, 1)], ["Riesgo", student.risk_level]],
  );
}

async function loadSettings() {
  setStatus("#settings-status", "Verificando APIs, tablas y estado de procesamiento…");
  try {
    const status = await loadStatus();
    setStatus("#settings-status", `Conexión verificada · ${formatNumber(status.database?.student_count)} estudiantes cargados · almacenamiento Azure Tables.`);
  } catch (error) {
    setStatus("#settings-status", error.message);
  }
}

function setStatus(selector, message) {
  const node = document.querySelector(selector);
  if (node) node.textContent = message;
}

async function pollBatch(batchId) {
  const status = document.querySelector("#synthetic-db-status");
  try {
    const result = await api(`/batches/${encodeURIComponent(batchId)}`);
    if (["Completed", "Failed", "Terminated", "Canceled"].includes(result.runtimeStatus)) {
      batchRunning = false;
      status.textContent = `Lote ${result.runtimeStatus} · ${formatNumber(result.processedCount || 0)} procesados · ${formatNumber(result.failedCount || 0)} fallidos. Los análisis se muestran automáticamente.`;
      updateProcessingButtons();
      await refreshAll();
      showView("dashboard");
      return;
    }
    status.textContent = `Lote ${result.runtimeStatus || "Pending"} · agentes socioeconómico/académico y sintetizador trabajando…`;
    window.setTimeout(() => pollBatch(batchId), 3000);
  } catch (error) {
    batchRunning = false;
    status.textContent = `No se pudo consultar el lote: ${error.message}`;
    updateProcessingButtons();
  }
}

async function startBatch() {
  if (!authenticated || !pocEnabled || batchRunning || pendingSyntheticCases === 0) return;
  const limit = Math.min(5, pendingSyntheticCases);
  if (!window.confirm(`Se analizarán hasta ${limit} registros de demo con la red multiagente y el LLM. El resultado se mostrará al terminar; no se enviarán mensajes ni se ejecutarán intervenciones. ¿Continuar?`)) return;
  batchRunning = true;
  updateProcessingButtons();
  setStatus("#synthetic-db-status", "Reservando casos y enviándolos a Durable Functions…");
  try {
    const result = await api("/batches", { method: "POST", body: JSON.stringify({ limit }) });
    await pollBatch(result.batchId);
  } catch (error) {
    batchRunning = false;
    setStatus("#synthetic-db-status", error.message);
    updateProcessingButtons();
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
    setStatus("#synthetic-db-status", error.message);
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
  document.querySelector("#dashboard-campus-filter").addEventListener("change", loadDashboard);
  document.querySelector("#dashboard-program-filter").addEventListener("change", loadDashboard);
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
  document.querySelector("#students-batch-button").addEventListener("click", startBatch);
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
  document.querySelector("#analytics-refresh").addEventListener("click", async () => { await loadDashboard(); await loadAnalytics(); });
  document.querySelector("#faculties-refresh").addEventListener("click", async () => { await loadDashboard(); await loadFaculties(); });
  document.querySelector("#programs-refresh").addEventListener("click", async () => { await loadDashboard(); await loadPrograms(); });
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
