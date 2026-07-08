function byId(id) {
  return document.getElementById(id);
}

function hours(value) {
  return `${Number(value || 0).toFixed(2)}h`;
}

function showError(message) {
  const box = byId("detailErrorBox");
  box.textContent = message;
  box.classList.remove("d-none");
}

function flowUrl() {
  const shell = document.querySelector(".detail-shell");
  const params = new URLSearchParams({
    from: shell.dataset.from,
    to: shell.dataset.to,
    sample_mode: shell.dataset.sampleMode,
  });
  return `/api/issue-flow/${encodeURIComponent(shell.dataset.issueId)}?${params.toString()}`;
}

function renderFlow(data) {
  byId("issueTitle").textContent = `Issue #${data.issue.id} ${data.issue.subject}`;
  byId("issueMeta").textContent = `現在ステータス: ${data.issue.status || "-"} / ステータス別に作業時間を按分表示`;
  byId("detailIssueId").textContent = `#${data.issue.id}`;
  byId("detailPeriod").textContent = `${document.querySelector(".detail-shell").dataset.from} - ${document.querySelector(".detail-shell").dataset.to}`;
  byId("detailTotalHours").textContent = hours(data.issue.total_hours);
  byId("detailStatusCount").textContent = data.nodes.length;

  const redmineLink = byId("redmineIssueLink");
  if (data.issue.url) {
    redmineLink.href = data.issue.url;
  } else {
    redmineLink.classList.add("disabled");
  }

  renderFlowDiagram(data.nodes);
  renderBreakdown(data.nodes);
  renderTransitions(data.transitions);
}

function renderFlowDiagram(nodes) {
  const container = byId("flowDiagram");
  container.innerHTML = "";
  if (!nodes.length) {
    container.textContent = "ステータス遷移がありません。";
    return;
  }

  nodes.forEach((node, index) => {
    const nodeEl = document.createElement("div");
    nodeEl.className = "flow-node";
    nodeEl.style.setProperty("--intensity", String(Math.max(node.share, 0.12)));

    const inner = document.createElement("div");
    inner.className = "flow-node-inner";

    const label = document.createElement("strong");
    label.textContent = node.status_name;
    const value = document.createElement("span");
    value.textContent = hours(node.hours);
    const bar = document.createElement("div");
    bar.className = "flow-node-bar";
    bar.style.width = `${Math.max(node.share * 100, node.hours > 0 ? 12 : 0)}%`;

    inner.appendChild(label);
    inner.appendChild(value);
    inner.appendChild(bar);
    nodeEl.appendChild(inner);
    container.appendChild(nodeEl);

    if (index < nodes.length - 1) {
      const arrow = document.createElement("div");
      arrow.className = "flow-arrow";
      arrow.textContent = "→";
      container.appendChild(arrow);
    }
  });
}

function renderBreakdown(nodes) {
  const container = byId("statusBreakdown");
  container.innerHTML = "";
  nodes.forEach((node) => {
    const item = document.createElement("div");
    item.className = "status-item";
    const header = document.createElement("div");
    header.className = "status-item-header";
    header.innerHTML = `<strong>${node.status_name}</strong><span>${hours(node.hours)} / ${node.entry_count}件</span>`;
    item.appendChild(header);

    const list = document.createElement("ul");
    if (node.activities.length) {
      node.activities.forEach((activity) => {
        const li = document.createElement("li");
        li.textContent = `${activity.activity_name}: ${hours(activity.hours)}`;
        list.appendChild(li);
      });
    } else {
      const li = document.createElement("li");
      li.textContent = "作業時間なし";
      list.appendChild(li);
    }
    item.appendChild(list);
    container.appendChild(item);
  });
}

function renderTransitions(transitions) {
  const tbody = byId("transitionTable");
  tbody.innerHTML = "";
  if (!transitions.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 2;
    td.className = "empty";
    td.textContent = "ステータス変更履歴がありません";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  transitions.forEach((transition) => {
    const tr = document.createElement("tr");
    const date = document.createElement("td");
    date.textContent = transition.changed_at ? transition.changed_at.replace("T", " ").slice(0, 16) : "-";
    const move = document.createElement("td");
    move.textContent = `${transition.from} → ${transition.to}`;
    tr.appendChild(date);
    tr.appendChild(move);
    tbody.appendChild(tr);
  });
}

async function loadDetail() {
  try {
    const response = await fetch(flowUrl());
    const data = await response.json();
    if (!response.ok) {
      showError(data.error || "Issue詳細の取得に失敗しました。");
      return;
    }
    renderFlow(data);
  } catch (error) {
    showError("Issue詳細の取得に失敗しました。");
  }
}

loadDetail();
