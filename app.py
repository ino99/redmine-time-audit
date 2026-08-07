import io
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request


load_dotenv()

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_PATH = os.path.join(BASE_DIR, "sample_data", "sample_time_entries.json")
SAMPLE_ISSUE_DETAILS_PATH = os.path.join(BASE_DIR, "sample_data", "sample_issue_details.json")
CSV_OUTPUT_DIR = os.path.join(BASE_DIR, "output", "csv")
EXCEL_OUTPUT_DIR = os.path.join(BASE_DIR, "output", "excel")
JST = timezone(timedelta(hours=9))


def parse_date(value, field_name):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} は YYYY-MM-DD 形式で指定してください。")


def parse_datetime(value):
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(JST).replace(tzinfo=None)


def redmine_config():
    redmine_url = (os.getenv("REDMINE_URL") or "").rstrip("/")
    api_key = os.getenv("REDMINE_API_KEY")
    if not redmine_url or not api_key:
        raise RuntimeError(".env に REDMINE_URL と REDMINE_API_KEY を設定してください。")
    return redmine_url, {"X-Redmine-API-Key": api_key}


def quarter_range(preset):
    today = date.today()
    year = today.year
    quarters = {
        "this_q1": (date(year, 1, 1), date(year, 3, 31)),
        "this_q2": (date(year, 4, 1), date(year, 6, 30)),
        "this_q3": (date(year, 7, 1), date(year, 9, 30)),
        "this_q4": (date(year, 10, 1), date(year, 12, 31)),
    }
    if preset in quarters:
        return quarters[preset]

    if preset == "previous_quarter":
        current_quarter = ((today.month - 1) // 3) + 1
        previous_quarter = current_quarter - 1
        previous_year = year
        if previous_quarter == 0:
            previous_quarter = 4
            previous_year -= 1
        start_month = (previous_quarter - 1) * 3 + 1
        start = date(previous_year, start_month, 1)
        next_start = date(previous_year + 1, 1, 1) if previous_quarter == 4 else date(previous_year, start_month + 3, 1)
        return start, next_start - timedelta(days=1)

    return None


def previous_three_full_months(today=None):
    today = today or date.today()
    first_day_this_month = date(today.year, today.month, 1)
    end = first_day_this_month - timedelta(days=1)
    start_month = first_day_this_month.month - 3
    start_year = first_day_this_month.year
    if start_month <= 0:
        start_month += 12
        start_year -= 1
    start = date(start_year, start_month, 1)
    return start, end


def flatten_entry(entry):
    issue = entry.get("issue") or {}
    return {
        "id": entry.get("id"),
        "spent_on": entry.get("spent_on"),
        "hours": float(entry.get("hours") or 0),
        "user_name": (entry.get("user") or {}).get("name") or "未設定",
        "project_name": (entry.get("project") or {}).get("name") or "未設定",
        "issue_id": issue.get("id"),
        "issue_subject": issue.get("subject") or "",
        "issue_fixed_version_id": (issue.get("fixed_version") or {}).get("id"),
        "issue_status_count": issue.get("status_count", 0),
        "issue_transition_count": issue.get("transition_count", 0),
        "issue_total_transition_count": issue.get("total_transition_count", 0),
        "issue_fixed_version_name": (issue.get("fixed_version") or {}).get("name") or "",
        "activity_name": (entry.get("activity") or {}).get("name") or "未設定",
        "comments": entry.get("comments") or "",
    }


def issue_url(redmine_url, issue_id):
    if not redmine_url or pd.isna(issue_id) or issue_id == "":
        return ""
    return f"{redmine_url.rstrip('/')}/issues/{issue_label(issue_id)}"


def fetch_issue_detail(issue_id, redmine_url, headers, assignee_names):
    response = requests.get(
        f"{redmine_url}/issues/{issue_id}.json",
        headers=headers,
        params={"include": "journals"},
        timeout=(5, 30),
    )
    if response.status_code >= 400:
        return None

    issue_payload = response.json().get("issue") or {}
    assignee_names = dict(assignee_names or {})
    assignee_ids = set()
    current_assignee_id = (issue_payload.get("assigned_to") or {}).get("id")
    if current_assignee_id not in (None, 0, "0", ""):
        assignee_ids.add(str(current_assignee_id))
    for journal in issue_payload.get("journals") or []:
        for detail in journal.get("details") or []:
            if detail.get("property") != "attr" or detail.get("name") != "assigned_to_id":
                continue
            for value in (detail.get("old_value"), detail.get("new_value")):
                if value not in (None, 0, "0", ""):
                    assignee_ids.add(str(value))
    for assignee_id in assignee_ids:
        if assignee_id in assignee_names:
            continue
        try:
            user_response = requests.get(
                f"{redmine_url}/users/{assignee_id}.json",
                headers=headers,
                timeout=(5, 15),
            )
            if user_response.status_code < 400:
                user = user_response.json().get("user") or {}
                user_name = user.get("name") or " ".join(
                    part for part in [user.get("firstname"), user.get("lastname")] if part
                )
                if user_name:
                    assignee_names[assignee_id] = user_name
        except (requests.RequestException, ValueError):
            continue
    history_events = remove_new_assignee_events(
        issue_history_events(issue_payload, assignee_names)
    )
    changes = status_change_details(issue_payload)
    status_ids = [
        changes[0].get("old_value") if changes else (issue_payload.get("status") or {}).get("id")
    ] + [change.get("new_value") for change in changes]
    return {
        "subject": issue_payload.get("subject") or "",
        "fixed_version": issue_payload.get("fixed_version") or {},
        "status_count": len({str(value) for value in status_ids if value is not None}) or 1,
        "transition_count": assignee_transition_count(history_events),
        "total_transition_count": transition_event_count(history_events),
        "status_metrics_by_user": status_metrics_by_user(history_events),
    }


def enrich_issue_details(entries, redmine_url, headers):
    issue_ids = sorted({
        (entry.get("issue") or {}).get("id")
        for entry in entries
        if (entry.get("issue") or {}).get("id")
    })
    details = {}
    assignee_names_by_issue = {}
    for entry in entries:
        issue_id = (entry.get("issue") or {}).get("id")
        user = entry.get("user") or {}
        if issue_id and user.get("id") is not None and user.get("name"):
            assignee_names_by_issue.setdefault(issue_id, {})[str(user["id"])] = user["name"]

    max_workers = max(1, min(int(os.getenv("REDMINE_DETAIL_WORKERS", "8")), len(issue_ids) or 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                fetch_issue_detail,
                issue_id,
                redmine_url,
                headers,
                assignee_names_by_issue.get(issue_id),
            ): issue_id
            for issue_id in issue_ids
        }
        for future in as_completed(futures):
            issue_id = futures[future]
            try:
                result = future.result()
            except (requests.RequestException, ValueError, TypeError):
                continue
            if result is not None:
                details[issue_id] = result

    for entry in entries:
        issue = entry.get("issue") or {}
        issue_id = issue.get("id")
        if issue_id in details:
            if details[issue_id].get("subject"):
                issue["subject"] = details[issue_id]["subject"]
            if details[issue_id].get("fixed_version"):
                issue["fixed_version"] = details[issue_id]["fixed_version"]
            user = entry.get("user") or {}
            user_metrics = details[issue_id].get("status_metrics_by_user") or {}
            metric = user_metric_for_entry(user_metrics, user)
            if metric is None and not user_metrics:
                metric = {
                    "status_count": details[issue_id].get("status_count", 0),
                    "transition_count": details[issue_id].get("transition_count", 0),
                    "total_transition_count": details[issue_id].get("total_transition_count", 0),
                }
            issue["status_count"] = metric.get("status_count", 0) if metric else 0
            issue["transition_count"] = metric.get("transition_count", 0) if metric else 0
            issue["total_transition_count"] = details[issue_id].get("total_transition_count", 0)
            entry["issue"] = issue

    return entries


def fetch_redmine_entries(start_date, end_date, project_id=None):
    redmine_url, headers = redmine_config()
    entries = []
    offset = 0
    limit = 100

    while True:
        params = {
            "from": start_date,
            "to": end_date,
            "limit": limit,
            "offset": offset,
        }
        if project_id:
            params["project_id"] = project_id

        response = requests.get(
            f"{redmine_url}/time_entries.json",
            headers=headers,
            params=params,
            timeout=30,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Redmine APIエラー: HTTP {response.status_code}")

        payload = response.json()
        batch = payload.get("time_entries", [])
        entries.extend(batch)

        total_count = int(payload.get("total_count", len(entries)))
        offset += limit
        if not batch or offset >= total_count:
            break

    return enrich_issue_details(entries, redmine_url, headers)


def fetch_redmine_issue_flow(issue_id, start_date, end_date):
    redmine_url, headers = redmine_config()
    issue_response = requests.get(
        f"{redmine_url}/issues/{issue_id}.json",
        headers=headers,
        params={"include": "journals"},
        timeout=30,
    )
    if issue_response.status_code >= 400:
        raise RuntimeError(f"Redmine Issue APIエラー: HTTP {issue_response.status_code}")

    statuses_response = requests.get(
        f"{redmine_url}/issue_statuses.json",
        headers=headers,
        timeout=30,
    )
    status_names = {}
    if statuses_response.status_code < 400:
        status_names = {
            str(status.get("id")): status.get("name")
            for status in statuses_response.json().get("issue_statuses", [])
        }

    issue_payload = issue_response.json().get("issue") or {}
    assignee_names = {}
    assignee_ids = set()
    current_assignee_id = (issue_payload.get("assigned_to") or {}).get("id")
    if current_assignee_id not in (None, 0, "0", ""):
        assignee_ids.add(str(current_assignee_id))
    for journal in issue_payload.get("journals") or []:
        for detail in journal.get("details") or []:
            if detail.get("property") != "attr" or detail.get("name") != "assigned_to_id":
                continue
            for value in (detail.get("old_value"), detail.get("new_value")):
                if value not in (None, 0, "0", ""):
                    assignee_ids.add(str(value))
    for assignee_id in assignee_ids:
        try:
            user_response = requests.get(
                f"{redmine_url}/users/{assignee_id}.json",
                headers=headers,
                timeout=(5, 15),
            )
            if user_response.status_code >= 400:
                continue
            user = user_response.json().get("user") or {}
            user_name = user.get("name") or " ".join(
                part for part in [user.get("firstname"), user.get("lastname")] if part
            )
            if user_name:
                assignee_names[assignee_id] = user_name
        except (requests.RequestException, ValueError):
            continue

    entries = []
    offset = 0
    limit = 100
    while True:
        params = {
            "issue_id": issue_id,
            "from": start_date,
            "to": end_date,
            "limit": limit,
            "offset": offset,
        }
        response = requests.get(
            f"{redmine_url}/time_entries.json",
            headers=headers,
            params=params,
            timeout=30,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Redmine time_entries APIエラー: HTTP {response.status_code}")

        payload = response.json()
        batch = payload.get("time_entries", [])
        entries.extend(batch)
        total_count = int(payload.get("total_count", len(entries)))
        offset += limit
        if not batch or offset >= total_count:
            break

    return build_issue_flow(issue_payload, entries, status_names, redmine_url, assignee_names)


def load_sample_entries(start_date, end_date, project_id=None):
    with open(SAMPLE_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    with open(SAMPLE_ISSUE_DETAILS_PATH, "r", encoding="utf-8") as f:
        issue_details = json.load(f)

    start = parse_date(start_date, "開始日")
    end = parse_date(end_date, "終了日")
    entries = []
    for entry in payload.get("time_entries", []):
        spent_on = parse_date(entry.get("spent_on"), "作業日")
        if spent_on < start or spent_on > end:
            continue
        if project_id and str((entry.get("project") or {}).get("id")) != str(project_id):
            continue
        issue = entry.get("issue") or {}
        detail = issue_details.get(str(issue.get("id"))) or {}
        history_events = remove_new_assignee_events(issue_history_events(detail))
        changes = status_change_details(detail)
        status_ids = [
            changes[0].get("old_value") if changes else (detail.get("status") or {}).get("id")
        ] + [change.get("new_value") for change in changes]
        issue["status_count"] = len({str(value) for value in status_ids if value is not None}) or 1
        issue["transition_count"] = assignee_transition_count(history_events)
        issue["total_transition_count"] = len(history_events)
        entry["issue"] = issue
        entries.append(entry)
    return entries


def load_sample_issue_flow(issue_id, start_date, end_date):
    with open(SAMPLE_ISSUE_DETAILS_PATH, "r", encoding="utf-8") as f:
        issue_payload = json.load(f).get(str(issue_id)) or {}
    entries = load_sample_entries(start_date, end_date)
    entries = [
        entry for entry in entries
        if str((entry.get("issue") or {}).get("id")) == str(issue_id)
    ]
    redmine_url = (os.getenv("REDMINE_URL") or "").rstrip("/")
    status_names = {
        str(status.get("id")): status.get("name")
        for status in issue_payload.get("status_names", [])
    }
    return build_issue_flow(issue_payload, entries, status_names, redmine_url)


def issue_label(value):
    if pd.isna(value) or value == "":
        return "Issueなし"
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def version_label(value):
    if value is None or pd.isna(value) or value == "":
        return "バージョン未設定"
    return str(value)


def status_name(status_id, status_names, fallback=None):
    if status_id is None:
        return fallback or "ステータス未設定"
    return status_names.get(str(status_id)) or fallback or f"ステータスID {status_id}"


def status_change_details(issue):
    changes = []
    for journal in issue.get("journals") or []:
        changed_at = parse_datetime(journal.get("created_on"))
        for detail in journal.get("details") or []:
            if detail.get("property") == "attr" and detail.get("name") == "status_id":
                changes.append({
                    "changed_at": changed_at,
                    "old_value": detail.get("old_value"),
                    "new_value": detail.get("new_value"),
                    "user_id": (journal.get("user") or {}).get("id"),
                    "user_name": (journal.get("user") or {}).get("name") or "",
                })
    return sorted(changes, key=lambda item: item.get("changed_at") or datetime.min)


def assignee_name(assignee_id, names):
    if assignee_id in (None, "", 0, "0"):
        return "未アサイン"
    return names.get(str(assignee_id)) or f"担当者ID {assignee_id}"


def issue_history_events(issue, assignee_names=None):
    names = {str(key): value for key, value in (assignee_names or {}).items()}
    current_assignee = (issue.get("assigned_to") or {}).get("id")
    if current_assignee is not None:
        current_name = (issue.get("assigned_to") or {}).get("name")
        if current_name:
            names[str(current_assignee)] = current_name

    journals = []
    for journal in issue.get("journals") or []:
        status_detail = None
        assignee_detail = None
        progress_detail = None
        for detail in journal.get("details") or []:
            if detail.get("property") != "attr":
                continue
            if detail.get("name") == "status_id":
                status_detail = detail
            elif detail.get("name") == "assigned_to_id":
                assignee_detail = detail
            elif detail.get("name") == "done_ratio":
                progress_detail = detail
        if status_detail or assignee_detail or progress_detail:
            journals.append({
                "changed_at": parse_datetime(journal.get("created_on")),
                "user_id": (journal.get("user") or {}).get("id"),
                "user_name": (journal.get("user") or {}).get("name") or "",
                "status": status_detail,
                "assignee": assignee_detail,
                "progress": progress_detail,
            })
    journals.sort(key=lambda item: item.get("changed_at") or datetime.min)

    events = []
    current_progress = (issue.get("done_ratio") or 0)
    for journal in reversed(journals):
        status_detail = journal.get("status")
        assignee_detail = journal.get("assignee")
        progress_detail = journal.get("progress")
        events.append({
            "changed_at": journal.get("changed_at"),
            "user_id": journal.get("user_id"),
            "user_name": journal.get("user_name") or "",
            "type": "status" if status_detail else ("assignee" if assignee_detail else "progress"),
            "status_old": status_detail.get("old_value") if status_detail else None,
            "status_new": status_detail.get("new_value") if status_detail else None,
            "assignee_old": assignee_detail.get("old_value") if assignee_detail else None,
            "assignee_new": assignee_detail.get("new_value") if assignee_detail else None,
            "progress_old": progress_detail.get("old_value") if progress_detail else None,
            "progress_new": progress_detail.get("new_value") if progress_detail else None,
            "progress_after": current_progress,
            "assignee_after": current_assignee,
        })
        if assignee_detail:
            current_assignee = assignee_detail.get("old_value")
        if progress_detail:
            current_progress = progress_detail.get("old_value")
    events.reverse()

    current_status = None
    for event in events:
        if event.get("type") == "status" and event.get("status_old") is not None:
            current_status = event.get("status_old")
            break
    if current_status is None:
        current_status = (issue.get("status") or {}).get("id")
    for event in events:
        event["status_before"] = current_status
        if event.get("type") == "status":
            current_status = event.get("status_new")
        event["status_after"] = current_status
        if event.get("progress_new") is not None:
            current_progress = event.get("progress_new")
        event["progress_after"] = current_progress

    for event in events:
        event["assignee_after_name"] = assignee_name(event.get("assignee_after"), names)
        event["assignee_old_name"] = assignee_name(event.get("assignee_old"), names)
        event["assignee_new_name"] = assignee_name(event.get("assignee_new"), names)
    return events


def is_new_status(status_id, status_names=None):
    if str(status_id) == "1":
        return True
    return str((status_names or {}).get(str(status_id), "")).lower() == "new"


def remove_new_assignee_events(events, status_names=None):
    return [
        event
        for event in events
        if not (
            event.get("type") == "assignee"
            and is_new_status(event.get("status_after"), status_names)
        )
    ]


def assignee_transition_count(events):
    return sum(
        1
        for event in events
        if is_assignee_change(event)
    )


def transition_event_count(events):
    return sum(1 for event in events if event.get("type") in {"status", "assignee"})


def is_assignee_change(event):
    old_value = event.get("assignee_old")
    new_value = event.get("assignee_new")
    if old_value is None and new_value is None:
        return False
    return str(old_value or "") != str(new_value or "")


def user_metric_keys(user_id=None, user_name=None):
    keys = []
    if user_id is not None:
        keys.append(f"id:{user_id}")
    if user_name:
        keys.append(f"name:{user_name}")
    return keys


def status_metrics_by_user(changes):
    metrics = {}
    for change in changes:
        keys = user_metric_keys(change.get("user_id"), change.get("user_name"))
        if not keys:
            continue
        for key in keys:
            metric = metrics.setdefault(key, {"status_ids": set(), "transition_count": 0})
            for status_id in [change.get("status_old", change.get("old_value")), change.get("status_new", change.get("new_value"))]:
                if status_id is not None:
                    metric["status_ids"].add(str(status_id))
            if is_assignee_change(change):
                metric["transition_count"] += 1
    return {
        key: {
            "status_count": len(value["status_ids"]),
            "transition_count": value["transition_count"],
        }
        for key, value in metrics.items()
    }


def user_metric_for_entry(metrics, user):
    for key in user_metric_keys(user.get("id"), user.get("name")):
        if key in metrics:
            return metrics[key]
    return None


def entry_datetime(entry):
    spent_on = parse_date(entry.get("spent_on"), "作業日")
    return datetime.combine(spent_on, datetime.min.time()).replace(hour=12)


def status_for_entry(entry_at, changes, initial_status):
    current = initial_status
    for change in changes:
        changed_at = change.get("changed_at")
        if changed_at and changed_at.replace(tzinfo=None) <= entry_at:
            current = change.get("new_value")
    return current


def build_issue_flow(issue, entries, status_names, redmine_url=None, assignee_names=None):
    changes = status_change_details(issue)
    current_status = issue.get("status") or {}
    initial_status = changes[0].get("old_value") if changes else current_status.get("id")
    ordered_status_ids = []
    for status_id in [initial_status] + [change.get("new_value") for change in changes]:
        if status_id is not None and str(status_id) not in [str(value) for value in ordered_status_ids]:
            ordered_status_ids.append(status_id)
    if not ordered_status_ids and current_status:
        ordered_status_ids.append(current_status.get("id"))

    status_hours = {
        str(status_id): {
            "status_id": str(status_id),
            "status_name": status_name(status_id, status_names, current_status.get("name") if str(status_id) == str(current_status.get("id")) else None),
            "hours": 0.0,
            "activities": {},
            "activity_details": {},
            "entries": [],
        }
        for status_id in ordered_status_ids
    }

    for entry in entries:
        assigned_status = status_for_entry(entry_datetime(entry), changes, initial_status)
        status_key = str(assigned_status)
        if status_key not in status_hours:
            status_hours[status_key] = {
                "status_id": status_key,
                "status_name": status_name(assigned_status, status_names),
                "hours": 0.0,
                "activities": {},
                "activity_details": {},
                "entries": [],
            }
            ordered_status_ids.append(assigned_status)
        hours_value = float(entry.get("hours") or 0)
        activity_name = (entry.get("activity") or {}).get("name") or "未設定"
        user_name = (entry.get("user") or {}).get("name") or "未設定"
        status_hours[status_key]["hours"] += hours_value
        activity_detail_key = (activity_name, user_name)
        status_hours[status_key]["activity_details"][activity_detail_key] = status_hours[status_key]["activity_details"].get(activity_detail_key, 0) + hours_value
        status_hours[status_key]["activities"][activity_name] = status_hours[status_key]["activities"].get(activity_name, 0) + hours_value
        status_hours[status_key]["entries"].append(flatten_entry(entry))

    nodes = []
    max_hours = max([data["hours"] for data in status_hours.values()] or [0])
    for index, status_id in enumerate(ordered_status_ids):
        data = status_hours[str(status_id)]
        nodes.append({
            "status_id": data["status_id"],
            "status_name": data["status_name"],
            "hours": round(data["hours"], 2),
            "share": round((data["hours"] / max_hours) if max_hours else 0, 3),
            "activities": [
                {"activity_name": name, "hours": round(hours, 2)}
                for name, hours in sorted(data["activities"].items(), key=lambda item: item[1], reverse=True)
            ],
            "activity_details": [
                {"activity_name": name, "hours": round(hours, 2), "assignee": assignee}
                for (name, assignee), hours in sorted(data["activity_details"].items(), key=lambda item: item[1], reverse=True)
            ],
            "entry_count": len(data["entries"]),
            "order": index,
        })

    total_work_hours = sum(node["hours"] for node in nodes)
    progress_by_status = {
        node["status_name"]: round(
            (node["hours"] / total_work_hours * 100) if total_work_hours else 0,
            1,
        )
        for node in nodes
    }

    entry_assignee_names = {
        str((entry.get("user") or {}).get("id")): (entry.get("user") or {}).get("name")
        for entry in entries
        if (entry.get("user") or {}).get("id") is not None and (entry.get("user") or {}).get("name")
    }
    assignee_names = {**(assignee_names or {}), **entry_assignee_names}
    history_events = remove_new_assignee_events(
        issue_history_events(issue, assignee_names), status_names
    )
    transition_rows = []
    initial_status_name = status_name(initial_status, status_names)
    if initial_status_name.lower() == "new":
        initial_changed_at = parse_datetime(issue.get("created_on"))
        transition_rows.append({
            "type": "initial",
            "progress_rate": 0.0,
            "from": "",
            "to": initial_status_name,
            "assignee": "未アサイン",
            "changed_at": initial_changed_at.isoformat() if initial_changed_at else "",
        })
    for event in history_events:
        changed_at = event.get("changed_at")
        if event.get("type") == "status":
            transition_rows.append({
                "type": "status",
                "progress_rate": float(event.get("progress_after") or 0),
                "from": status_name(event.get("status_old"), status_names),
                "to": status_name(event.get("status_new"), status_names),
                "assignee": event.get("assignee_after_name") or "未アサイン",
                "assignee": event.get("assignee_after_name") or "未アサイン",
                "changed_at": changed_at.isoformat() if changed_at else "",
            })
        elif event.get("type") == "assignee":
            transition_rows.append({
                "type": "assignee",
                "progress_rate": float(event.get("progress_after") or 0),
                "assignee": event.get("assignee_new_name") or "未アサイン",
                "from": event.get("assignee_old_name") or "未アサイン",
                "to": event.get("assignee_new_name") or "未アサイン",
                "changed_at": changed_at.isoformat() if changed_at else "",
            })

        else:
            transition_rows.append({
                "type": "progress",
                "from": "",
                "to": "",
                "assignee": event.get("assignee_after_name") or "未アサイン",
                "progress_rate": float(event.get("progress_after") or 0),
                "changed_at": changed_at.isoformat() if changed_at else "",
            })

    return {
        "issue": {
            "id": issue.get("id"),
            "subject": issue.get("subject") or "",
            "url": issue_url(redmine_url, issue.get("id")),
            "status": current_status.get("name") or "",
            "total_hours": round(sum(float(entry.get("hours") or 0) for entry in entries), 2),
        },
        "nodes": nodes,
        "transitions": transition_rows,
        "status_transitions": [row for row in transition_rows if row["type"] == "status"],
        "total_transition_count": transition_event_count(history_events),
        "assignee_transition_count": assignee_transition_count(history_events),
        "time_entries": records(pd.DataFrame([flatten_entry(entry) for entry in entries])),
    }


def build_analysis(entries, redmine_url=None):
    rows = [flatten_entry(entry) for entry in entries]
    return build_analysis_from_rows(rows, redmine_url)


def build_analysis_from_rows(rows, redmine_url=None):
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=[
            "id", "spent_on", "hours", "user_name", "project_name",
            "issue_id", "issue_subject", "issue_fixed_version_id",
            "issue_fixed_version_name", "issue_status_count",
            "issue_transition_count", "issue_total_transition_count", "activity_name", "comments",
        ])
    for column in [
        "id", "spent_on", "hours", "user_name", "project_name",
        "issue_id", "issue_subject", "issue_fixed_version_id",
        "issue_fixed_version_name", "issue_status_count",
        "issue_transition_count", "issue_total_transition_count", "activity_name", "comments",
    ]:
        if column not in df.columns:
            df[column] = None
    df["hours"] = df["hours"].apply(lambda value: float(value or 0))
    df["issue_url"] = df["issue_id"].apply(lambda value: issue_url(redmine_url, value))
    df["issue_fixed_version_name"] = df["issue_fixed_version_name"].apply(lambda value: value or "")

    total_hours = float(df["hours"].sum()) if not df.empty else 0.0
    issue_df = df[df["issue_id"].notna()] if not df.empty else df
    issue_hours = issue_df.groupby("issue_id", dropna=True)["hours"].sum().reset_index() if not issue_df.empty else pd.DataFrame(columns=["issue_id", "hours"])
    max_issue = None
    if not issue_hours.empty:
        max_row = issue_hours.sort_values("hours", ascending=False).iloc[0]
        max_issue = {"issue_id": issue_label(max_row["issue_id"]), "hours": round(float(max_row["hours"]), 2)}

    user_ranking_df = (
        df.groupby("user_name", dropna=False)["hours"].sum().reset_index()
        .sort_values("hours", ascending=False)
        .head(10)
    ) if not df.empty else pd.DataFrame(columns=["user_name", "hours"])

    activity_df = (
        df.groupby("activity_name", dropna=False)["hours"].sum().reset_index()
        .sort_values("hours", ascending=False)
    ) if not df.empty else pd.DataFrame(columns=["activity_name", "hours"])

    project_df = (
        df.groupby("project_name", dropna=False)["hours"].sum().reset_index()
        .sort_values("hours", ascending=False)
    ) if not df.empty else pd.DataFrame(columns=["project_name", "hours"])

    version_activity_df = (
        df.assign(version_name=df["issue_fixed_version_name"].apply(version_label))
        .groupby(["version_name", "activity_name"], dropna=False)["hours"]
        .sum()
        .reset_index()
        .sort_values(["version_name", "hours"], ascending=[True, False])
    ) if not df.empty else pd.DataFrame(columns=["version_name", "activity_name", "hours"])

    user_issue_df = pd.DataFrame(columns=[
        "user_name", "issue_id", "issue_subject", "issue_fixed_version_name",
        "issue_url", "hours", "activity_breakdown",
    ])
    if not df.empty:
        grouped = (
            df.assign(
                issue_key=df["issue_id"].apply(issue_label),
                issue_title=df.apply(
                    lambda row: "Issueなし" if pd.isna(row["issue_id"]) else (row["issue_subject"] or "題名未取得"),
                    axis=1,
                ),
                version_name=df["issue_fixed_version_name"].apply(version_label),
            )
            .groupby(["user_name", "issue_key", "issue_title", "version_name", "issue_url", "issue_status_count", "issue_transition_count", "issue_total_transition_count", "activity_name"], dropna=False)["hours"]
            .sum()
            .reset_index()
        )
        totals = (
            grouped.groupby(["user_name", "issue_key", "issue_title", "version_name", "issue_url", "issue_status_count", "issue_transition_count", "issue_total_transition_count"], dropna=False)["hours"]
            .sum()
            .reset_index()
            .sort_values(["user_name", "hours"], ascending=[True, False])
        )
        breakdown_rows = []
        for keys, group in grouped.groupby(["user_name", "issue_key", "issue_title", "version_name", "issue_url", "issue_status_count", "issue_transition_count", "issue_total_transition_count"], dropna=False):
            user_name, issue_key, issue_title, version_name, url, status_count, transition_count, total_transition_count = keys
            breakdown_rows.append({
                "user_name": user_name,
                "issue_key": issue_key,
                "issue_title": issue_title,
                "version_name": version_name,
                "issue_url": url,
                "issue_status_count": status_count,
                "issue_transition_count": transition_count,
                "issue_total_transition_count": total_transition_count,
                "activity_breakdown": ", ".join(
                    f"{row.activity_name}: {row.hours:.2f}h" for row in group.itertuples()
                ),
            })
        breakdowns = pd.DataFrame(breakdown_rows)
        user_issue_df = totals.merge(breakdowns, on=["user_name", "issue_key", "issue_title", "version_name", "issue_url"], how="left")
        for count_field in ["issue_status_count", "issue_transition_count", "issue_total_transition_count"]:
            left_field = f"{count_field}_x"
            right_field = f"{count_field}_y"
            if left_field in user_issue_df.columns:
                user_issue_df[count_field] = user_issue_df[left_field].fillna(user_issue_df.get(right_field, 0))
                user_issue_df = user_issue_df.drop(columns=[field for field in [left_field, right_field] if field in user_issue_df.columns])
        user_issue_df = user_issue_df.groupby("user_name", group_keys=False).head(10)
        user_issue_df = user_issue_df.rename(columns={
            "issue_key": "issue_id",
            "issue_title": "issue_subject",
            "version_name": "issue_fixed_version_name",
        })

    alerts = build_alerts(df, total_hours, redmine_url)
    version_options = sorted(
        {version_label(value) for value in df["issue_fixed_version_name"].tolist()},
        key=lambda value: (value == "バージョン未設定", value),
    ) if not df.empty else []

    return {
        "summary": {
            "total_hours": round(total_hours, 2),
            "user_count": int(df["user_name"].nunique()) if not df.empty else 0,
            "issue_count": int(issue_df["issue_id"].nunique()) if not issue_df.empty else 0,
            "entry_count": int(len(df)),
            "avg_hours_per_issue": round(total_hours / issue_df["issue_id"].nunique(), 2) if not issue_df.empty and issue_df["issue_id"].nunique() else 0,
            "max_issue": max_issue,
        },
        "user_ranking": records(user_ranking_df),
        "activity_summary": records(activity_df),
        "project_summary": records(project_df),
        "version_activity_summary": records(version_activity_df),
        "user_issue_top10": records(user_issue_df),
        "users": sorted(df["user_name"].dropna().unique().tolist()) if not df.empty else [],
        "versions": version_options,
        "alerts": alerts,
        "raw_time_entries": records(df),
        "redmine_url": redmine_url or "",
    }


def build_alerts(df, total_hours, redmine_url=None):
    if df.empty or total_hours <= 0:
        return []

    alerts = []
    user_totals = df.groupby("user_name")["hours"].sum()
    for user_name, hours in user_totals.items():
        ratio = hours / total_hours
        if ratio >= 0.30:
            alerts.append({
                "type": "作業集中",
                "message": f"{user_name} さんに全体の {ratio:.1%} の作業時間が集中しています。",
            })

    issue_totals = df[df["issue_id"].notna()].groupby("issue_id")["hours"].sum()
    for issue_id, hours in issue_totals[issue_totals >= 30].sort_values(ascending=False).items():
        issue_id_text = issue_label(issue_id)
        alerts.append({
            "type": "重いIssue",
            "message": f"Issue #{issue_id_text} に {hours:.2f}h かかっています。",
            "issue_id": issue_id_text,
            "issue_url": issue_url(redmine_url, issue_id),
        })

    activity_totals = df.groupby("activity_name")["hours"].sum()
    research_hours = sum(
        hours for name, hours in activity_totals.items()
        if any(keyword in str(name).lower() for keyword in ["調査", "問い合わせ", "問合", "inquiry", "research", "support"])
    )
    if research_hours / total_hours >= 0.25:
        alerts.append({
            "type": "調査・問い合わせ過多",
            "message": f"調査・問い合わせ系が全体の {research_hours / total_hours:.1%} を占めています。",
        })

    review_hours = sum(
        hours for name, hours in activity_totals.items()
        if any(keyword in str(name).lower() for keyword in ["レビュー", "review"])
    )
    if review_hours / total_hours < 0.05:
        alerts.append({
            "type": "レビュー不足の可能性",
            "message": f"レビュー作業が全体の {review_hours / total_hours:.1%} です。",
        })

    no_issue_count = int(df["issue_id"].isna().sum())
    if no_issue_count > 0 and no_issue_count / len(df) >= 0.20:
        alerts.append({
            "type": "Issue紐づけ不足",
            "message": f"Issue番号がない作業記録が {no_issue_count} 件あります。",
        })

    return alerts


def records(df):
    clean = df.copy().astype(object)
    clean = clean.where(pd.notna(clean), None)
    for column in clean.columns:
        if column == "hours":
            clean[column] = clean[column].apply(lambda value: round(float(value), 2) if value is not None else 0)
    return clean.to_dict(orient="records")


def dataframe_from_records(rows, columns=None):
    df = pd.DataFrame(rows or [])
    if columns:
        for column in columns:
            if column not in df.columns:
                df[column] = None
        df = df[columns]
    return df


def build_excel_workbook(data):
    output = io.BytesIO()
    summary = data.get("summary") or {}
    max_issue = summary.get("max_issue") or {}
    criteria = data.get("criteria") or {}

    summary_rows = [
        {"項目": "開始日", "値": criteria.get("from", "")},
        {"項目": "終了日", "値": criteria.get("to", "")},
        {"項目": "プロジェクトID", "値": criteria.get("project_id", "")},
        {"項目": "対象バージョン", "値": ", ".join(criteria.get("versions") or [])},
        {"項目": "データソース", "値": data.get("source", "")},
        {"項目": "総作業時間", "値": summary.get("total_hours", 0)},
        {"項目": "対象ユーザー数", "値": summary.get("user_count", 0)},
        {"項目": "対象Issue数", "値": summary.get("issue_count", 0)},
        {"項目": "作業記録数", "値": summary.get("entry_count", 0)},
        {"項目": "平均時間 / Issue", "値": summary.get("avg_hours_per_issue", 0)},
        {"項目": "最大時間Issue", "値": f"#{max_issue.get('issue_id')} / {max_issue.get('hours')}h" if max_issue else ""},
    ]

    sheets = {
        "サマリー": pd.DataFrame(summary_rows),
        "棚卸アラート": dataframe_from_records(data.get("alerts"), ["type", "message", "issue_id", "issue_url"]),
        "ユーザーランキング": dataframe_from_records(data.get("user_ranking"), ["user_name", "hours"]),
        "ユーザーIssueTop10": dataframe_from_records(
            data.get("user_issue_top10"),
            [
                "user_name", "issue_id", "issue_subject", "issue_fixed_version_name",
                "issue_url", "hours", "activity_breakdown",
                "issue_total_transition_count", "issue_transition_count",
            ],
        ),
        "作業分類別": dataframe_from_records(data.get("activity_summary"), ["activity_name", "hours"]),
        "プロジェクト別": dataframe_from_records(data.get("project_summary"), ["project_name", "hours"]),
        "Raw": dataframe_from_records(
            data.get("raw_time_entries"),
            [
                "id", "spent_on", "hours", "user_name", "project_name",
                "issue_id", "issue_subject", "issue_fixed_version_id",
                "issue_fixed_version_name", "issue_url", "activity_name", "comments",
            ],
        ),
    }

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            worksheet = writer.sheets[sheet_name]
            worksheet.freeze_panes = "A2"
            for column_cells in worksheet.columns:
                max_length = max(len(str(cell.value or "")) for cell in column_cells)
                worksheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 12), 60)

            if "issue_url" in df.columns and "issue_id" in df.columns:
                issue_url_col = list(df.columns).index("issue_url") + 1
                issue_id_col = list(df.columns).index("issue_id") + 1
                for row_index, row in enumerate(df.itertuples(index=False), start=2):
                    url = getattr(row, "issue_url", None)
                    issue_id = getattr(row, "issue_id", None)
                    if isinstance(url, str) and url and issue_id and issue_id != "Issueなし":
                        cell = worksheet.cell(row=row_index, column=issue_id_col)
                        cell.value = f"#{issue_id}"
                        cell.hyperlink = url
                        cell.style = "Hyperlink"
                worksheet.column_dimensions[worksheet.cell(row=1, column=issue_url_col).column_letter].hidden = True

    output.seek(0)
    return output.getvalue()


@app.route("/")
def index():
    default_start, default_end = previous_three_full_months()
    return render_template(
        "index.html",
        default_start=default_start.isoformat(),
        default_end=default_end.isoformat(),
        default_project_id=os.getenv("DEFAULT_PROJECT_ID", ""),
    )


@app.route("/issue-detail/<issue_id>")
def issue_detail(issue_id):
    return render_template(
        "issue_detail.html",
        issue_id=issue_id,
        start_date=request.args.get("from", ""),
        end_date=request.args.get("to", ""),
        sample_mode=request.args.get("sample_mode", "false"),
        redmine_url=(os.getenv("REDMINE_URL") or "").rstrip("/"),
    )


@app.route("/api/preset-range")
def preset_range():
    preset = request.args.get("preset")
    result = quarter_range(preset)
    if not result:
        return jsonify({"error": "未対応の四半期プリセットです。"}), 400
    start, end = result
    return jsonify({"from": start.isoformat(), "to": end.isoformat()})


@app.route("/api/issue-flow/<issue_id>")
def issue_flow(issue_id):
    try:
        start = parse_date(request.args.get("from"), "開始日")
        end = parse_date(request.args.get("to"), "終了日")
        if start > end:
            return jsonify({"error": "開始日は終了日以前にしてください。"}), 400

        if request.args.get("sample_mode") == "true":
            flow = load_sample_issue_flow(issue_id, start.isoformat(), end.isoformat())
        else:
            flow = fetch_redmine_issue_flow(issue_id, start.isoformat(), end.isoformat())
        response = jsonify(flow)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response
    except requests.RequestException:
        return jsonify({"error": "Redmineに接続できませんでした。"}), 502
    except (RuntimeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/analyze", methods=["POST"])
def analyze():
    payload = request.get_json(silent=True) or {}
    try:
        start = parse_date(payload.get("from"), "開始日")
        end = parse_date(payload.get("to"), "終了日")
        if start > end:
            return jsonify({"error": "開始日は終了日以前にしてください。"}), 400

        project_id = (payload.get("project_id") or "").strip() or None
        sample_mode = bool(payload.get("sample_mode"))
        if sample_mode:
            entries = load_sample_entries(start.isoformat(), end.isoformat(), project_id)
            source = "sample"
            redmine_url = (os.getenv("REDMINE_URL") or "").rstrip("/")
        else:
            entries = fetch_redmine_entries(start.isoformat(), end.isoformat(), project_id)
            source = "redmine"
            redmine_url = (os.getenv("REDMINE_URL") or "").rstrip("/")

        analysis = build_analysis(entries, redmine_url)
        analysis["source"] = source
        analysis["criteria"] = {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "project_id": project_id or "",
            "sample_mode": sample_mode,
        }
        return jsonify(analysis)
    except requests.RequestException:
        return jsonify({"error": "Redmineに接続できませんでした。サンプルモードを利用するか、URLとネットワークを確認してください。"}), 502
    except (RuntimeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/filter-analysis", methods=["POST"])
def filter_analysis():
    payload = request.get_json(silent=True) or {}
    rows = payload.get("raw_time_entries") or []
    selected_versions = payload.get("versions") or []
    redmine_url = payload.get("redmine_url") or ""

    if selected_versions:
        rows = [
            row for row in rows
            if version_label(row.get("issue_fixed_version_name")) in selected_versions
        ]

    analysis = build_analysis_from_rows(rows, redmine_url)
    analysis["source"] = payload.get("source") or ""
    analysis["criteria"] = payload.get("criteria") or {}
    analysis["criteria"]["versions"] = selected_versions
    return jsonify(analysis)


@app.route("/api/export/<export_name>", methods=["POST"])
def export_csv(export_name):
    payload = request.get_json(silent=True) or {}
    data = payload.get("data") or {}
    export_map = {
        "raw_time_entries": data.get("raw_time_entries", []),
        "user_ranking": data.get("user_ranking", []),
        "user_issue_top10": data.get("user_issue_top10", []),
        "activity_summary": data.get("activity_summary", []),
        "project_summary": data.get("project_summary", []),
        "version_activity_summary": data.get("version_activity_summary", []),
    }
    if export_name not in export_map:
        return jsonify({"error": "未対応のCSV種別です。"}), 404

    df = pd.DataFrame(export_map[export_name])
    csv_text = df.to_csv(index=False)
    csv_bytes = csv_text.encode("utf-8-sig")
    filename = f"{export_name}.csv"
    os.makedirs(CSV_OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(CSV_OUTPUT_DIR, filename), "wb") as f:
        f.write(csv_bytes)
    return Response(
        csv_bytes,
        mimetype="text/csv",
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/api/export-excel", methods=["POST"])
def export_excel():
    payload = request.get_json(silent=True) or {}
    data = payload.get("data") or {}
    if not data:
        return jsonify({"error": "分析結果がありません。先に分析を実行してください。"}), 400

    try:
        workbook = build_excel_workbook(data)
    except ImportError:
        return jsonify({"error": "Excel出力には openpyxl が必要です。pip install -r requirements.txt を実行してください。"}), 500

    filename = "redmine_time_audit_report.xlsx"
    os.makedirs(EXCEL_OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(EXCEL_OUTPUT_DIR, filename), "wb") as f:
        f.write(workbook)

    return Response(
        workbook,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    app.run(debug=True)
