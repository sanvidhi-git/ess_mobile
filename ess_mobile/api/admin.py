"""Desk-side (HR) endpoints: app permission, live map data, trip and device actions."""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

HR_ROLES = {"HR Manager", "HR User", "System Manager"}


def check_app_permission() -> bool:
    """Shows the ESS Mobile tile on the apps screen / desktop only to HR and admins."""
    if frappe.session.user == "Administrator":
        return True
    return bool(HR_ROLES & set(frappe.get_roles()))


def _require_hr():
    if not check_app_permission():
        frappe.throw(_("Only HR users can do this."), frappe.PermissionError)


# ---------------------------------------------------------------- live map
@frappe.whitelist()
def live_map_data(date: str | None = None, company: str | None = None, branch: str | None = None):
    _require_hr()
    day = getdate(date or nowdate())
    emp_filters = {"status": "Active"}
    if company:
        emp_filters["company"] = company
    if branch:
        emp_filters["branch"] = branch
    employees = {
        e.name: e
        for e in frappe.get_all("Employee", filters=emp_filters,
                                fields=["name", "employee_name", "branch", "designation", "image"])
    }
    if not employees:
        return {"date": str(day), "employees": [], "geofences": []}

    punches = frappe.get_all(
        "Employee Checkin",
        filters={"employee": ["in", list(employees)], "time": ["between", [f"{day} 00:00:00", f"{day} 23:59:59"]]},
        fields=["name", "employee", "log_type", "time", "ess_latitude", "ess_longitude", "ess_accuracy",
                "ess_within_geofence", "ess_geofence", "ess_selfie", "ess_trip"],
        order_by="time asc",
    )
    trips = frappe.get_all(
        "ESS Trip",
        filters={"employee": ["in", list(employees)], "trip_date": day},
        fields=["name", "employee", "status", "start_time", "end_time", "distance_km", "route", "expense_claim"],
        order_by="start_time asc",
    )
    last_ping = {}
    active = [t.name for t in trips if t.status == "Active"]
    if active:
        rows = frappe.db.sql(
            """
            select p.trip, p.ping_time, p.latitude, p.longitude, p.accuracy, p.battery
            from `tabESS Location Ping` p
            join (select trip, max(ping_time) mt from `tabESS Location Ping`
                  where trip in %(trips)s group by trip) m
              on m.trip = p.trip and m.mt = p.ping_time
            """,
            {"trips": tuple(active)},
            as_dict=True,
        )
        last_ping = {r.trip: r for r in rows}

    out: dict[str, dict] = {}

    def row(emp_id):
        e = employees[emp_id]
        return out.setdefault(emp_id, {
            "employee": emp_id, "employee_name": e.employee_name, "branch": e.branch,
            "designation": e.designation, "image": e.image, "punches": [], "trips": [],
        })

    for p in punches:
        row(p.employee)["punches"].append({
            "name": p.name, "type": p.log_type, "time": str(p.time),
            "lat": p.ess_latitude, "lng": p.ess_longitude, "accuracy": p.ess_accuracy,
            "inside": cint(p.ess_within_geofence), "geofence": p.ess_geofence, "selfie": p.ess_selfie,
        })
    for t in trips:
        coords = []
        try:
            for f in json.loads(t.route or "{}").get("features", []):
                if f.get("geometry", {}).get("type") == "LineString":
                    coords = [[c[1], c[0]] for c in f["geometry"]["coordinates"]]
        except (ValueError, TypeError, KeyError):
            pass
        lp = last_ping.get(t.name)
        row(t.employee)["trips"].append({
            "name": t.name, "status": t.status, "start_time": str(t.start_time),
            "end_time": str(t.end_time) if t.end_time else None, "distance_km": flt(t.distance_km, 2),
            "expense_claim": t.expense_claim, "route": coords,
            "last": {"time": str(lp.ping_time), "lat": lp.latitude, "lng": lp.longitude,
                     "accuracy": lp.accuracy, "battery": lp.battery} if lp else None,
        })

    for r in out.values():
        last = r["punches"][-1] if r["punches"] else None
        r["state"] = "in" if last and last["type"] == "IN" else ("out" if last else "none")

    geofences = frappe.get_all("ESS Geofence", filters={"enabled": 1},
                               fields=["name", "latitude", "longitude", "radius_m", "company", "branch"])
    if company:
        geofences = [g for g in geofences if not g.company or g.company == company]
    if branch:
        geofences = [g for g in geofences if not g.branch or g.branch == branch]

    return {
        "date": str(day),
        "employees": sorted(out.values(), key=lambda r: (r["state"] != "in", r["employee_name"] or "")),
        "geofences": geofences,
        "absent_count": len(employees) - len(out),
    }


# ---------------------------------------------------------------- actions
@frappe.whitelist(methods=["POST"])
def recompute_trip(trip: str):
    _require_hr()
    doc = frappe.get_doc("ESS Trip", trip)
    from ess_mobile.api.tracking import recompute_trip as _recompute

    _recompute(doc, save=True)
    return {"distance_km": flt(doc.distance_km, 2), "accepted_pings": doc.accepted_pings,
            "total_pings": doc.total_pings}


@frappe.whitelist(methods=["POST"])
def create_travel_claim(trip: str, description: str | None = None, transport_mode: str | None = None,
                        claim_km: float | None = None, personal_km: float | None = None):
    """HR raises the travel claim on the employee's behalf (same limits as the app)."""
    _require_hr()
    from ess_mobile.api.expense import _trip_and_employee, make_travel_claim

    t, emp = _trip_and_employee(trip)
    return make_travel_claim(emp, t, description, transport_mode=transport_mode, claim_km=claim_km,
                             personal_km=personal_km)


@frappe.whitelist(methods=["POST"])
def close_trip(trip: str):
    _require_hr()
    from ess_mobile.api.tracking import _close

    doc = frappe.get_doc("ESS Trip", trip)
    if doc.status != "Active":
        frappe.throw(_("Trip is already closed"))
    last = frappe.get_all("ESS Location Ping", filters={"trip": trip}, pluck="ping_time",
                          order_by="ping_time desc", limit=1)
    _close(doc, status="Auto Closed", end_time=last[0] if last else None)
    return {"status": doc.status, "distance_km": flt(doc.distance_km, 2)}


@frappe.whitelist(methods=["POST"])
def reset_device(employee: str):
    """Deactivate the employee's registered phone so their next login binds a new one."""
    _require_hr()
    names = frappe.get_all("ESS Device", filters={"employee": employee, "is_active": 1}, pluck="name")
    for n in names:
        frappe.db.set_value("ESS Device", n, "is_active", 0)
    user = frappe.db.get_value("Employee", employee, "user_id")
    if user:  # sign the old phone out immediately
        u = frappe.get_doc("User", user)
        if u.api_key:
            u.api_secret = frappe.generate_hash(length=15)
            u.save(ignore_permissions=True)
    return {"deactivated": len(names)}


@frappe.whitelist()
def employee_summary(employee: str):
    """Numbers for the Employee form's Mobile App tab."""
    _require_hr()
    device = frappe.db.get_value("ESS Device", {"employee": employee, "is_active": 1},
                                 ["name", "device_model", "app_version", "last_seen", "registered_on"], as_dict=True)
    month_start = getdate(nowdate()).replace(day=1)
    from ess_mobile.api.tracking import attendance_mode

    emp = frappe.db.get_value("Employee", employee, ["name", "ess_attendance_mode"], as_dict=True)
    return {
        "attendance_mode": attendance_mode(emp),
        "mode_is_default": not emp.ess_attendance_mode,
        "device": device,
        "checkins_this_month": frappe.db.count("Employee Checkin", {
            "employee": employee, "ess_device": ["is", "set"], "time": [">=", month_start]}),
        "rejected_this_month": frappe.db.count("ESS Checkin Attempt", {
            "employee": employee, "attempt_time": [">=", month_start]}),
        "km_this_month": flt(frappe.db.sql(
            "select sum(distance_km) from `tabESS Trip` where employee=%s and trip_date>=%s",
            (employee, month_start))[0][0] or 0, 2),
    }
