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
    _: Date.now().toString(),
  });
  return `/api/issue-flow/${encodeURIComponent(shell.dataset.issueId)}?${params.toString()}`;
}

function renderFlow(data) {
  byId("issueTitle").textContent = `Issue #${data.issue.id} ${data.issue.subject}`;
  byId("issueMeta").textContent = `現在ステータス: ${data.issue.status || "-"} / ステータス別に作業時間を按分表示`;
  byId("detailIssueId").textContent = `#${data.issue.id}`;
  byId("detailPeriod").textContent = `${document.querySelector(".detail-shell").dataset.from} - ${document.querySelector(".detail-shell").dataset.to}`;
  byId("detailTotalHours").textContent = hours(data.issue.total_hours);
  const transitionCount = data.total_transition_count ?? 0;
  byId("detailStatusCount").previousElementSibling.textContent = "遷移回数";
  byId("detailStatusCount").textContent = `${transitionCount}回`;

  const redmineLink = byId("redmineIssueLink");
  if (data.issue.url) {
    redmineLink.href = data.issue.url;
    const issueLink = byId("detailIssueId");
    issueLink.href = data.issue.url;
    issueLink.target = "_blank";
    issueLink.rel = "noopener noreferrer";
    issueLink.onclick = (event) => {
      event.preventDefault();
      window.open(data.issue.url, "_blank", "noopener,noreferrer");
    };
  } else {
    redmineLink.classList.add("disabled");
    byId("detailIssueId").classList.add("disabled");
  }

  renderFlowDiagram(data.nodes, data.status_transitions || (data.transitions || []).filter((transition) => !transition.type || transition.type === "status"));
  renderBreakdownTable(data.nodes);
  renderTransitions(data.transitions);
}

function renderFlowDiagram(nodes, transitions) {
  const container = byId("flowDiagram");
  container.innerHTML = "";
  transitions = transitions || [];
  const statusByName = new Map(nodes.map((node) => [node.status_name, node]));
  const historyNodes = nodes;
  const transitionGroups = new Map();
  transitions.forEach((transition) => {
    const key = [transition.from, transition.to].sort().join("\u0000");
    if (!transitionGroups.has(key)) {
      transitionGroups.set(key, []);
    }
    transitionGroups.get(key).push(transition);
  });

  if (!historyNodes.length) {
    container.textContent = "ステータス遷移がありません。";
    return;
  }

  historyNodes.forEach((historyNode, index) => {
    const node = statusByName.get(historyNode.status_name) || {
      status_name: historyNode.status_name,
      hours: 0,
      share: 0,
    };
    const flowItem = document.createElement("div");
    flowItem.className = "flow-item";

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
    flowItem.appendChild(nodeEl);

    if (index < historyNodes.length - 1) {
      const arrow = document.createElement("div");
      arrow.className = "flow-arrow";
      arrow.textContent = "→";
      flowItem.appendChild(arrow);
    }

    if (index < historyNodes.length - 1) {
      const nextStatus = historyNodes[index + 1].status_name;
      const key = [node.status_name, nextStatus].sort().join("\u0000");
      const connector = document.createElement("div");
      connector.className = "flow-connector";
      (transitionGroups.get(key) || []).forEach((transition) => {
        const transitionArrow = document.createElement("span");
        transitionArrow.className = "flow-transition-arrow";
        transitionArrow.textContent = transition.from === node.status_name ? "→" : "←";
        transitionArrow.title = `${formatDateTime(transition.changed_at)} ${transition.from} → ${transition.to}`;
        connector.appendChild(transitionArrow);
      });
      if (!connector.childElementCount) {
        connector.textContent = "→";
      }
      flowItem.appendChild(connector);
    }

    container.appendChild(flowItem);
  });
}

function formatDateTime(value) {
  return value ? value.replace("T", " ").slice(0, 16) : "";
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
    const activities = node.activity_details || node.activities || [];
    if (activities.length) {
      activities.forEach((activity) => {
        const li = document.createElement("li");
        li.textContent = `${activity.activity_name}: ${hours(activity.hours)}`;
        li.textContent = "";
        li.className = "activity-row";
        const activityName = document.createElement("span");
        activityName.textContent = activity.activity_name;
        const activityHours = document.createElement("span");
        activityHours.textContent = hours(activity.hours);
        const assignee = document.createElement("span");
        assignee.textContent = activity.assignee || "未設定";
        li.append(activityName, activityHours, assignee);
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

function renderBreakdownTable(nodes) {
  const container = byId("statusBreakdown");
  container.innerHTML = "";
  nodes.forEach((node) => {
    const item = document.createElement("div");
    item.className = "status-item";
    const header = document.createElement("div");
    header.className = "status-item-header";
    const title = document.createElement("strong");
    title.textContent = node.status_name;
    const total = document.createElement("span");
    total.textContent = hours(node.hours);
    header.append(title, total);
    item.appendChild(header);

    const activities = node.activity_details || node.activities || [];
    if (activities.length) {
      const table = document.createElement("table");
      table.className = "activity-table";
      const body = document.createElement("tbody");
      activities.forEach((activity) => {
        const row = document.createElement("tr");
        const name = document.createElement("td");
        name.textContent = activity.activity_name;
        const duration = document.createElement("td");
        duration.textContent = hours(activity.hours);
        const assignee = document.createElement("td");
        assignee.textContent = activity.assignee || "未設定";
        row.append(name, duration, assignee);
        body.appendChild(row);
      });
      table.appendChild(body);
      item.appendChild(table);
    } else {
      const empty = document.createElement("p");
      empty.className = "activity-empty";
      empty.textContent = "作業時間なし";
      item.appendChild(empty);
    }
    container.appendChild(item);
  });
}

function renderTransitions(transitions) {
  const tbody = byId("transitionTable");
  const headerRow = tbody.closest("table")?.querySelector("thead tr");
  if (headerRow && headerRow.children.length < 4) {
    const numberHeader = document.createElement("th");
    numberHeader.textContent = "No";
    headerRow.insertBefore(numberHeader, headerRow.firstElementChild);
  }
  if (headerRow && headerRow.children.length < 5) {
    const progressHeader = document.createElement("th");
    progressHeader.className = "text-end";
    progressHeader.textContent = "進捗率";
    headerRow.appendChild(progressHeader);
  }
  tbody.innerHTML = "";
  if (!transitions.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.className = "empty";
    td.textContent = "ステータス変更履歴がありません";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  let transitionNumber = 0;
  transitions.forEach((transition) => {
    const tr = document.createElement("tr");
    const number = document.createElement("td");
    if (transition.type === "status" || transition.type === "assignee") {
      transitionNumber += 1;
      number.textContent = transitionNumber;
    } else {
      number.textContent = "-";
    }
    tr.appendChild(number);
    const date = document.createElement("td");
    date.textContent = transition.changed_at ? transition.changed_at.replace("T", " ").slice(0, 16) : "-";
    const move = document.createElement("td");
    move.textContent = `${transition.from} → ${transition.to}`;
    tr.appendChild(date);
    move.textContent = transition.type !== "status"
      ? `担当者: ${transition.from} → ${transition.to}`
      : `${transition.from} → ${transition.to}（担当者: ${transition.assignee || "未アサイン"}）`;
    tr.appendChild(move);
    move.textContent = transition.type === "assignee"
      ? "ー"
      : transition.to;
    const assignee = document.createElement("td");
    assignee.textContent = transition.assignee || "未アサイン";
    tr.appendChild(assignee);
    const progress = document.createElement("td");
    progress.textContent = `${Number(transition.progress_rate || 0).toFixed(1)}%`;
    progress.className = "text-end";
    tr.appendChild(progress);
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
