const DATA_URL = "./data/eda_summary.json";

const cityFilter = document.getElementById("city-filter");
const retailerFilter = document.getElementById("retailer-filter");
const categoryFilter = document.getElementById("category-filter");
const resetButton = document.getElementById("reset-filters");
const metricCards = document.getElementById("metric-cards");
const extremeTableBody = document.querySelector("#extreme-table tbody");

let fullRecords = [];

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function mean(values) {
  if (!values.length) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

function fillSelect(el, values) {
  el.innerHTML = "";
  const allOpt = document.createElement("option");
  allOpt.value = "ALL";
  allOpt.textContent = "All";
  el.appendChild(allOpt);
  values.forEach((v) => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    el.appendChild(opt);
  });
}

function applyFilters() {
  const city = cityFilter.value;
  const retailer = retailerFilter.value;
  const category = categoryFilter.value;
  return fullRecords.filter((row) => {
    if (city !== "ALL" && row.city !== city) return false;
    if (retailer !== "ALL" && row.retailer !== retailer) return false;
    if (category !== "ALL" && row.category !== category) return false;
    return true;
  });
}

function renderMetricCards(rows) {
  const pink = rows.map((r) => toNumber(r.pink_tax_pct)).filter((v) => v !== null);
  const positive = pink.filter((v) => v > 0).length;
  const negative = pink.filter((v) => v < 0).length;
  const cards = [
    { label: "Rows", value: rows.length },
    { label: "Unique Pairs", value: new Set(rows.map((r) => r.pair_code)).size },
    { label: "Avg Pink Tax %", value: pink.length ? mean(pink).toFixed(2) : "NA" },
    { label: "Median Pink Tax %", value: pink.length ? median(pink).toFixed(2) : "NA" },
    { label: "Positive Share", value: pink.length ? `${((positive / pink.length) * 100).toFixed(1)}%` : "NA" },
    { label: "Negative Share", value: pink.length ? `${((negative / pink.length) * 100).toFixed(1)}%` : "NA" },
  ];
  metricCards.innerHTML = cards
    .map(
      (c) => `
        <article class="card">
          <div class="label">${c.label}</div>
          <div class="value">${c.value}</div>
        </article>
      `
    )
    .join("");
}

function renderHistogram(rows) {
  const values = rows.map((r) => toNumber(r.pink_tax_pct)).filter((v) => v !== null);
  Plotly.newPlot(
    "histogram",
    [
      {
        x: values,
        type: "histogram",
        marker: { color: "#0f766e" },
        nbinsx: 40,
      },
    ],
    {
      margin: { l: 40, r: 15, t: 10, b: 40 },
      xaxis: { title: "Pink Tax %" },
      yaxis: { title: "Count" },
      shapes: [
        {
          type: "line",
          x0: 0,
          x1: 0,
          y0: 0,
          y1: 1,
          yref: "paper",
          line: { color: "#555", width: 1.5, dash: "dash" },
        },
      ],
    },
    { responsive: true, displayModeBar: false }
  );
}

function renderRetailerBar(rows) {
  const grouped = {};
  rows.forEach((r) => {
    const v = toNumber(r.pink_tax_pct);
    if (v === null) return;
    if (!grouped[r.retailer]) grouped[r.retailer] = [];
    grouped[r.retailer].push(v);
  });
  const labels = Object.keys(grouped);
  const means = labels.map((k) => mean(grouped[k]));
  Plotly.newPlot(
    "retailer-bar",
    [{ x: labels, y: means, type: "bar", marker: { color: "#b45309" } }],
    {
      margin: { l: 40, r: 15, t: 10, b: 80 },
      xaxis: { tickangle: -25 },
      yaxis: { title: "Average Pink Tax %" },
      shapes: [{ type: "line", x0: -0.5, x1: labels.length - 0.5, y0: 0, y1: 0, line: { color: "#555", dash: "dash" } }],
    },
    { responsive: true, displayModeBar: false }
  );
}

function renderCityBox(rows) {
  const byCity = {};
  rows.forEach((r) => {
    const v = toNumber(r.pink_tax_pct);
    if (v === null) return;
    if (!byCity[r.city]) byCity[r.city] = [];
    byCity[r.city].push(v);
  });
  const traces = Object.entries(byCity).map(([city, vals]) => ({
    y: vals,
    name: city,
    type: "box",
    boxpoints: false,
  }));
  Plotly.newPlot(
    "city-box",
    traces,
    {
      margin: { l: 40, r: 15, t: 10, b: 40 },
      yaxis: { title: "Pink Tax %" },
      shapes: [{ type: "line", x0: -0.5, x1: traces.length - 0.5, y0: 0, y1: 0, line: { color: "#555", dash: "dash" } }],
    },
    { responsive: true, displayModeBar: false }
  );
}

function renderCategoryBar(rows) {
  const grouped = {};
  rows.forEach((r) => {
    const v = toNumber(r.pink_tax_pct);
    if (v === null) return;
    if (!grouped[r.category]) grouped[r.category] = [];
    grouped[r.category].push(v);
  });
  const pairs = Object.entries(grouped)
    .map(([k, vals]) => ({ category: k, mean: mean(vals), n: vals.length }))
    .sort((a, b) => b.mean - a.mean)
    .slice(0, 12);

  Plotly.newPlot(
    "category-bar",
    [{ x: pairs.map((p) => p.category), y: pairs.map((p) => p.mean), type: "bar", marker: { color: "#1d3557" } }],
    {
      margin: { l: 40, r: 15, t: 10, b: 100 },
      xaxis: { tickangle: -30 },
      yaxis: { title: "Average Pink Tax %" },
      shapes: [{ type: "line", x0: -0.5, x1: pairs.length - 0.5, y0: 0, y1: 0, line: { color: "#555", dash: "dash" } }],
    },
    { responsive: true, displayModeBar: false }
  );
}

function renderExtremeTable(rows) {
  const withPink = rows
    .map((r) => ({ ...r, pinkTax: toNumber(r.pink_tax_pct) }))
    .filter((r) => r.pinkTax !== null)
    .sort((a, b) => Math.abs(b.pinkTax) - Math.abs(a.pinkTax))
    .slice(0, 15);

  extremeTableBody.innerHTML = withPink
    .map((r) => {
      const klass = r.pinkTax > 0 ? "bad" : r.pinkTax < 0 ? "good" : "";
      return `
        <tr>
          <td>${r.pair_code}</td>
          <td>${r.city}</td>
          <td>${r.retailer}</td>
          <td>${r.category}</td>
          <td>${r.brand}</td>
          <td class="${klass}">${r.pinkTax.toFixed(2)}</td>
        </tr>
      `;
    })
    .join("");
}

function renderAll() {
  const rows = applyFilters();
  renderMetricCards(rows);
  renderHistogram(rows);
  renderRetailerBar(rows);
  renderCityBox(rows);
  renderCategoryBar(rows);
  renderExtremeTable(rows);
}

function bindEvents() {
  [cityFilter, retailerFilter, categoryFilter].forEach((el) => {
    el.addEventListener("change", renderAll);
  });
  resetButton.addEventListener("click", () => {
    cityFilter.value = "ALL";
    retailerFilter.value = "ALL";
    categoryFilter.value = "ALL";
    renderAll();
  });
}

async function boot() {
  const response = await fetch(DATA_URL);
  if (!response.ok) {
    throw new Error(`Could not load ${DATA_URL}`);
  }
  const payload = await response.json();
  fullRecords = payload.records || [];

  fillSelect(cityFilter, payload.filters?.cities || []);
  fillSelect(retailerFilter, payload.filters?.retailers || []);
  fillSelect(categoryFilter, payload.filters?.categories || []);

  bindEvents();
  renderAll();
}

boot().catch((err) => {
  console.error(err);
  metricCards.innerHTML = `<article class="card"><div class="label">Error</div><div class="value">Could not load data</div></article>`;
});
