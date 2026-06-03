const STORAGE = {
  history: "sfr_chat_history",
  saved: "sfr_saved_reports",
  theme: "sfr_theme",
  lastQuery: "sfr_last_query",
};

const $ = (sel) => document.querySelector(sel);
const chatMessages = $("#chat-messages");
const chatForm = $("#chat-form");
const chatInput = $("#chat-input");
const kpiRow = $("#kpi-row");
const chartArea = $("#chart-area");
const chartSummary = $("#chart-summary");
const dataTable = $("#data-table");
const tableMeta = $("#table-meta");
const quickQueriesEl = $("#quick-queries");
const chatHistoryEl = $("#chat-history");
const savedReportsEl = $("#saved-reports");
const btnDownloadChart = $("#btn-download-chart");

let lastResponse = null;
let lastChart = null;


function loadJSON(key, fallback) {
  try {
    // Keep history and saved reports session-scoped
    if (key === STORAGE.history || key === STORAGE.saved) {
      return JSON.parse(sessionStorage.getItem(key)) || fallback;
    }
    return JSON.parse(localStorage.getItem(key)) || fallback;
  } catch {
    return fallback;
  }
}

function saveJSON(key, value) {
  if (key === STORAGE.history || key === STORAGE.saved) {
    sessionStorage.setItem(key, JSON.stringify(value));
  } else {
    localStorage.setItem(key, JSON.stringify(value));
  }
}

function md(text) {
  return String(text || "")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

async function fetchKpis() {
  const res = await fetch("/api/kpis");
  const kpis = await res.json();
  renderKpis(kpis);
}

function renderKpis(k) {
  const cards = [
    { label: "Total Failures", value: k.total_failures?.toLocaleString() },
    { label: "Avg Repair Time", value: `${k.avg_repair_time} min` },
    { label: "Worst Station", value: k.worst_station },
    { label: "Peak Month", value: k.peak_month },
    { label: "Trains Detained", value: k.trains_detained_total?.toLocaleString() },
    { label: "Top Gear", value: k.top_gear },
  ];
  kpiRow.innerHTML = cards
    .map(
      (c, i) => `
    <div class="kpi-card" style="animation-delay:${i * 0.06}s">
      <div class="label">${c.label}</div>
      <div class="value">${c.value ?? "—"}</div>
    </div>`
    )
    .join("");
}


async function loadQuickQueries() {
  const res = await fetch("/api/quick-queries");
  const data = await res.json();
  quickQueriesEl.innerHTML = data.queries
    .map((q) => `<button type="button" class="chip" data-q="${encodeURIComponent(q)}">${q}</button>`)
    .join("");
  quickQueriesEl.querySelectorAll(".chip").forEach((btn) => {
    btn.addEventListener("click", () => runQuery(decodeURIComponent(btn.dataset.q), true, true));
  });
}

function renderHistory() {
  const history = loadJSON(STORAGE.history, []);
  chatHistoryEl.innerHTML =
    history.length === 0
      ? '<span class="muted">No history yet</span>'
      : history
          .slice(0, 20)
          .map(
            (h, i) =>
              `<div class="history-item" data-i="${i}">${h.query.slice(0, 42)}${h.query.length > 42 ? "…" : ""}</div>`
          )
          .join("");
  chatHistoryEl.querySelectorAll(".history-item").forEach((el) => {
    el.addEventListener("click", () => {
      const h = history[Number(el.dataset.i)];
      if (h) runQuery(h.query, false);
    });
  });
}

function renderSaved() {
  const saved = loadJSON(STORAGE.saved, []);
  savedReportsEl.innerHTML =
    saved.length === 0
      ? '<span class="muted">No saved reports</span>'
      : saved
          .map(
            (s, i) =>
              `<div class="history-item saved-item" data-s="${i}">${s.title.slice(0, 40)}</div>`
          )
          .join("");
  savedReportsEl.querySelectorAll(".saved-item").forEach((el) => {
    el.addEventListener("click", () => {
      const s = saved[Number(el.dataset.s)];
      if (!s) return;
      showSavedModal(s);
    });
  });
}

function showSavedModal(saved) {
  const modal = $("#saved-modal");
  const content = $("#modal-content");
  const restoreBtn = $("#modal-restore");
  const closeBtns = [$("#modal-close"), $("#modal-close-2"), $("#modal-backdrop")];
  if (!modal || !content) return;
  // populate content
  const resp = saved.response || {};
  const ins = resp.insight || {};
  const chartSpec = resp.chart;
  content.innerHTML = `
    <h3>${escapeHtml(saved.title || "Report")}</h3>
    <div class="modal-summary"><p>${escapeHtml(resp.message || "")}</p>
      <div>${md(ins.key_insight || "")}</div>
    </div>
    <div id="modal-chart" class="modal-chart"></div>
    <div class="modal-suggestions"></div>
  `;

  // render chart if present
  if (chartSpec) {
    const normalized = normalizePlotlySpec(chartSpec);
    try {
      Plotly.newPlot($("#modal-chart"), normalized.data, normalized.layout || {}, {responsive:true});
    } catch (e) { /* ignore */ }
  } else {
    $("#modal-chart").innerHTML = '<p class="muted">No chart available</p>';
  }

  // modal suggestion buttons removed

  // restore button
  restoreBtn.onclick = () => {
    // Replace chat with saved report view to avoid heavy scrolling
    chatMessages.innerHTML = "";
    const sessionEntries = saved.session || [];
    if (sessionEntries.length) {
      const collapsed = document.createElement('div');
      collapsed.className = 'insight-card collapsed-session';
      collapsed.innerHTML = `<strong>${sessionEntries.length} earlier messages</strong> <button class="btn small" id="expand-session">Show</button>`;
      chatMessages.appendChild(collapsed);
      const expBtn = collapsed.querySelector('#expand-session');
      expBtn.addEventListener('click', () => {
        // render simple history items (no re-run)
        sessionEntries.slice(0).reverse().forEach(h => {
          const d = document.createElement('div');
          d.className = 'msg-user';
          d.textContent = h.query || h.title || '';
          chatMessages.insertBefore(d, collapsed);
        });
        expBtn.remove();
      });
    }

    // restore session into sessionStorage for later
    if (sessionEntries.length) {
      saveJSON(STORAGE.history, sessionEntries || []);
      renderHistory();
    }

    if (saved.response) {
      displayResponse(saved.query || '', saved.response, false);
      // ensure the restored response is visible
      const last = chatMessages.lastElementChild;
      try { if (last && typeof last.scrollIntoView === 'function') last.scrollIntoView({behavior:'smooth', block:'center'}); } catch(e) {}
    }
    closeModal();
  };

  // close handlers
  closeBtns.forEach((el)=>{ if (el) el.onclick = closeModal; });

  modal.classList.remove('hidden');
}

function closeModal() {
  const modal = $("#saved-modal");
  if (!modal) return;
  // destroy any plotly in modal
  try { Plotly.purge($("#modal-chart")); } catch (e) {}
  modal.classList.add('hidden');
}

function pushHistory(query, response) {
  const history = loadJSON(STORAGE.history, []);
  history.unshift({ query, ts: Date.now(), title: response.title });
  saveJSON(STORAGE.history, history.slice(0, 50));
  renderHistory();
}

function addUserMessage(text) {
  const div = document.createElement("div");
  div.className = "msg-user";
  div.textContent = text;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function renderInsightBlock(title, content) {
  if (!content) return "";
  return `<div class="insight-card"><h4>${title}</h4><p>${md(content)}</p></div>`;
}

function renderSummaryLines(lines) {
  if (!lines?.length) return "";
  const items = lines.map((l, i) => `<li>${escapeHtml(l)}</li>`).join("");
  return `<div class="insight-card summary-list"><h4>Data Summary</h4><ol>${items}</ol></div>`;
}

function renderFailureCards(cards) {
  if (!cards?.length) return "";
  return cards
    .map(
      (f) => `
    <div class="failure-card">
      <h5>Failure ${f.index}</h5>
      <p><span>Station</span> ${escapeHtml(f.station)}</p>
      <p><span>Gear</span> ${escapeHtml(f.gear)}</p>
      ${f.sub_gear ? `<p><span>Sub Gear</span> ${escapeHtml(f.sub_gear)}</p>` : ""}
      <p><span>Cause</span> ${escapeHtml(f.cause)}</p>
      ${f.train_detained ? `<p><span>Train Detained</span> ${escapeHtml(f.train_detained)}</p>` : ""}
      ${f.duration !== "" ? `<p><span>Duration</span> ${escapeHtml(f.duration)} mins</p>` : ""}
      ${f.time ? `<p><span>Time</span> ${escapeHtml(f.time)}</p>` : ""}
      ${f.chargeable ? `<p><span>Chargeable</span> ${escapeHtml(f.chargeable)}</p>` : ""}
    </div>`
    )
    .join("");
}

function displayResponse(query, data, saveHist = true) {
  lastResponse = data;
  const ins = data.insight || {};
  const hasCards = data.failure_cards?.length > 0;
  const wrap = document.createElement("div");
  const status = "";
  wrap.innerHTML = `
    ${status}
    ${!hasCards ? `<div class="insight-card">
    <h4>Answer</h4>
    <p>${md(ins.key_insight)}</p>
</div>` : ""}
    ${ins.analysis ? renderInsightBlock("Detailed Analysis", ins.analysis) : ""}
    ${ins.filters_applied ? renderInsightBlock("Filters", ins.filters_applied + " · " + (ins.records_matched ?? "")) : ""}
  `;
    // suggestions removed per user request
    wrap.appendChild(document.createElement("div"));
  chatMessages.appendChild(wrap);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  if (data.chart) {
    renderChart(data.chart);
    chartSummary.textContent = ins.chart_summary || "";
    btnDownloadChart.disabled = false;
    lastChart = data.chart;
  } else {
    chartArea.innerHTML = '<p class="placeholder">No chart for this query — see table below</p>';
    chartSummary.textContent = ins.chart_summary || "";
    btnDownloadChart.disabled = true;
  }

  // Render EITHER failure cards OR tables, not both
  if (hasCards) {
    // Show only failure cards in chat, hide table panel entirely
    const cardsWrap = document.createElement("div");
    cardsWrap.className = "failure-cards";
    cardsWrap.innerHTML = renderFailureCards(data.failure_cards);
    chatMessages.appendChild(cardsWrap);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    // Hide the entire table panel
    if (dataTable) dataTable.style.display = "none";
    if (tableMeta) tableMeta.style.display = "none";
  } else {
    // Show only tables in side panel when no cards
    if (dataTable) dataTable.style.display = "";
    if (tableMeta) tableMeta.style.display = "";
    
    const failureTable = data.failure_table || data.table;
    const summaryTable = data.summary_table || data.ranking_table;
    renderTables(failureTable, summaryTable);
  }
  if (saveHist) pushHistory(query, data);
}

function decodePlotlyBinary(obj) {
  if (!obj || typeof obj !== "object") return obj;
  if (!obj.bdata || !obj.dtype || !obj.shape) return obj;

  const raw = atob(obj.bdata);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) {
    bytes[i] = raw.charCodeAt(i);
  }

  const shape = String(obj.shape)
    .split(",")
    .map((v) => Number(v.trim()));

  let typed;
  switch (obj.dtype) {
    case "f8":
      typed = new Float64Array(bytes.buffer);
      break;
    case "f4":
      typed = new Float32Array(bytes.buffer);
      break;
    case "i4":
      typed = new Int32Array(bytes.buffer);
      break;
    case "i2":
      typed = new Int16Array(bytes.buffer);
      break;
    case "i1":
      typed = new Int8Array(bytes.buffer);
      break;
    case "u4":
      typed = new Uint32Array(bytes.buffer);
      break;
    case "u2":
      typed = new Uint16Array(bytes.buffer);
      break;
    case "u1":
      typed = new Uint8Array(bytes.buffer);
      break;
    default:
      typed = new Float64Array(bytes.buffer);
  }

  if (shape.length === 1) {
    return Array.from(typed);
  }

  const [rows, cols] = shape;
  const matrix = [];
  for (let i = 0; i < rows; i++) {
    const start = i * cols;
    matrix.push(Array.from(typed.slice(start, start + cols)));
  }
  return matrix;
}

function normalizePlotlySpec(spec) {
  const copy = JSON.parse(JSON.stringify(spec));
  (copy.data || []).forEach((trace) => {
    if (trace.z && !Array.isArray(trace.z)) {
      if (trace.z.bdata && trace.z.dtype && trace.z.shape) {
        trace.z = decodePlotlyBinary(trace.z);
      } else {
        const keys = Object.keys(trace.z).sort((a, b) => Number(a) - Number(b));
        trace.z = keys.map((k) => trace.z[k]);
      }
    }
  });
  return copy;
}

function renderChart(spec) {
  chartArea.innerHTML = "";

  const normalized = normalizePlotlySpec(spec);

  const layout = {
    ...normalized.layout,
    autosize: true,
    margin: {
      l: 80,
      r: 40,
      t: 50,
      b: 100
    },
    template:
      document.documentElement.dataset.theme === "light"
        ? "plotly_white"
        : "plotly_dark",
  };

  Plotly.newPlot(
    chartArea,
    normalized.data,
    layout,
    {
      responsive: true,
      displayModeBar: true,
      modeBarButtonsToRemove: ["lasso2d", "select2d"],
    }
  );

  setTimeout(() => {
    Plotly.Plots.resize(chartArea);
  }, 200);
}
function renderTables(failureTable, summaryTable) {
  if (!dataTable) return; // Raw records panel removed; avoid DOM errors
  const thead = dataTable.querySelector("thead");
  const tbody = dataTable.querySelector("tbody");
  const table = failureTable || summaryTable;
  if (!table?.rows?.length) {
    thead.innerHTML = "";
    tbody.innerHTML =
      '<tr><td colspan="10" class="muted">No matching failure records. Try widening your filters.</td></tr>';
    tableMeta.textContent = "";
    return;
  }

  let html = "";
  if (summaryTable?.rows?.length && failureTable?.rows?.length) {
    html += `<tr class="section-row"><td colspan="${failureTable.columns.length}"><strong>${summaryTable.title || "Summary"}</strong> (${summaryTable.showing} rows)</td></tr>`;
    html += summaryTable.rows
      .map(
        (row) =>
          `<tr class="summary-row">${summaryTable.columns
            .map((c) => `<td>${escapeHtml(row[c] ?? "")}</td>`)
            .join("")}${"<td></td>".repeat(Math.max(0, failureTable.columns.length - summaryTable.columns.length))}</tr>`
      )
      .join("");
    html += `<tr class="section-row"><td colspan="${failureTable.columns.length}"><strong>${failureTable.title || "Failure records"}</strong> — full list</td></tr>`;
  }

  thead.innerHTML = `<tr>${table.columns.map((c) => `<th>${c}</th>`).join("")}</tr>`;
  const rows = failureTable?.rows?.length ? failureTable.rows : table.rows;
  const cols = failureTable?.columns || table.columns;
  html += rows
    .map(
      (row) =>
        `<tr>${cols.map((c) => `<td>${escapeHtml(row[c] ?? "")}</td>`).join("")}</tr>`
    )
    .join("");
  tbody.innerHTML = html;

  const total = failureTable?.total ?? table.total;
  const showing = failureTable?.showing ?? table.showing;
  tableMeta.textContent =
    failureTable?.rows?.length
      ? `${failureTable.title || "Failures"}: showing all ${showing} of ${total} records`
      : `Showing ${showing} of ${total} records`;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function runQuery(message, saveHist = true, fromQuick = false) {
  if (!message?.trim()) return;
  addUserMessage(message);
  const typing = document.createElement("div");
  typing.className = "typing";
  typing.textContent = "Analyzing…";
  chatMessages.appendChild(typing);
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const data = await res.json();
    typing.remove();
    if (!res.ok) {
      addUserMessage(data.error || "Request failed");
      return;
    }
    displayResponse(message, data, saveHist);

    if (fromQuick) {
      const last = chatMessages.lastElementChild;
      try {
        if (last && typeof last.scrollIntoView === "function") last.scrollIntoView({ behavior: "smooth", block: "center" });
      } catch (e) {}
    }

    saveJSON(STORAGE.lastQuery, message);
  } catch (e) {
    typing.remove();
    const err = document.createElement("div");
    err.className = "insight-card";
    err.innerHTML = "<h4>Error</h4><p>Server not reachable. Run <code>python app.py</code> from the project folder.</p>";
    chatMessages.appendChild(err);
  }
}



chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const msg = chatInput.value.trim();
  if (!msg) return;
  chatInput.value = "";
  runQuery(msg);
});



// Upload input removed — uploads disabled


$("#btn-theme").addEventListener("click", () => {
  const html = document.documentElement;
  const next = html.dataset.theme === "dark" ? "light" : "dark";
  html.dataset.theme = next;
  saveJSON(STORAGE.theme, next);
  if (lastChart) renderChart(lastChart);
});

$("#btn-download-chart").addEventListener("click", () => {
  Plotly.downloadImage(chartArea, { format: "png", filename: "sfr_chart", height: 600, width: 1000 });
});

$("#btn-save-report").addEventListener("click", () => {
  if (!lastResponse) return;
  const saved = loadJSON(STORAGE.saved, []);
  const sessionHistory = loadJSON(STORAGE.history, []);
  saved.unshift({
    title: lastResponse.title || "Report",
    query: loadJSON(STORAGE.lastQuery, ""),
    response: lastResponse,
    session: sessionHistory,
    ts: Date.now(),
  });
  saveJSON(STORAGE.saved, saved.slice(0, 20));
  renderSaved();
});

document.documentElement.dataset.theme = loadJSON(STORAGE.theme, "dark");

(async function init() {
  await fetchKpis();
  await loadQuickQueries();
  renderHistory();
  renderSaved();
  const welcome = document.createElement("div");
  welcome.className = "insight-card";
  welcome.innerHTML =
    "<h4>Welcome</h4><p>Enterprise SFR analytics with charts, tables, KPIs, and export. Pick a quick query or ask in natural language.</p>";
  chatMessages.appendChild(welcome);
})();
// ensure chat panel is visible and focused on load
// No auto-scroll on load (feature removed)
