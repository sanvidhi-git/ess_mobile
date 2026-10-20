# Copyright (c) 2026, Sanvidhi Tech Pvt. Ltd. and contributors

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate


def execute(filters=None):
    f = frappe._dict(filters or {})
    f.from_date = getdate(f.from_date or frappe.utils.get_first_day(frappe.utils.nowdate()))
    f.to_date = getdate(f.to_date or frappe.utils.nowdate())
    rate = flt(frappe.db.get_single_value("ESS Settings", "rate_per_km"))

    emp_filters = {k: f[k] for k in ("company", "branch", "department") if f.get(k)}
    if f.employee:
        emp_filters["name"] = f.employee
    employees = {e.name: e for e in frappe.get_all("Employee", filters=emp_filters,
                                                  fields=["name", "employee_name", "branch", "department"])}
    if not employees:
        return [], []

    trips = frappe.get_all(
        "ESS Trip",
        filters={"employee": ["in", list(employees)], "trip_date": ["between", [f.from_date, f.to_date]]},
        fields=["name", "employee", "trip_date", "status", "start_time", "end_time", "distance_km",
                "accepted_pings", "total_pings", "expense_claim", "claimed_km", "transport_mode", "odometer_km",
                "personal_km"],
        order_by="trip_date desc, start_time desc",
    )
    claims = {}
    names = [t.expense_claim for t in trips if t.expense_claim]
    if names:
        claims = {c.name: c for c in frappe.get_all(
            "Expense Claim", filters={"name": ["in", names]},
            fields=["name", "total_claimed_amount", "total_sanctioned_amount", "approval_status", "status",
                    "docstatus"])}

    if f.get("group_by") == "Trip":
        return _trip_columns(), _trip_rows(trips, employees, claims), None, _chart(trips, employees), \
            _summary(trips, claims, rate)

    by_emp: dict[str, dict] = {}
    for t in trips:
        e = employees[t.employee]
        r = by_emp.setdefault(t.employee, {
            "employee": t.employee, "employee_name": e.employee_name, "branch": e.branch,
            "trips": 0, "km": 0.0, "claimed_km": 0.0, "unclaimed_km": 0.0, "claimed_amount": 0.0,
            "unclaimed_value": 0.0,
        })
        r["trips"] += 1
        r["km"] += flt(t.distance_km)
        c = claims.get(t.expense_claim)
        if c and c.docstatus != 2:
            r["claimed_km"] += flt(t.claimed_km)
            r["claimed_amount"] += flt(c.total_claimed_amount)
        elif t.status != "Active":
            r["unclaimed_km"] += flt(t.distance_km)
    for r in by_emp.values():
        r["unclaimed_value"] = flt(r["unclaimed_km"] * rate, 2)
        for k in ("km", "claimed_km", "unclaimed_km"):
            r[k] = flt(r[k], 2)
    rows = sorted(by_emp.values(), key=lambda r: r["km"], reverse=True)
    return _emp_columns(), rows, None, _chart(trips, employees), _summary(trips, claims, rate)


def _trip_rows(trips, employees, claims):
    out = []
    for t in trips:
        c = claims.get(t.expense_claim)
        out.append({
            "trip": t.name, "trip_date": t.trip_date, "employee": t.employee,
            "employee_name": employees[t.employee].employee_name, "status": t.status,
            "start_time": t.start_time, "end_time": t.end_time, "km": flt(t.distance_km, 2),
            "odometer_km": flt(t.odometer_km, 1) or None, "personal_km": flt(t.personal_km, 2) or None,
            "transport_mode": t.transport_mode,
            "pings": f"{cint(t.accepted_pings)} / {cint(t.total_pings)}", "expense_claim": t.expense_claim,
            "claimed_km": flt(t.claimed_km, 2), "claimed_amount": flt(c.total_claimed_amount) if c else 0,
            "claim_status": (c.approval_status if c.docstatus != 2 else "Cancelled") if c else "",
        })
    return out


def _chart(trips, employees):
    totals: dict[str, float] = {}
    for t in trips:
        name = employees[t.employee].employee_name or t.employee
        totals[name] = totals.get(name, 0) + flt(t.distance_km)
    top = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:12]
    if not top:
        return None
    return {
        "data": {"labels": [name for name, _km in top], "datasets": [{"name": _("km"), "values": [flt(km, 1) for _name, km in top]}]},
        "type": "bar",
        "colors": ["#7575FF"],
    }


def _summary(trips, claims, rate):
    km = sum(flt(t.distance_km) for t in trips)
    claimed = sum(flt(c.total_claimed_amount) for c in claims.values() if c.docstatus != 2)
    unclaimed_km = sum(flt(t.distance_km) for t in trips
                       if t.status != "Active" and not (t.expense_claim and claims.get(t.expense_claim)
                                                        and claims[t.expense_claim].docstatus != 2))
    return [
        {"label": _("Trips"), "value": len(trips), "indicator": "Blue"},
        {"label": _("Total km"), "value": flt(km, 1), "indicator": "Blue", "datatype": "Float"},
        {"label": _("Claimed"), "value": claimed, "indicator": "Green", "datatype": "Currency"},
        {"label": _("Unclaimed km"), "value": flt(unclaimed_km, 1), "indicator": "Orange", "datatype": "Float"},
        {"label": _("Unclaimed Value"), "value": flt(unclaimed_km * rate, 2), "indicator": "Orange",
         "datatype": "Currency"},
    ]


def _emp_columns():
    return [
        {"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 130},
        {"fieldname": "employee_name", "label": _("Name"), "fieldtype": "Data", "width": 180},
        {"fieldname": "branch", "label": _("Branch"), "fieldtype": "Link", "options": "Branch", "width": 120},
        {"fieldname": "trips", "label": _("Trips"), "fieldtype": "Int", "width": 80},
        {"fieldname": "km", "label": _("Total km"), "fieldtype": "Float", "precision": 2, "width": 110},
        {"fieldname": "claimed_km", "label": _("Claimed km"), "fieldtype": "Float", "precision": 2, "width": 110},
        {"fieldname": "claimed_amount", "label": _("Claimed Amount"), "fieldtype": "Currency", "width": 140},
        {"fieldname": "unclaimed_km", "label": _("Unclaimed km"), "fieldtype": "Float", "precision": 2,
         "width": 120},
        {"fieldname": "unclaimed_value", "label": _("Unclaimed Value"), "fieldtype": "Currency", "width": 140},
    ]


def _trip_columns():
    return [
        {"fieldname": "trip", "label": _("Trip"), "fieldtype": "Link", "options": "ESS Trip", "width": 140},
        {"fieldname": "trip_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
        {"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 120},
        {"fieldname": "employee_name", "label": _("Name"), "fieldtype": "Data", "width": 160},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
        {"fieldname": "start_time", "label": _("Start"), "fieldtype": "Datetime", "width": 150},
        {"fieldname": "end_time", "label": _("End"), "fieldtype": "Datetime", "width": 150},
        {"fieldname": "km", "label": _("km"), "fieldtype": "Float", "precision": 2, "width": 90},
        {"fieldname": "odometer_km", "label": _("Odometer km"), "fieldtype": "Float", "precision": 1, "width": 110},
        {"fieldname": "personal_km", "label": _("Personal km"), "fieldtype": "Float", "precision": 2, "width": 100},
        {"fieldname": "transport_mode", "label": _("Mode"), "fieldtype": "Data", "width": 110},
        {"fieldname": "pings", "label": _("Pings Used / Received"), "fieldtype": "Data", "width": 150},
        {"fieldname": "expense_claim", "label": _("Expense Claim"), "fieldtype": "Link", "options": "Expense Claim",
         "width": 150},
        {"fieldname": "claimed_km", "label": _("Claimed km"), "fieldtype": "Float", "precision": 2, "width": 100},
        {"fieldname": "claimed_amount", "label": _("Claimed Amount"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "claim_status", "label": _("Claim Status"), "fieldtype": "Data", "width": 110},
    ]
