"""Selfie + geolocation check-in, geofences and attendance history."""

import calendar
import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowdate, time_diff_in_seconds

from ess_mobile.api.common import (
    current_employee,
    ensure_enabled,
    log_rejected_attempt,
    save_base64_file,
    settings,
    touch_device,
)
from ess_mobile.utils.geo import haversine_m


# ---------------------------------------------------------------- geofences
def applicable_geofences(emp) -> list[dict]:
    rows = frappe.get_all(
        "ESS Geofence",
        filters={"enabled": 1},
        fields=["name", "company", "branch", "employee", "latitude", "longitude", "radius_m"],
    )
    out = []
    for g in rows:
        if g.company and g.company != emp.company:
            continue
        if g.branch and g.branch != emp.branch:
            continue
        if g.employee and g.employee != emp.name:
            continue
        out.append({"name": g.name, "latitude": g.latitude, "longitude": g.longitude, "radius_m": g.radius_m})
    return out


def nearest_geofence(emp, lat: float, lng: float):
    """(geofence, distance_m, inside) for the closest applicable geofence."""
    best = None
    for g in applicable_geofences(emp):
        d = haversine_m(lat, lng, g["latitude"], g["longitude"])
        # 'inside' if within radius; rank by distance from the edge
        edge = d - g["radius_m"]
        if best is None or edge < best[3]:
            best = (g, d, d <= g["radius_m"], edge)
    if not best:
        return None, None, None
    return best[0], best[1], best[2]


@frappe.whitelist(methods=["GET"])
def get_geofences():
    return applicable_geofences(current_employee())


# ---------------------------------------------------------------- status
def _last_log(employee):
    rows = frappe.get_all(
        "Employee Checkin",
        filters={"employee": employee},
        fields=["name", "log_type", "time"],
        order_by="time desc, creation desc",
        limit=1,
    )
    return rows[0] if rows else None


def today_status(emp) -> dict:
    today = getdate(nowdate())
    logs = frappe.get_all(
        "Employee Checkin",
        filters={"employee": emp.name, "time": ["between", [f"{today} 00:00:00", f"{today} 23:59:59"]]},
        fields=["name", "log_type", "time", "ess_within_geofence", "ess_geofence"],
        order_by="time asc",
    )
    last = _last_log(emp.name)
    next_type = "OUT" if last and last.log_type == "IN" and _hours_since(last.time) < 20 else "IN"
    trip = frappe.db.get_value("ESS Trip", {"employee": emp.name, "status": "Active"},
                               ["name", "start_time", "distance_km", "odometer_start"], as_dict=True)
    first_in = next((l.time for l in logs if l.log_type == "IN"), None)
    last_out = next((l.time for l in reversed(logs) if l.log_type == "OUT"), None)
    worked = 0
    open_in = None
    for l in logs:
        if l.log_type == "IN":
            open_in = l.time
        elif open_in:
            worked += time_diff_in_seconds(l.time, open_in)
            open_in = None
    if open_in and next_type == "OUT":
        worked += time_diff_in_seconds(now_datetime(), open_in)
    return {
        "date": str(today),
        "next_log_type": next_type,
        "last_log": {"type": last.log_type, "time": str(last.time)} if last else None,
        "first_in": str(first_in) if first_in else None,
        "last_out": str(last_out) if last_out else None,
        "worked_seconds": int(worked),
        "logs": [{"name": l.name, "type": l.log_type, "time": str(l.time),
                  "geofence": l.ess_geofence, "inside": cint(l.ess_within_geofence)} for l in logs],
        "active_trip": {"name": trip.name, "start_time": str(trip.start_time),
                        "distance_km": flt(trip.distance_km, 2),
                        "odometer_start": flt(trip.odometer_start, 1) if trip.odometer_start else None} if trip else None,
    }


def _hours_since(dt) -> float:
    return time_diff_in_seconds(now_datetime(), dt) / 3600.0


@frappe.whitelist(methods=["GET"])
def get_today():
    ensure_enabled()
    return today_status(current_employee())


# ---------------------------------------------------------------- check-in
@frappe.whitelist(methods=["POST"])
def checkin(log_type: str, latitude: float, longitude: float, accuracy: float | None = None,
            is_mocked: int = 0, is_rooted: int = 0, selfie: str | None = None,
            face_count: int | None = None, liveness_passed: int = 0, device_id: str | None = None,
            odometer_reading: float | None = None, odometer_photo: str | None = None):
    ensure_enabled()
    s = settings()
    emp = current_employee()
    log_type = (log_type or "").upper()
    if log_type not in ("IN", "OUT"):
        frappe.throw(_("Log type must be IN or OUT"))
    latitude, longitude, accuracy = flt(latitude), flt(longitude), flt(accuracy)
    if not latitude and not longitude:
        frappe.throw(_("Location is required. Turn on GPS and try again."), title=_("Location Missing"))

    ctx = {"log_type": log_type, "latitude": latitude, "longitude": longitude, "accuracy": accuracy,
           "device_id": device_id, "is_mocked": cint(is_mocked)}

    def reject(reason: str, message: str, title: str | None = None, **extra):
        log_rejected_attempt(emp, reason, message, dict(ctx, **extra))
        frappe.throw(message, title=title or reason)

    try:
        device = touch_device(emp.name, device_id)
    except frappe.PermissionError:
        log_rejected_attempt(emp, "Unregistered Device", _("Check-in from a phone not registered to this employee"), ctx)
        raise

    # --- integrity checks
    if cint(s.block_mock_location) and cint(is_mocked):
        reject("Mock Location", _("A fake GPS / mock location app was detected. Disable it to mark attendance."))
    if cint(s.block_rooted_devices) and cint(is_rooted):
        reject("Rooted Device", _("Attendance cannot be marked from a rooted device or emulator."),
               _("Device Not Allowed"))
    if s.max_accuracy_m and accuracy and accuracy > flt(s.max_accuracy_m):
        reject("Weak GPS", _("GPS accuracy is {0} m (limit {1} m). Move to an open area and retry.")
               .format(int(accuracy), int(s.max_accuracy_m)))
    if cint(s.require_selfie) and not selfie:
        reject("Selfie Missing", _("A selfie is required to mark attendance."), _("Selfie Required"))
    if cint(s.require_liveness) and not cint(liveness_passed):
        reject("Liveness Failed", _("Liveness check was not completed."))
    if selfie and face_count is not None and cint(face_count) != 1:
        reject("Face Check Failed", _("Exactly one face must be visible in the selfie."), _("Selfie Rejected"))

    # --- sequence checks (not logged: ordinary user mistakes)
    last = _last_log(emp.name)
    if last:
        gap = time_diff_in_seconds(now_datetime(), last.time)
        if gap < cint(s.min_seconds_between_logs):
            frappe.throw(_("You just marked {0}. Please wait a moment.").format(last.log_type))
        if cint(s.strict_alternate_logs) and last.log_type == log_type and gap < 20 * 3600:
            frappe.throw(_("You have already checked {0}.").format(log_type.lower()), title=_("Already Marked"))
    elif cint(s.strict_alternate_logs) and log_type == "OUT":
        frappe.throw(_("Please check in first."))

    # --- geofence
    fence, dist, inside = nearest_geofence(emp, latitude, longitude)
    if cint(s.enforce_geofence) and not cint(emp.ess_geofence_exempt) and fence and not inside:
        reject(
            "Outside Geofence",
            _("You are {0} m from {1} (allowed radius {2} m).").format(int(dist), fence["name"], fence["radius_m"]),
            _("Outside Permitted Area"),
            geofence=fence["name"], distance_m=flt(dist, 1),
        )

    # --- odometer (Live Tracking + own-vehicle mode): validate before anything is saved
    from ess_mobile.api.tracking import tracking_enabled_for
    from ess_mobile.api.transport import odometer_applies

    odo = flt(odometer_reading) if odometer_reading not in (None, "") else None
    open_trip = frappe.db.get_value("ESS Trip", {"employee": emp.name, "status": "Active"},
                                    ["name", "odometer_start"], as_dict=True, order_by="start_time desc")
    if odo is not None and odo < 0:
        frappe.throw(_("Odometer reading cannot be negative."), title=_("Odometer"))
    if log_type == "IN" and tracking_enabled_for(emp) and odometer_applies(emp, s):
        if s.odometer_capture == "Required" and (odo is None or not odometer_photo):
            frappe.throw(_("Enter the odometer reading and take a photo of the odometer to check in."),
                         title=_("Odometer Required"))
    if log_type == "OUT" and open_trip and open_trip.odometer_start is not None and flt(open_trip.odometer_start) > 0:
        if odo is None and s.odometer_capture == "Required":
            frappe.throw(_("Enter the odometer reading at check-out (it was {0} at check-in).")
                         .format(flt(open_trip.odometer_start, 1)), title=_("Odometer Required"))
        if odo is not None and odo < flt(open_trip.odometer_start):
            frappe.throw(_("Check-out odometer {0} is lower than the check-in reading {1}.")
                         .format(flt(odo, 1), flt(open_trip.odometer_start, 1)), title=_("Odometer"))

    # --- create the checkin
    doc = frappe.new_doc("Employee Checkin")
    meta = doc.meta
    doc.employee = emp.name
    doc.log_type = log_type
    doc.time = now_datetime()
    doc.device_id = f"ESS App ({device or device_id or 'unknown'})"[:140]
    if meta.has_field("latitude"):
        doc.latitude = latitude
        doc.longitude = longitude
    if meta.has_field("geolocation"):
        doc.geolocation = json.dumps({"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]}}]})
    doc.update({
        "ess_latitude": latitude,
        "ess_longitude": longitude,
        "ess_accuracy": accuracy,
        "ess_is_mocked": cint(is_mocked),
        "ess_face_count": cint(face_count) if face_count is not None else None,
        "ess_liveness_passed": cint(liveness_passed),
        "ess_geofence": fence["name"] if fence else None,
        "ess_distance_m": flt(dist, 1) if dist is not None else None,
        "ess_within_geofence": 1 if inside else 0,
        "ess_device": device,
    })
    doc.insert(ignore_permissions=True)

    if selfie:
        fname = f"selfie-{emp.name}-{doc.time.strftime('%Y%m%d-%H%M%S')}.jpg"
        url = save_base64_file(selfie, fname, "Employee Checkin", doc.name, "ess_selfie")
        doc.db_set("ess_selfie", url, update_modified=False)

    # --- live tracking: IN starts a trip only in Live Tracking mode; OUT closes any open trip,
    # so a trip ends cleanly even if HR switched the employee's mode during the day.
    trip = None
    from ess_mobile.api.tracking import close_open_trips, end_trip, start_trip

    point = {"latitude": latitude, "longitude": longitude, "accuracy": accuracy, "is_mocked": cint(is_mocked)}
    if log_type == "IN":
        if tracking_enabled_for(emp):
            trip = start_trip(emp, doc, point)
        else:
            close_open_trips(emp)
    else:
        trip = end_trip(emp, doc, point)
    if trip:
        doc.db_set("ess_trip", trip.name, update_modified=False)
        if odo is not None:
            _save_odometer(trip, log_type, odo, odometer_photo, emp.name, doc.time)

    return {
        "checkin": doc.name,
        "log_type": log_type,
        "time": str(doc.time),
        "geofence": fence["name"] if fence else None,
        "distance_m": flt(dist, 1) if dist is not None else None,
        "inside": cint(inside),
        "trip": {"name": trip.name, "status": trip.status, "distance_km": flt(trip.distance_km, 2)} if trip else None,
        "today": today_status(emp),
    }


def _save_odometer(trip, log_type: str, reading: float, photo_b64: str | None, employee: str, at):
    which = "start" if log_type == "IN" else "end"
    url = None
    if photo_b64:
        url = save_base64_file(photo_b64, f"odometer-{which}-{employee}-{at.strftime('%Y%m%d-%H%M%S')}.jpg",
                               "ESS Trip", trip.name, f"odometer_{which}_photo")
    values = {f"odometer_{which}": reading}
    if url:
        values[f"odometer_{which}_photo"] = url
    start = reading if which == "start" else flt(frappe.db.get_value("ESS Trip", trip.name, "odometer_start"))
    end = reading if which == "end" else None
    if end is not None and start:
        values["odometer_km"] = flt(end - start, 1)
    frappe.db.set_value("ESS Trip", trip.name, values, update_modified=False)


# ---------------------------------------------------------------- history
@frappe.whitelist(methods=["GET"])
def get_month(year: int, month: int):
    """Attendance, checkins and holidays for one month, keyed by date."""
    emp = current_employee()
    year, month = cint(year), cint(month)
    start = getdate(f"{year}-{month:02d}-01")
    end = getdate(f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]}")

    days: dict[str, dict] = {}

    def day(d):
        return days.setdefault(str(d), {"date": str(d), "status": None, "logs": []})

    for a in frappe.get_all(
        "Attendance",
        filters={"employee": emp.name, "docstatus": 1, "attendance_date": ["between", [start, end]]},
        fields=["attendance_date", "status", "leave_type", "working_hours", "late_entry", "early_exit",
                "in_time", "out_time"],
    ):
        d = day(a.attendance_date)
        d.update({"status": a.status, "leave_type": a.leave_type, "working_hours": flt(a.working_hours, 2),
                  "late_entry": cint(a.late_entry), "early_exit": cint(a.early_exit)})

    for c in frappe.get_all(
        "Employee Checkin",
        filters={"employee": emp.name, "time": ["between", [f"{start} 00:00:00", f"{end} 23:59:59"]]},
        fields=["log_type", "time", "ess_within_geofence"],
        order_by="time asc",
    ):
        day(getdate(c.time))["logs"].append({"type": c.log_type, "time": str(c.time),
                                            "inside": cint(c.ess_within_geofence)})

    holidays = _holidays(emp, start, end)
    for h in holidays:
        d = day(h["date"])
        d["holiday"] = h["description"]
        d["weekly_off"] = h["weekly_off"]

    summary: dict[str, int] = {}
    for d in days.values():
        if d.get("status"):
            summary[d["status"]] = summary.get(d["status"], 0) + 1
    return {"year": year, "month": month, "days": sorted(days.values(), key=lambda x: x["date"]),
            "summary": summary}


def holiday_list_for(emp):
    """Employee's holiday list: v16 assignment if any, else Employee field, else Company default."""
    hl = None
    try:
        from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

        hl = get_holiday_list_for_employee(emp.name, raise_exception=False)
    except Exception:
        pass
    return hl or emp.holiday_list or frappe.get_cached_value("Company", emp.company, "default_holiday_list")


def _holidays(emp, start, end) -> list[dict]:
    hl = holiday_list_for(emp)
    if not hl:
        return []
    return [
        {"date": str(h.holiday_date), "description": frappe.utils.strip_html(h.description or ""),
         "weekly_off": cint(h.weekly_off)}
        for h in frappe.get_all(
            "Holiday",
            filters={"parent": hl, "parenttype": "Holiday List", "holiday_date": ["between", [start, end]]},
            fields=["holiday_date", "description", "weekly_off"],
            order_by="holiday_date asc",
        )
    ]


@frappe.whitelist(methods=["GET"])
def get_holidays(year: int | None = None, include_weekly_off: int = 0):
    emp = current_employee()
    year = cint(year) or getdate().year
    rows = _holidays(emp, getdate(f"{year}-01-01"), getdate(f"{year}-12-31"))
    if not cint(include_weekly_off):
        rows = [r for r in rows if not r["weekly_off"]]
    return rows


@frappe.whitelist(methods=["GET"])
def home_summary():
    """This month at a glance for the app's home screen."""
    emp = current_employee()
    today = getdate(nowdate())
    start = today.replace(day=1)
    att = frappe.get_all("Attendance", filters={"employee": emp.name, "docstatus": 1,
                                                "attendance_date": ["between", [start, today]]},
                         fields=["status", "working_hours"])
    present = sum(1 for a in att if a.status in ("Present", "Work From Home"))
    half = sum(1 for a in att if a.status == "Half Day")
    hours = sum(flt(a.working_hours) for a in att)
    punch_days = len({getdate(t) for t in frappe.get_all(
        "Employee Checkin", filters={"employee": emp.name, "time": [">=", f"{start} 00:00:00"]}, pluck="time")})

    leave_left = None
    try:
        from hrms.hr.doctype.leave_application.leave_application import get_leave_details

        alloc = (get_leave_details(emp.name, nowdate()).get("leave_allocation") or {})
        leave_left = flt(sum(flt(v.get("remaining_leaves")) for v in alloc.values()), 1)
    except Exception:
        pass

    drafts = frappe.get_all("Expense Claim", filters={"employee": emp.name, "docstatus": 0},
                            fields=["total_claimed_amount", "approval_status"])
    pending = frappe.get_all("Expense Claim", filters={"employee": emp.name, "docstatus": 1, "status": "Unpaid"},
                             fields=["total_sanctioned_amount"])
    s = settings()
    unclaimed = frappe.get_all("ESS Trip", filters={"employee": emp.name, "status": ["!=", "Active"],
                                                    "expense_claim": ["is", "not set"],
                                                    "distance_km": [">=", max(flt(s.min_claim_km), 0.01)]},
                               fields=["distance_km"])
    hl_rows = []
    hl = holiday_list_for(emp)
    if hl:
        hl_rows = frappe.get_all("Holiday", filters={"parent": hl, "holiday_date": [">=", today], "weekly_off": 0},
                                 fields=["holiday_date", "description"], order_by="holiday_date asc", limit=1)
    return {
        "month": today.strftime("%B"),
        "present_days": present,
        "half_days": half,
        "punch_days": punch_days,
        "hours": flt(hours, 1),
        "leave_left": leave_left,
        "draft_claims": len(drafts),
        "draft_amount": flt(sum(flt(d.total_claimed_amount) for d in drafts), 2),
        "awaiting_payment": flt(sum(flt(p.total_sanctioned_amount) for p in pending), 2),
        "unclaimed_trips": len(unclaimed),
        "unclaimed_km": flt(sum(flt(u.distance_km) for u in unclaimed), 1),
        "next_holiday": {"date": str(hl_rows[0].holiday_date),
                         "name": frappe.utils.strip_html(hl_rows[0].description or "")} if hl_rows else None,
    }
