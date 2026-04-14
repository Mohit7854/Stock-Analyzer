const STORAGE_KEY = "sovereign_terminal_state_v2";

const state = {
  mode: "quick",
  activeTab: "analyze",
  history: [],
  showRawJson: false,
  lastSingle: null,
  lastCompare: null
};

const healthBadge = document.getElementById("healthBadge");
const runStatus = document.getElementById("runStatus");
const resultJson = document.getElementById("resultJson");
const resultPretty = document.getElementById("resultPretty");
const summaryCards = document.getElementById("summaryCards");
const rawJsonDetails = document.getElementById("rawJsonDetails");

const modeQuick = document.getElementById("modeQuick");
const modeDeep = document.getElementById("modeDeep");

const singleForm = document.getElementById("singleForm");
const compareForm = document.getElementById("compareForm");

const historyList = document.getElementById("historyList");
const clearHistoryBtn = document.getElementById("clearHistoryBtn");

const navButtons = Array.from(document.querySelectorAll(".nav-btn"));
const panels = {
  analyze: document.getElementById("panelAnalyze"),
  history: document.getElementById("panelHistory")
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function safeText(value, fallback) {
  const text = String(value === undefined || value === null ? "" : value).trim();
  return text || fallback;
}

function formatSeconds(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "-";
  return n.toFixed(1) + "s";
}

function formatDate(ts) {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleString();
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") {
      state.mode = parsed.mode === "deep" ? "deep" : "quick";
      state.activeTab = ["analyze", "history"].includes(parsed.activeTab) ? parsed.activeTab : "analyze";
      state.history = Array.isArray(parsed.history) ? parsed.history : [];
      state.showRawJson = !!parsed.showRawJson;
    }
  } catch (_) {
  }
}

function saveState() {
  const out = {
    mode: state.mode,
    activeTab: state.activeTab,
    history: state.history,
    showRawJson: state.showRawJson
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(out));
}

function setMode(mode) {
  state.mode = mode === "deep" ? "deep" : "quick";
  modeQuick.classList.toggle("active", state.mode === "quick");
  modeDeep.classList.toggle("active", state.mode === "deep");
  saveState();
}

function setTab(tab) {
  if (!panels[tab]) return;
  state.activeTab = tab;
  Object.keys(panels).forEach(function (key) {
    panels[key].classList.toggle("active", key === tab);
  });
  navButtons.forEach(function (btn) {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  saveState();
}

function setBusy(isBusy, text) {
  const actions = document.querySelectorAll(".action-btn");
  actions.forEach(function (btn) {
    btn.disabled = isBusy;
  });
  runStatus.textContent = text || (isBusy ? "Running..." : "Idle");
}

function summaryRow(label, value) {
  const row = el("div", "summary-item");
  const left = el("span", "", label);
  const right = el("strong", "", value === undefined || value === null ? "-" : String(value));
  row.append(left, right);
  return row;
}

function rubricToneClass(score) {
  const n = Number(score);
  if (!Number.isFinite(n)) return "rubric-mid";
  if (n >= 85) return "rubric-good";
  if (n >= 70) return "rubric-mid";
  return "rubric-low";
}

function criterionLabel(key) {
  const map = {
    trend_relevance: "Trend",
    sector_trend_fit: "Sector Fit",
    visual_text_alignment: "Alignment",
    quote_quality: "Quote",
    report_completeness: "Completeness"
  };
  return map[key] || key;
}

function createSummaryCard(title, summary) {
  const card = el("div", "summary-card");
  card.appendChild(el("h4", "", title));
  card.appendChild(summaryRow("Ticker", summary && summary.ticker));
  card.appendChild(summaryRow("Company", summary && summary.company));
  card.appendChild(summaryRow("Verdict", summary && summary.verdict));
  card.appendChild(summaryRow("Conviction", summary && summary.conviction));
  card.appendChild(summaryRow("Risk", summary && summary.risk));
  card.appendChild(summaryRow("Horizon", summary && summary.time_horizon));
  card.appendChild(summaryRow("Size %", summary && summary.position_size_pct));

  const rubric = summary && summary.rubric && typeof summary.rubric === "object" ? summary.rubric : null;
  if (rubric && rubric.normalized_score !== undefined && rubric.normalized_score !== null) {
    const tone = rubricToneClass(rubric.normalized_score);
    const badge = el(
      "div",
      "rubric-badge " + tone,
      "Rubric " + safeText(rubric.grade, "-") + " | " + String(rubric.normalized_score) + "/100"
    );
    card.appendChild(badge);

    const criteria = rubric.criteria && typeof rubric.criteria === "object" ? rubric.criteria : {};
    const grid = el("div", "rubric-grid");
    ["trend_relevance", "sector_trend_fit", "visual_text_alignment", "quote_quality", "report_completeness"].forEach(function (key) {
      const item = criteria[key] || {};
      const row = el("div", "rubric-row");
      row.appendChild(el("span", "", criterionLabel(key)));
      row.appendChild(el("strong", "", item.score !== undefined && item.score !== null ? String(item.score) + "/5" : "-"));
      grid.appendChild(row);
    });
    card.appendChild(grid);
  }

  return card;
}

function showJson(data) {
  resultJson.textContent = JSON.stringify(data, null, 2);
}

function verdictClass(verdict) {
  const v = safeText(verdict, "").toUpperCase();
  if (v.indexOf("BUY") !== -1) return "verdict-buy";
  if (v.indexOf("SELL") !== -1) return "verdict-sell";
  return "verdict-hold";
}

function createKpi(label, value) {
  const card = el("div", "kpi");
  card.appendChild(el("p", "", label));
  card.appendChild(el("p", "", value === undefined || value === null ? "-" : String(value)));
  return card;
}

function createReportSection(title, body, options) {
  const opts = options || {};
  const className = "report-section" + (opts.main ? " report-main" : "");
  const sec = el("section", className);
  sec.appendChild(el("h5", "", title));
  let text = safeText(body, "Not available");
  if (opts.main) {
    // Strip markdown heading markers so the final report reads cleanly in the styled card.
    text = text.replace(/^#{1,6}\s*/gm, "").replace(/\n{3,}/g, "\n\n").trim();
  }
  const maxChars = opts.full ? null : (opts.maxChars || 1300);
  const rendered = maxChars && text.length > maxChars ? text.slice(0, maxChars) + "..." : text;
  sec.appendChild(el("p", "report-text" + (opts.main ? " report-text-main" : ""), rendered));
  return sec;
}

function summarizeReportBits(text, maxChars) {
  const cleaned = safeText(text, "")
    .split(/\r?\n/)
    .map(function (line) { return line.trim(); })
    .filter(function (line) {
      const lower = line.toLowerCase();
      if (!line) return false;
      if (line.indexOf("##") === 0 || line.indexOf("###") === 0 || line.indexOf("#") === 0) return false;
      if (lower.indexOf("fallback") !== -1) return false;
      if (lower.indexOf("gemini request failed") !== -1) return false;
      if (lower.indexOf("rate_limited") !== -1) return false;
      if (lower.indexOf("tried:") !== -1) return false;
      return true;
    })
    .join(" ");
  if (!cleaned) return "Not available";
  return cleaned.length > maxChars ? cleaned.slice(0, maxChars) + "..." : cleaned;
}

function extractInsightLines(text) {
  const cleaned = summarizeReportBits(text, 560);
  if (cleaned === "Not available") {
    return ["No additional context available for this run."];
  }
  const lines = cleaned
    .split(/[.!?]\s+|\s+-\s+/)
    .map(function (part) { return part.trim(); })
    .filter(function (part) { return part.length > 18; });
  if (!lines.length) {
    return [cleaned];
  }
  return lines.slice(0, 3);
}

function createReportBit(body, tone, index) {
  const sec = el("section", "report-section report-bit-card");
  if (tone) {
    sec.classList.add(tone);
  }

  const glow = el("div", "report-bit-glow");
  const badge = el("div", "report-bit-badge", "Insight " + String(index || 1).padStart(2, "0"));

  const lines = extractInsightLines(body);
  const main = el("p", "report-bit-main", lines[0]);

  const list = el("ul", "report-bit-list");
  lines.slice(1).forEach(function (line) {
    list.appendChild(el("li", "", line));
  });

  sec.append(glow, badge, main, list);
  return sec;
}

function collectWarnings(output) {
  const warnings = [];
  if (output && output.signals && Array.isArray(output.signals.warnings)) {
    output.signals.warnings.forEach(function (w) { warnings.push(String(w)); });
  }
  const w = output && output.agent4_warnings ? output.agent4_warnings : {};
  ["signal_warnings", "stock_warnings", "rule_messages", "override_notes"].forEach(function (key) {
    if (Array.isArray(w[key])) {
      w[key].forEach(function (item) { warnings.push(String(item)); });
    }
  });
  if (output && output.agent4_critique) warnings.push(String(output.agent4_critique));

  const hiddenPatterns = [
    "signal conflict detected; conviction downgrade applied",
    "fallback mode used due to llm error",
    "gemini request failed for configured models",
    "fallback summary used because llm was unavailable",
    "fallback engine used due to llm unavailability",
    "deterministic synthesis applied due to temporary model unavailability"
  ];

  const clean = warnings
    .map(function (x) { return x.trim(); })
    .filter(Boolean)
    .filter(function (line) {
      const lower = line.toLowerCase();
      return !hiddenPatterns.some(function (p) { return lower.indexOf(p) !== -1; });
    });

  return Array.from(new Set(clean));
}

function renderSingleVisual(data) {
  const output = data && data.output ? data.output : {};
  const summary = data && data.summary ? data.summary : {};
  const structured = output.structured_output || {};

  const ticker = summary.ticker || output.ticker || "-";
  const company = summary.company || output.company || "-";
  const verdict = summary.verdict || structured.verdict || "-";
  const sizeValue = structured.position_size_pct !== undefined && structured.position_size_pct !== null
    ? String(structured.position_size_pct) + "%"
    : (summary.position_size_pct !== undefined && summary.position_size_pct !== null ? String(summary.position_size_pct) + "%" : "-");

  resultPretty.innerHTML = "";

  const hero = el("section", "report-hero");
  const top = el("div", "report-hero-top");
  const left = el("div", "");
  left.appendChild(el("h4", "report-title", company + " (" + ticker + ")"));
  left.appendChild(el("p", "report-sub", "Synthesis: " + safeText(data.synthesis_mode || output.mode, "-") + " | Runtime: " + formatSeconds(data.elapsed)));

  const chip = el("span", "verdict-chip " + verdictClass(verdict), "Verdict: " + verdict);
  top.append(left, chip);
  hero.appendChild(top);

  const kpi = el("div", "kpi-grid");
  kpi.appendChild(createKpi("Conviction", structured.conviction !== undefined ? structured.conviction : summary.conviction));
  kpi.appendChild(createKpi("Risk", structured.risk || summary.risk || "-"));
  kpi.appendChild(createKpi("Position", sizeValue));
  kpi.appendChild(createKpi("Horizon", structured.time_horizon || summary.time_horizon || "-"));
  kpi.appendChild(createKpi("Signal", output.signals ? output.signals.signal : "-"));
  kpi.appendChild(createKpi("Trend", output.signals ? output.signals.trend : "-"));
  hero.appendChild(kpi);

  resultPretty.appendChild(hero);

  const bitsGrid = el("div", "report-bits-grid");
  bitsGrid.appendChild(createReportBit(output.market_report, "report-bit-a", 1));
  bitsGrid.appendChild(createReportBit(output.technical_report, "report-bit-b", 2));
  bitsGrid.appendChild(createReportBit(output.fundamental_report, "report-bit-c", 3));
  resultPretty.appendChild(bitsGrid);

  resultPretty.appendChild(createReportSection("Report", output.final_report, { full: true, main: true }));
}

function renderCompareVisual(data) {
  resultPretty.innerHTML = "";
  const meta = data && data.comparison_meta && typeof data.comparison_meta === "object" ? data.comparison_meta : {};

  const hero = el("section", "report-hero");
  const top = el("div", "report-hero-top");
  const left = el("div", "");
  left.appendChild(el("h4", "report-title", "Comparison Analysis"));
  left.appendChild(el("p", "report-sub", "Mode: " + safeText(data.synthesis_mode || data.mode, "-") + " | Runtime: " + formatSeconds(data.elapsed_total)));
  const chip = el("span", "verdict-chip verdict-hold", "Winner: " + safeText(data.winner, "No clear winner"));
  top.append(left, chip);
  hero.appendChild(top);

  const kpi = el("div", "kpi-grid");
  kpi.appendChild(createKpi("Confidence", data.confidence || "-"));
  kpi.appendChild(createKpi("Stock A", data.stock_a_summary ? data.stock_a_summary.ticker : "-"));
  kpi.appendChild(createKpi("Stock B", data.stock_b_summary ? data.stock_b_summary.ticker : "-"));
  kpi.appendChild(createKpi("Synthesis", data.synthesis_mode || "-"));
  if (meta.rubric_delta !== undefined && meta.rubric_delta !== null) {
    const delta = Number(meta.rubric_delta);
    const deltaText = Number.isFinite(delta) ? (delta > 0 ? "+" + String(delta) : String(delta)) : String(meta.rubric_delta);
    kpi.appendChild(createKpi("Rubric Delta", deltaText));
  }
  if (meta.winner_basis) {
    kpi.appendChild(createKpi("Winner Basis", String(meta.winner_basis).replace(/_/g, " ")));
  }
  hero.appendChild(kpi);
  resultPretty.appendChild(hero);

  const a = data.stock_a_summary || {};
  const b = data.stock_b_summary || {};

  const winnerSummaryText =
    "Winner: " + safeText(data.winner, "-") + "\n" +
    "Confidence: " + safeText(data.confidence, "-") +
    (meta.winner_basis ? ("\nBasis: " + safeText(String(meta.winner_basis).replace(/_/g, " "), "-")) : "") +
    (meta.rubric_score_a !== undefined && meta.rubric_score_a !== null ? ("\nA Rubric: " + safeText(meta.rubric_score_a, "-")) : "") +
    (meta.rubric_score_b !== undefined && meta.rubric_score_b !== null ? ("\nB Rubric: " + safeText(meta.rubric_score_b, "-")) : "");

  const grid = el("div", "report-grid");
  grid.appendChild(createReportSection(
    "Stock A - " + safeText(a.ticker, "-"),
    "Verdict: " + safeText(a.verdict, "-") + "\n" +
    "Conviction: " + safeText(a.conviction, "-") + "\n" +
    "Risk: " + safeText(a.risk, "-") + "\n" +
    "Horizon: " + safeText(a.time_horizon, "-") + "\n" +
    "Size: " + safeText(a.position_size_pct, "-") + "%"
  ));
  grid.appendChild(createReportSection(
    "Stock B - " + safeText(b.ticker, "-"),
    "Verdict: " + safeText(b.verdict, "-") + "\n" +
    "Conviction: " + safeText(b.conviction, "-") + "\n" +
    "Risk: " + safeText(b.risk, "-") + "\n" +
    "Horizon: " + safeText(b.time_horizon, "-") + "\n" +
    "Size: " + safeText(b.position_size_pct, "-") + "%"
  ));
  grid.appendChild(createReportSection("Comparison Report", data.comparison_report));
  grid.appendChild(createReportSection("Winner Summary", winnerSummaryText));
  resultPretty.appendChild(grid);
}

function generateMarkdownReport(data) {
  if (!data) return "";
  const output = data.output || {};
  const summary = data.summary || {};
  const struct = output.structured_output || {};
  const ticker = summary.ticker || output.ticker || "UNKNOWN";
  const company = summary.company || output.company || "";
  
  let md = `# Equity Research Report\n\nTicker: **${ticker}**\nCompany: ${company}\nGenerated: ${new Date().toLocaleString()}\n\n`;
  
  md += `## Summary\n`;
  md += `- Verdict: ${struct.verdict || summary.verdict || "-"}\n`;
  md += `- Conviction: ${struct.conviction || summary.conviction || "-"}/10\n`;
  md += `- Risk: ${struct.risk || summary.risk || "-"}\n`;
  md += `- Position Size: ${struct.position_size_pct || summary.position_size_pct || "-"}%\n`;
  md += `- Time Horizon: ${struct.time_horizon || summary.time_horizon || "-"}\n\n`;
  
  const rubric = output.rubric || {};
  if (rubric.normalized_score !== undefined) {
    md += `## Quality Rubric\n`;
    md += `- Score: ${rubric.normalized_score}/100\n`;
    md += `- Grade: ${rubric.grade || "-"}\n\n`;
  }
  
  md += `## Market Report\n${output.market_report || "N/A"}\n\n`;
  md += `## Technical Analysis\n${output.technical_report || "N/A"}\n\n`;
  md += `## Fundamental Analysis\n${output.fundamental_report || "N/A"}\n\n`;
  md += `## Final Report\n${output.final_report || "N/A"}\n\n`;
  
  const warnings = output.agent4_warnings || {};
  if (warnings.override_notes && Array.isArray(warnings.override_notes) && warnings.override_notes.length) {
    md += `## Warnings\n`;
    warnings.override_notes.forEach(function(note) {
      md += `- ${note}\n`;
    });
    md += `\n`;
  }
  
  md += `---\n*This report was generated by an AI system and should not be considered financial advice.*\n`;
  return md;
}

function generateComparisonMarkdown(data) {
  if (!data) return "";
  const a = data.stock_a_summary || {};
  const b = data.stock_b_summary || {};
  
  let md = `# Comparison Analysis Report\n\nGenerated: ${new Date().toLocaleString()}\n\n`;
  
  md += `## Winner\n${data.winner || "N/A"}\n\n`;
  md += `## Confidence\n${data.confidence || "N/A"}\n\n`;
  
  md += `## Stock A - ${a.ticker || "Unknown"}\n`;
  md += `- Verdict: ${a.verdict || "-"}\n`;
  md += `- Conviction: ${a.conviction || "-"}/10\n`;
  md += `- Risk: ${a.risk || "-"}\n`;
  md += `- Position Size: ${a.position_size_pct || "-"}%\n\n`;
  
  md += `## Stock B - ${b.ticker || "Unknown"}\n`;
  md += `- Verdict: ${b.verdict || "-"}\n`;
  md += `- Conviction: ${b.conviction || "-"}/10\n`;
  md += `- Risk: ${b.risk || "-"}\n`;
  md += `- Position Size: ${b.position_size_pct || "-"}%\n\n`;
  
  md += `## Comparison Report\n${data.comparison_report || "N/A"}\n\n`;
  
  md += `---\n*This report was generated by an AI system and should not be considered financial advice.*\n`;
  return md;
}

function downloadReport(filename, content) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename || "report.md";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function renderSingle(data) {
  summaryCards.innerHTML = "";
  summaryCards.appendChild(createSummaryCard("Single Analysis Summary", data.summary));
  renderSingleVisual(data);
  showJson(data);
  
  const downloadBtn = document.getElementById("downloadReportBtn");
  if (downloadBtn) {
    downloadBtn.style.display = "inline-block";
    downloadBtn.onclick = function() {
      const ticker = (data.summary && data.summary.ticker) || (data.output && data.output.ticker) || "report";
      const filename = ticker + "_" + new Date().toISOString().split("T")[0] + ".md";
      const content = generateMarkdownReport(data);
      downloadReport(filename, content);
    };
  }
}

function renderCompare(data) {
  summaryCards.innerHTML = "";
  summaryCards.appendChild(createSummaryCard("Stock A Summary", data.stock_a_summary));
  summaryCards.appendChild(createSummaryCard("Stock B Summary", data.stock_b_summary));
  renderCompareVisual(data);
  showJson(data);
  
  const downloadBtn = document.getElementById("downloadReportBtn");
  if (downloadBtn) {
    downloadBtn.style.display = "inline-block";
    downloadBtn.onclick = function() {
      const a = data.stock_a_summary && data.stock_a_summary.ticker ? data.stock_a_summary.ticker : "A";
      const b = data.stock_b_summary && data.stock_b_summary.ticker ? data.stock_b_summary.ticker : "B";
      const filename = a + "_vs_" + b + "_" + new Date().toISOString().split("T")[0] + ".md";
      const content = generateComparisonMarkdown(data);
      downloadReport(filename, content);
    };
  }
}

function showError(err) {
  const msg = String(err);
  resultPretty.innerHTML = "";
  const sec = createReportSection("Request Error", msg);
  resultPretty.appendChild(sec);
  showJson({ error: msg });
}

function addHistoryEntry(entry) {
  state.history.unshift(entry);
  state.history = state.history.slice(0, 200);
  saveState();
  renderHistory();
}

function buildSingleHistoryTitle(query, data, ts) {
  const output = (data && data.output) || {};
  const summary = (data && data.summary) || {};
  const label = safeText(summary.ticker || output.ticker || query, "Single Report");
  return label + " - " + formatDate(ts);
}

function buildCompareHistoryTitle(stockA, stockB, data, ts) {
  const a = data && data.stock_a_summary ? data.stock_a_summary.ticker : stockA;
  const b = data && data.stock_b_summary ? data.stock_b_summary.ticker : stockB;
  return safeText(a, "Stock A") + " vs " + safeText(b, "Stock B") + " - " + formatDate(ts);
}

function renderHistory() {
  historyList.innerHTML = "";
  if (!state.history.length) {
    historyList.appendChild(el("p", "muted", "No reports yet. Run a single or comparison analysis to build history."));
    return;
  }

  state.history.forEach(function (item, index) {
    const card = el("div", "list-item");
    const top = el("div", "list-row");
    top.appendChild(el("div", "list-title", safeText(item.title, "Report")));
    top.appendChild(el("div", "list-meta", safeText(item.kind, "-").toUpperCase()));
    card.appendChild(top);

    const meta = el("div", "list-meta", "Created: " + formatDate(item.ts));
    card.appendChild(meta);

    const actions = el("div", "inline-actions");
    const openBtn = el("button", "btn-small", "Open");
    openBtn.dataset.action = "open-history";
    openBtn.dataset.index = String(index);

    const downloadBtn = el("button", "btn-small", "Download");
    downloadBtn.dataset.action = "download-history";
    downloadBtn.dataset.index = String(index);

    const removeBtn = el("button", "btn-small", "Delete");
    removeBtn.dataset.action = "delete-history";
    removeBtn.dataset.index = String(index);

    actions.append(openBtn, downloadBtn, removeBtn);
    card.appendChild(actions);
    historyList.appendChild(card);
  });
}

function openHistoryItem(index) {
  const item = state.history[index];
  if (!item || !item.payload) return;
  if (item.kind === "single") {
    state.lastSingle = item.payload;
    renderSingle(item.payload);
    runStatus.textContent = "Loaded from history";
  } else {
    state.lastCompare = item.payload;
    renderCompare(item.payload);
    runStatus.textContent = "Loaded from history";
  }
  setTab("analyze");
}

async function checkHealth() {
  try {
    const res = await fetch("/health");
    const body = await res.json();
    if (body.ok) {
      const checks = body.checks || {};
      healthBadge.textContent = "API Healthy | Gemini: " + (checks.gemini ? "OK" : "Down") + " | Tavily: " + (checks.tavily_api_key_configured ? "Configured" : "Missing");
      healthBadge.classList.remove("bad");
      healthBadge.classList.add("good");
    } else {
      healthBadge.textContent = "API Degraded | " + safeText(body.message, "Unknown issue");
      healthBadge.classList.remove("good");
      healthBadge.classList.add("bad");
    }
  } catch (_) {
    healthBadge.textContent = "Health check failed";
    healthBadge.classList.remove("good");
    healthBadge.classList.add("bad");
  }
}

async function runSingle(query) {
  setBusy(true, "Running single analysis...");
  try {
    const res = await fetch("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: query,
        mode: state.mode,
        save: false
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Single analysis failed");
    state.lastSingle = data;
    runStatus.textContent = "Done in " + Number(data.elapsed || 0).toFixed(1) + "s (" + safeText(data.synthesis_mode, "-") + ")";
    renderSingle(data);

    const ts = Date.now();
    addHistoryEntry({
      kind: "single",
      ts,
      title: buildSingleHistoryTitle(query, data, ts),
      payload: data
    });
  } catch (err) {
    runStatus.textContent = "Error";
    showError(err);
  } finally {
    setBusy(false, runStatus.textContent);
  }
}

async function runCompare(stockA, stockB) {
  setBusy(true, "Running comparison...");
  try {
    const res = await fetch("/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stock_a: stockA,
        stock_b: stockB,
        mode: state.mode,
        save: false
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Comparison failed");
    state.lastCompare = data;
    runStatus.textContent = "Comparison done (" + safeText(data.synthesis_mode, "-") + ") | Winner: " + safeText(data.winner, "-");
    renderCompare(data);

    const ts = Date.now();
    addHistoryEntry({
      kind: "compare",
      ts,
      title: buildCompareHistoryTitle(stockA, stockB, data, ts),
      payload: data
    });
  } catch (err) {
    runStatus.textContent = "Error";
    showError(err);
  } finally {
    setBusy(false, runStatus.textContent);
  }
}

function bindEvents() {
  modeQuick.addEventListener("click", function () { setMode("quick"); });
  modeDeep.addEventListener("click", function () { setMode("deep"); });

  navButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setTab(btn.dataset.tab);
    });
  });

  singleForm.addEventListener("submit", function (e) {
    e.preventDefault();
    const query = document.getElementById("singleQuery").value.trim();
    if (!query) return;
    setTab("analyze");
    runSingle(query);
  });

  compareForm.addEventListener("submit", function (e) {
    e.preventDefault();
    const stockA = document.getElementById("stockA").value.trim();
    const stockB = document.getElementById("stockB").value.trim();
    if (!stockA || !stockB) return;
    setTab("analyze");
    runCompare(stockA, stockB);
  });

  historyList.addEventListener("click", function (e) {
    const target = e.target;
    if (!target || !target.dataset) return;
    const idx = Number(target.dataset.index);
    if (!Number.isFinite(idx)) return;

    if (target.dataset.action === "open-history") {
      openHistoryItem(idx);
      return;
    }

    if (target.dataset.action === "download-history") {
      const item = state.history[idx];
      if (!item || !item.payload) return;
      
      if (item.kind === "single") {
        const ticker = (item.payload.summary && item.payload.summary.ticker) || (item.payload.output && item.payload.output.ticker) || "report";
        const filename = ticker + "_" + new Date().toISOString().split("T")[0] + ".md";
        const content = generateMarkdownReport(item.payload);
        downloadReport(filename, content);
      } else if (item.kind === "compare") {
        const a = item.payload.stock_a_summary && item.payload.stock_a_summary.ticker ? item.payload.stock_a_summary.ticker : "A";
        const b = item.payload.stock_b_summary && item.payload.stock_b_summary.ticker ? item.payload.stock_b_summary.ticker : "B";
        const filename = a + "_vs_" + b + "_" + new Date().toISOString().split("T")[0] + ".md";
        const content = generateComparisonMarkdown(item.payload);
        downloadReport(filename, content);
      }
      return;
    }

    if (target.dataset.action === "delete-history") {
      state.history.splice(idx, 1);
      saveState();
      renderHistory();
    }
  });

  clearHistoryBtn.addEventListener("click", function () {
    state.history = [];
    saveState();
    renderHistory();
  });
}

function init() {
  loadState();
  bindEvents();
  setMode(state.mode);
  setTab(state.activeTab);
  rawJsonDetails.open = state.showRawJson;

  renderHistory();

  resultPretty.innerHTML = "";
  resultPretty.appendChild(el("p", "muted", "Run an analysis to view the full report."));

  checkHealth();
}

init();
