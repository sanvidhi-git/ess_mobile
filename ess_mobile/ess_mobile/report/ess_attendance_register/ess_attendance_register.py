# Copyright (c) 2026, Sanvidhi Tech Pvt. Ltd. and contributors

import frappe
from frappe import _
from frappe.utils import cint, escape_html, flt, getdate


def execute(filters=None):
    f = frappe._dict(filters or {})
    f.from_date = getdate(f.from_date or frappe.utils.nowdate())
    f.to_date = getdate(f.to_date or f.from_date)
    employees = _employees(f)
    if not employees:
        return _columns(), [], None, None, []

    max_acc = flt(frappe.db.get_single_value("ESS Settings", "max_accuracy_m")) or 100
    rows = _accepted(f, employees) + (_rejected(f, employees) if cint(f.include_rejected) else [])
    for r in rows:
        r["exception"] = cint(
            r["status"] == "Rejected"
            or (r.get("geofence") and not r.get("inside"))
            or r.get("mocked")
            or (r.get("accuracy") or 0) > max_acc
            or (r["status"] == "Accepted" and r.get("selfie_url") and not r.get("liveness"))
        )
    if cint(f.exceptions_only):
        rows = [r for r in rows if r["exception"]]
    rows.sort(key=lambda r: r["time"], reverse=True)

    summary = [
        {"label": _("Punches"), "value": sum(1 for r in rows if r["status"] == "Accepted"), "indicator": "Blue"},
        {"label": _("Employees"), "value": len({r["employee"] for r in rows}), "indicator": "Blue"},
        {"label": _("Outside Geofence"),
         "value": sum(1 for r in rows if r["status"] == "Accepted" and r.get("geofence") and not r.get("inside")),
         "indicator": "Orange"},
        {"label": _("Rejected Attempts"), "value": sum(1 for r in rows if r["status"] == "Rejected"),
         "indicator": "Red"},
    ]
    return _columns(), rows, None, None, summary


def _employees(f) -> dict:
    flt_ = {}
    for k in ("company", "branch", "department"):
        if f.get(k):
            flt_[k] = f.get(k)
    if f.employee:
        flt_["name"] = f.employee
    return {e.name: e for e in frappe.get_all("Employee", filters=flt_, fields=["name", "employee_name", "branch"])}


def _accepted(f, employees) -> list[dict]:
    filters = {
        "employee": ["in", list(employees)],
        "time": ["between", [f"{f.from_date} 00:00:00", f"{f.to_date} 23:59:59"]],
    }
    if cint(f.get("mobile_only", 1)):
        filters["ess_device"] = ["is", "set"]
    if f.log_type:
        filters["log_type"] = f.log_type
    out = []
    for c in frappe.get_all(
        "Employee Checkin",
        filters=filters,
        fields=["name", "employee", "log_type", "time", "ess_selfie", "ess_geofence", "ess_within_geofence",
                "ess_distance_m", "ess_accuracy", "ess_is_mocked", "ess_liveness_passed", "ess_latitude",
                "ess_longitude", "ess_trip"],
    ):
        e = employees[c.employee]
        out.append({
            "status": "Accepted", "reason": "", "time": c.time, "employee": c.employee,
            "employee_name": e.employee_name, "branch": e.branch, "log_type": c.log_type,
            "selfie_url": c.ess_selfie, "selfie": _img(c.ess_selfie), "geofence": c.ess_geofence,
            "inside": cint(c.ess_within_geofence), "distance_m": c.ess_distance_m, "accuracy": c.ess_accuracy,
            "mocked": cint(c.ess_is_mocked), "liveness": cint(c.ess_liveness_passed),
            "map": _map(c.ess_latitude, c.ess_longitude), "trip": c.ess_trip,
            "document_type": "Employee Checkin", "document": c.name,
        })
    return out


def _rejected(f, employees) -> list[dict]:
    filters = {
        "employee": ["in", list(employees)],
        "attempt_time": ["between", [f"{f.from_date} 00:00:00", f"{f.to_date} 23:59:59"]],
    }
    if f.log_type:
        filters["log_type"] = f.log_type
    out = []
    for a in frappe.get_all(
        "ESS Checkin Attempt",
        filters=filters,
        fields=["name", "employee", "log_type", "attempt_time", "reason", "geofence", "distance_m", "accuracy",
                "is_mocked", "latitude", "longitude"],
    ):
        e = employees[a.employee]
        out.append({
            "status": "Rejected", "reason": a.reason, "time": a.attempt_time, "employee": a.employee,
            "employee_name": e.employee_name, "branch": e.branch, "log_type": a.log_type, "selfie": "",
            "geofence": a.geofence, "inside": 0, "distance_m": a.distance_m, "accuracy": a.accuracy,
            "mocked": cint(a.is_mocked), "liveness": 0, "map": _map(a.latitude, a.longitude), "trip": None,
            "document_type": "ESS Checkin Attempt", "document": a.name,
        })
    return out


def _img(url):
    if not url:
        return ""
    u = escape_html(url)
    return (f'<a href="{u}" target="_blank"><img src="{u}" '
            f'style="width:36px;height:36px;object-fit:cover;border-radius:6px"></a>')


def _map(lat, lng):
    if not (lat or lng):
        return ""
    return (f'<a href="https://www.google.com/maps?q={flt(lat, 7)},{flt(lng, 7)}" target="_blank">'
            f'{_("Map")}</a>')


def _columns():
    return [
        {"fieldname": "time", "label": _("Time"), "fieldtype": "Datetime", "width": 160},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 90},
        {"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 120},
        {"fieldname": "employee_name", "label": _("Name"), "fieldtype": "Data", "width": 160},
        {"fieldname": "branch", "label": _("Branch"), "fieldtype": "Link", "options": "Branch", "width": 110},
        {"fieldname": "log_type", "label": _("Type"), "fieldtype": "Data", "width": 60},
        {"fieldname": "selfie", "label": _("Selfie"), "fieldtype": "HTML", "width": 70},
        {"fieldname": "reason", "label": _("Rejected For"), "fieldtype": "Data", "width": 130},
        {"fieldname": "geofence", "label": _("Geofence"), "fieldtype": "Link", "options": "ESS Geofence", "width": 120},
        {"fieldname": "inside", "label": _("Inside"), "fieldtype": "Check", "width": 70},
        {"fieldname": "distance_m", "label": _("Dist. (m)"), "fieldtype": "Float", "precision": 0, "width": 80},
        {"fieldname": "accuracy", "label": _("GPS ± (m)"), "fieldtype": "Float", "precision": 0, "width": 80},
        {"fieldname": "mocked", "label": _("Mock GPS"), "fieldtype": "Check", "width": 80},
        {"fieldname": "liveness", "label": _("Liveness"), "fieldtype": "Check", "width": 80},
        {"fieldname": "map", "label": _("Location"), "fieldtype": "HTML", "width": 70},
        {"fieldname": "trip", "label": _("Trip"), "fieldtype": "Link", "options": "ESS Trip", "width": 120},
        {"fieldname": "document_type", "label": _("Document Type"), "fieldtype": "Data", "hidden": 1},
        {"fieldname": "document", "label": _("Record"), "fieldtype": "Dynamic Link", "options": "document_type",
         "width": 150},
        {"fieldname": "exception", "label": _("Exception"), "fieldtype": "Check", "hidden": 1},
    ]
