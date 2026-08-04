let latestAnalysis = null;
let baseAnalysis = null;
const charts = {};
const ANALYSIS_STORAGE_KEY = "redmine-time-audit-last-analysis";
const GADGET_ORDER_KEY = "redmine-time-audit-gadget-order";

const palette = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2", "#4b5563", "#db2777", "#65a30d", "#ea580c"];

function byId(id) {
  return document.getElementById(id);
}

function hours(value) {
  return `${Number(value || 0).toFixed(2)}h`;
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function showError(message) {
  const box = byId("errorBox");
  box.textContent = message;
  box.classList.remove("d-none");
}

function clearError() {
  const box = byId("errorBox");
  box.textContent = "";
  box.classList.add("d-none");
}

function renderRows(targetId, rows, columns) {
  const tbody = byId(targetId);
  tbody.innerHTML = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = columns.length;
    td.className = "empty";
    td.textContent = "データがありません";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      const td = document.createElement("td");
      if (column.render) {
        td.appendChild(column.render(row[column.key], row));
      } else {
        td.textContent = column.format ? column.format(row[column.key], row) : (row[column.key] ?? "");
      }
      if (column.align === "end") td.className = "text-end";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function issueLink(value, row) {
  const text = value === "Issueなし" ? value : `#${value}`;
  const wrap = document.createElement("span");
  wrap.className = "issue-actions";
  if (value === "Issueなし") {
    wrap.appendChild(document.createTextNode(text));
    return wrap;
  }
  if (row.issue_url) {
    const link = document.createElement("a");
    link.href = row.issue_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = text;
    wrap.appendChild(link);
  } else {
    wrap.appendChild(document.createTextNode(text));
  }
  wrap.appendChild(issueDetailLink(value));
  return wrap;
}

function issueDetailUrl(issueId) {
  const criteria = latestAnalysis?.criteria || {};
  const params = new URLSearchParams({
    from: criteria.from || byId("fromDate").value,
    to: criteria.to || byId("toDate").value,
    sample_mode: String(Boolean(criteria.sample_mode)),
  });
  return `/issue-detail/${encodeURIComponent(issueId)}?${params.toString()}`;
}

function issueDetailLink(issueId) {
  const link = document.createElement("a");
  link.href = issueDetailUrl(issueId);
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.className = "detail-link";
  link.textContent = "詳細";
  return link;
}

function renderBarChart(id, labels, values, label) {
  if (charts[id]) charts[id].destroy();
  const textColor = cssVar("--text");
  const mutedColor = cssVar("--muted");
  const lineColor = cssVar("--line");
  charts[id] = new Chart(byId(id), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label,
        data: values,
        backgroundColor: labels.map((_, index) => palette[index % palette.length]),
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: cssVar("--panel"),
          titleColor: textColor,
          bodyColor: textColor,
          borderColor: lineColor,
          borderWidth: 1,
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: "hours", color: mutedColor },
          ticks: { color: mutedColor },
          grid: { color: lineColor },
        },
        x: {
          ticks: { autoSkip: false, maxRotation: 40, minRotation: 0, color: mutedColor },
          grid: { color: lineColor },
        },
      },
    },
  });
}

function renderSummary(summary) {
  byId("totalHours").textContent = hours(summary.total_hours);
  byId("userCount").textContent = summary.user_count;
  byId("issueCount").textContent = summary.issue_count;
  byId("entryCount").textContent = summary.entry_count;
  byId("avgHours").textContent = hours(summary.avg_hours_per_issue);
  byId("maxIssue").textContent = summary.max_issue ? `#${summary.max_issue.issue_id} / ${hours(summary.max_issue.hours)}` : "-";
}

function selectedVersions() {
  return Array.from(byId("versionFilter").selectedOptions).map((option) => option.value);
}

function renderVersionOptions(data) {
  const select = byId("versionFilter");
  select.innerHTML = "";
  (data.versions || []).forEach((version) => {
    const option = document.createElement("option");
    option.value = version;
    option.textContent = version;
    select.appendChild(option);
  });
  select.disabled = !(data.versions || []).length;
}

let userIssueSort = { key: "hours", direction: "desc" };

function sortUserIssueRows(rows) {
  const multiplier = userIssueSort.direction === "asc" ? 1 : -1;
  return [...rows].sort((left, right) => {
    const leftValue = Number(left[userIssueSort.key] || 0);
    const rightValue = Number(right[userIssueSort.key] || 0);
    return (leftValue - rightValue) * multiplier;
  });
}

function updateUserIssueSortIndicators() {
  document.querySelectorAll("#userIssueSortHeaders [data-sort-key]").forEach((button) => {
    const isActive = button.dataset.sortKey === userIssueSort.key;
    button.querySelector(".sort-indicator").textContent = isActive
      ? (userIssueSort.direction === "asc" ? "↑" : "↓")
      : "↕";
    button.setAttribute("aria-sort", isActive ? userIssueSort.direction : "none");
  });
}

function setupUserIssueSortHeaders() {
  const table = byId("userIssueTable")?.closest("table");
  const headerRow = table?.querySelector("thead tr");
  if (!headerRow) return;
  headerRow.id = "userIssueSortHeaders";
  [
    { index: 3, key: "hours", label: "合計時間" },
    { index: 5, key: "issue_status_count", label: "ステータス数" },
    { index: 6, key: "issue_transition_count", label: "遷移回数" },
  ].forEach(({ index, key, label }) => {
    const header = headerRow.children[index];
    const button = document.createElement("button");
    button.type = "button";
    button.className = "table-sort-button";
    button.dataset.sortKey = key;
    button.innerHTML = `${label} <span class="sort-indicator" aria-hidden="true">↕</span>`;
    button.addEventListener("click", () => {
      if (userIssueSort.key === key) {
        userIssueSort.direction = userIssueSort.direction === "asc" ? "desc" : "asc";
      } else {
        userIssueSort = { key, direction: "desc" };
      }
      updateUserIssueSortIndicators();
      renderUserIssueTable();
    });
    header.textContent = "";
    header.appendChild(button);
  });
  updateUserIssueSortIndicators();
}

function renderUserIssueTable() {
  const selectedUser = byId("userSelect").value;
  const rows = sortUserIssueRows(
    (latestAnalysis?.user_issue_top10 || []).filter((row) => row.user_name === selectedUser),
  );
  renderRows("userIssueTable", rows, [
    { key: "issue_id", render: issueLink },
    { key: "issue_subject" },
    { key: "issue_fixed_version_name" },
    { key: "hours", align: "end", format: hours },
    { key: "activity_breakdown" },
    { key: "issue_status_count", align: "end" },
    { key: "issue_transition_count", align: "end", format: (value) => `${value || 0}回` },
  ]);
}

function formatUpdatedAt(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function setLastUpdated(value) {
  byId("lastUpdated").textContent = `最終更新: ${formatUpdatedAt(value)}`;
}

function saveAnalysisState(data, updatedAt) {
  try {
    localStorage.setItem(ANALYSIS_STORAGE_KEY, JSON.stringify({
      data,
      baseData: baseAnalysis,
      updatedAt,
    }));
  } catch (error) {
    console.warn("分析結果を保存できませんでした", error);
  }
}

function restoreFormState(criteria) {
  if (!criteria) return;
  if (criteria.from) byId("fromDate").value = criteria.from;
  if (criteria.to) byId("toDate").value = criteria.to;
  if (criteria.project_id !== undefined) byId("projectId").value = criteria.project_id;
  if (criteria.sample_mode !== undefined) byId("sampleMode").checked = Boolean(criteria.sample_mode);
}

function restoreVersionSelection(criteria) {
  const selected = new Set(criteria?.versions || []);
  Array.from(byId("versionFilter").options).forEach((option) => {
    option.selected = selected.has(option.value);
  });
}

function setupGadgetDragging() {
  const grid = document.querySelector(".content-grid");
  if (!grid) return;

  const definitions = [
    ["#userRankingChart", "user-ranking"],
    ["#activityChart", "activity-summary"],
    ["#projectChart", "project-summary"],
    ["#userIssueTable", "user-issue-top10"],
    ["#alerts", "alerts"],
  ];
  const panels = Array.from(grid.querySelectorAll(":scope > .panel"));
  definitions.forEach(([selector, id]) => {
    document.querySelector(selector)?.closest(".panel")?.setAttribute("data-gadget-id", id);
  });

  try {
    const savedOrder = JSON.parse(localStorage.getItem(GADGET_ORDER_KEY) || "[]");
    const panelById = new Map(panels.map((panel) => [panel.dataset.gadgetId, panel]));
    savedOrder.forEach((id) => {
      const panel = panelById.get(id);
      if (panel) grid.appendChild(panel);
    });
  } catch (error) {
    localStorage.removeItem(GADGET_ORDER_KEY);
  }

  let draggedPanel = null;
  const saveOrder = () => {
    const order = Array.from(grid.querySelectorAll(":scope > .panel"))
      .map((panel) => panel.dataset.gadgetId)
      .filter(Boolean);
    localStorage.setItem(GADGET_ORDER_KEY, JSON.stringify(order));
  };

  grid.querySelectorAll(":scope > .panel").forEach((panel) => {
    panel.draggable = true;
    panel.addEventListener("dragstart", (event) => {
      if (!event.target.closest(".panel-header") || event.target.closest("button, select, input, a")) {
        event.preventDefault();
        return;
      }
      draggedPanel = panel;
      panel.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", panel.dataset.gadgetId || "");
    });
    panel.addEventListener("dragend", () => {
      panel.classList.remove("is-dragging");
      draggedPanel = null;
      saveOrder();
    });
  });

  grid.addEventListener("dragover", (event) => {
    if (!draggedPanel) return;
    event.preventDefault();
    const target = event.target.closest(".panel");
    if (!target || target.parentElement !== grid || target === draggedPanel) return;
    const rect = target.getBoundingClientRect();
    const insertAfter = event.clientY > rect.top + rect.height / 2;
    grid.insertBefore(draggedPanel, insertAfter ? target.nextSibling : target);
  });
}

function renderAlerts(alerts) {
  const container = byId("alerts");
  container.innerHTML = "";
  if (!alerts.length) {
    const div = document.createElement("div");
    div.className = "alert-item calm";
    div.innerHTML = "<strong>大きなアラートはありません</strong><span>現在の条件では棚卸ルールに該当する偏りは見つかりませんでした。</span>";
    container.appendChild(div);
    return;
  }
  alerts.forEach((alert) => {
    const div = document.createElement("div");
    div.className = "alert-item";
    const strong = document.createElement("strong");
    strong.textContent = alert.type;
    const span = document.createElement("span");
    appendAlertMessage(span, alert);
    div.appendChild(strong);
    div.appendChild(span);
    container.appendChild(div);
  });
}

function appendAlertMessage(container, alert) {
  if (!alert.issue_id) {
    container.textContent = alert.message;
    return;
  }

  const marker = `#${alert.issue_id}`;
  const parts = alert.message.split(marker);
  container.appendChild(document.createTextNode(parts[0]));

  if (alert.issue_url) {
    const link = document.createElement("a");
    link.href = alert.issue_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = marker;
    container.appendChild(link);
  } else {
    container.appendChild(document.createTextNode(marker));
  }
  container.appendChild(document.createTextNode(parts.slice(1).join(marker)));
  container.appendChild(document.createTextNode(" "));
  container.appendChild(issueDetailLink(alert.issue_id));
}

function renderAnalysis(data, options = {}) {
  latestAnalysis = data;
  restoreFormState(data.criteria);
  byId("excelExportButton").disabled = false;
  if (options.updateVersionOptions) {
    renderVersionOptions(data);
    restoreVersionSelection(data.criteria);
  }
  const versionCount = selectedVersions().length;
  const sourceLabel = data.source === "sample" ? "サンプルデータ" : "Redmine API";
  byId("sourceBadge").textContent = versionCount ? `${sourceLabel} / ${versionCount}バージョン` : sourceLabel;
  renderSummary(data.summary);

  renderRows("userRankingTable", data.user_ranking, [
    { key: "user_name" },
    { key: "hours", align: "end", format: hours },
  ]);
  renderRows("activityTable", data.activity_summary, [
    { key: "activity_name" },
    { key: "hours", align: "end", format: hours },
  ]);
  renderRows("projectTable", data.project_summary, [
    { key: "project_name" },
    { key: "hours", align: "end", format: hours },
  ]);

  renderBarChart("userRankingChart", data.user_ranking.map((r) => r.user_name), data.user_ranking.map((r) => r.hours), "ユーザー別");
  renderBarChart("activityChart", data.activity_summary.map((r) => r.activity_name), data.activity_summary.map((r) => r.hours), "作業分類別");
  renderBarChart("projectChart", data.project_summary.map((r) => r.project_name), data.project_summary.map((r) => r.hours), "プロジェクト別");

  const userSelect = byId("userSelect");
  userSelect.innerHTML = "";
  data.users.forEach((user) => {
    const option = document.createElement("option");
    option.value = user;
    option.textContent = user;
    userSelect.appendChild(option);
  });
  renderUserIssueTable();
  renderAlerts(data.alerts);
  const updatedAt = options.updatedAt || new Date().toISOString();
  setLastUpdated(updatedAt);
  if (options.persist !== false) {
    saveAnalysisState(data, updatedAt);
  }
}

async function applyPreset() {
  const preset = byId("quarterPreset").value;
  if (!preset) return;
  const response = await fetch(`/api/preset-range?preset=${encodeURIComponent(preset)}`);
  const data = await response.json();
  if (!response.ok) {
    showError(data.error || "四半期プリセットの取得に失敗しました。");
    return;
  }
  byId("fromDate").value = data.from;
  byId("toDate").value = data.to;
}

async function analyze() {
  clearError();
  latestAnalysis = null;
  baseAnalysis = null;
  byId("analyzeButton").disabled = true;
  byId("excelExportButton").disabled = true;
  byId("analyzeButton").textContent = "分析中";
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        from: byId("fromDate").value,
        to: byId("toDate").value,
        project_id: byId("projectId").value,
        sample_mode: byId("sampleMode").checked,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      showError(data.error || "分析に失敗しました。");
      return;
    }
    baseAnalysis = data;
    renderAnalysis(data, { updateVersionOptions: true });
  } catch (error) {
    showError("通信に失敗しました。Flaskアプリが起動しているか確認してください。");
  } finally {
    byId("analyzeButton").disabled = false;
    byId("analyzeButton").textContent = "分析実行";
  }
}

async function applyVersionFilter() {
  if (!baseAnalysis) return;
  clearError();
  const select = byId("versionFilter");
  select.disabled = true;
  try {
    const response = await fetch("/api/filter-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        raw_time_entries: baseAnalysis.raw_time_entries,
        redmine_url: baseAnalysis.redmine_url,
        source: baseAnalysis.source,
        criteria: baseAnalysis.criteria,
        versions: selectedVersions(),
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      showError(data.error || "バージョン絞り込みに失敗しました。");
      return;
    }
    data.versions = baseAnalysis.versions;
    renderAnalysis(data);
  } catch (error) {
    showError("バージョン絞り込みに失敗しました。");
  } finally {
    select.disabled = !(baseAnalysis.versions || []).length;
  }
}

async function exportCsv(exportName) {
  if (!latestAnalysis) {
    showError("先に分析を実行してください。");
    return;
  }
  const response = await fetch(`/api/export/${exportName}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data: latestAnalysis }),
  });
  if (!response.ok) {
    const data = await response.json();
    showError(data.error || "CSV出力に失敗しました。");
    return;
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${exportName}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function exportExcel() {
  if (!latestAnalysis) {
    showError("先に分析を実行してください。");
    return;
  }
  const button = byId("excelExportButton");
  button.disabled = true;
  button.textContent = "Excel生成中";
  try {
    const response = await fetch("/api/export-excel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data: latestAnalysis }),
    });
    if (!response.ok) {
      const data = await response.json();
      showError(data.error || "Excel出力に失敗しました。");
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "redmine_time_audit_report.xlsx";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } finally {
    button.disabled = false;
    button.textContent = "Excel出力";
  }
}

byId("quarterPreset").addEventListener("change", applyPreset);
byId("analyzeButton").addEventListener("click", analyze);
byId("excelExportButton").addEventListener("click", exportExcel);
byId("versionFilter").addEventListener("change", applyVersionFilter);
byId("userSelect").addEventListener("change", renderUserIssueTable);
document.querySelectorAll(".export-button").forEach((button) => {
  button.addEventListener("click", () => exportCsv(button.dataset.export));
});
setupUserIssueSortHeaders();
setupGadgetDragging();
document.addEventListener("themechange", () => {
  if (latestAnalysis) {
    renderAnalysis(latestAnalysis, { persist: false });
  }
});

function restoreLastAnalysis() {
  try {
    const stored = JSON.parse(localStorage.getItem(ANALYSIS_STORAGE_KEY) || "null");
    if (!stored?.data) return;
    baseAnalysis = stored.baseData || stored.data;
    renderAnalysis(stored.data, {
      updateVersionOptions: true,
      persist: false,
      updatedAt: stored.updatedAt,
    });
  } catch (error) {
    localStorage.removeItem(ANALYSIS_STORAGE_KEY);
  }
}

restoreLastAnalysis();
