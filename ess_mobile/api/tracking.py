"""Location tracking between check-in and check-out, and distance computation."""

import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, flt, get_system_timezone, getdate, now_datetime

from ess_mobile.api.common import current_employee, ensure_enabled, parse_list, settings
from ess_mobile.utils.geo import downsample, filter_and_measure

LATE_SYNC_HOURS = 12
MAX_PINGS_PER_CALL = 500
_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,40}$")


CHECKIN_ONLY = "Check-in Only"
LIVE_TRACKING = "Live Tracking"


def attendance_mode(emp) -> str:
    """Employee override if set, else the company default from ESS Settings."""
    return emp.get("ess_attendance_mode") or settings().default_attendance_mode or CHECKIN_ONLY


def tracking_enabled_for(emp) -> bool:
    return attendance_mode(emp) == LIVE_TRACKING


def close_open_trips(emp, status="Auto Closed"):
    for name in frappe.get_all("ESS Trip", filters={"employee": emp.name, "status": "Active"}, pluck="name"):
        _close(frappe.get_doc("ESS Trip", name), status=status)


# ---------------------------------------------------------------- lifecycle
def start_trip(emp, checkin_doc, point: dict):
    close_open_trips(emp)
    trip = frappe.get_doc({
        "doctype": "ESS Trip",
        "employee": emp.name,
        "status": "Active",
        "trip_date": getdate(checkin_doc.time),
        "start_time": checkin_doc.time,
        "start_checkin": checkin_doc.name,
    }).insert(ignore_permissions=True)
    _insert_pings(trip.name, emp.name, [dict(point, ping_time=checkin_doc.time)])
    return trip


def end_trip(emp, checkin_doc, point: dict):
    name = frappe.db.get_value("ESS Trip", {"employee": emp.name, "status": "Active"}, "name",
                               order_by="start_time desc")
    if not name:
        return None
    trip = frappe.get_doc("ESS Trip", name)
    _insert_pings(trip.name, emp.name, [dict(point, ping_time=checkin_doc.time)])
    trip.end_checkin = checkin_doc.name
    return _close(trip, status="Completed", end_time=checkin_doc.time)


def _close(trip, status: str, end_time=None):
    trip.status = status
    trip.end_time = end_time or now_datetime()
    recompute_trip(trip, save=False)
    trip.save(ignore_permissions=True)
    return trip


def close_stale_trips():
    """Hourly: auto-close trips left open (e.g. employee forgot to check out)."""
    hours = cint(settings().stale_trip_hours) or 18
    cutoff = add_to_date(now_datetime(), hours=-hours)
    for name in frappe.get_all("ESS Trip", filters={"status": "Active", "start_time": ["<", cutoff]}, pluck="name"):
        trip = frappe.get_doc("ESS Trip", name)
        last = frappe.get_all("ESS Location Ping", filters={"trip": name}, pluck="ping_time",
                              order_by="ping_time desc", limit=1)
        last = last[0] if last else None
        _close(trip, status="Auto Closed", end_time=last or trip.start_time)
    frappe.db.commit()


# ---------------------------------------------------------------- pings
@frappe.whitelist(methods=["POST"])
def push_pings(trip: str, pings):
    """Batch upload of queued GPS points.

    pings: [{id, t (epoch ms), lat, lng, acc, spd, mock, bat}]
    Idempotent: re-sending the same ping ids is harmless.
    """
    ensure_enabled()
    emp = current_employee()
    pings = parse_list(pings)[:MAX_PINGS_PER_CALL]
    doc = frappe.get_doc("ESS Trip", trip)
    if doc.employee != emp.name:
        frappe.throw(_("Not your trip"), frappe.PermissionError)
    if doc.status != "Active":
        if not doc.end_time or (now_datetime() - doc.end_time).total_seconds() > LATE_SYNC_HOURS * 3600:
            return {"accepted": 0, "trip_status": doc.status, "distance_km": flt(doc.distance_km, 2)}

    lo = add_to_date(doc.start_time, minutes=-5)
    hi = add_to_date(doc.end_time or now_datetime(), minutes=5)
    tz = ZoneInfo(get_system_timezone())
    rows = []
    for p in pings:
        try:
            t = datetime.fromtimestamp(int(p["t"]) / 1000, tz=timezone.utc).astimezone(tz).replace(tzinfo=None)
            lat, lng = float(p["lat"]), float(p["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (lo <= t <= hi) or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            continue
        rows.append({
            "id": p.get("id") if _ID_RE.match(str(p.get("id") or "")) else None,
            "ping_time": t, "latitude": lat, "longitude": lng,
            "accuracy": flt(p.get("acc")), "speed": flt(p.get("spd")),
            "is_mocked": cint(p.get("mock")), "battery": cint(p.get("bat")),
        })
    _insert_pings(doc.name, emp.name, rows)
    recompute_trip(doc, save=True)
    return {"accepted": len(rows), "trip_status": doc.status, "distance_km": flt(doc.distance_km, 2)}


def _insert_pings(trip: str, employee: str, rows: list[dict]):
    if not rows:
        return
    now = now_datetime()
    user = frappe.session.user
    fields = ["name", "creation", "modified", "owner", "modified_by", "docstatus", "trip", "employee",
              "ping_time", "latitude", "longitude", "accuracy", "speed", "is_mocked", "battery"]
    values = [
        (r.get("id") or frappe.generate_hash(length=20), now, now, user, user, 0, trip, employee,
         r["ping_time"], r["latitude"], r["longitude"], flt(r.get("accuracy")), flt(r.get("speed")),
         cint(r.get("is_mocked")), cint(r.get("battery")))
        for r in rows
    ]
    frappe.db.bulk_insert("ESS Location Ping", fields, values, ignore_duplicates=True)


def recompute_trip(trip, save: bool = True):
    s = settings()
    points = frappe.get_all(
        "ESS Location Ping",
        filters={"trip": trip.name},
        fields=["latitude", "longitude", "accuracy", "ping_time", "is_mocked"],
        order_by="ping_time asc",
    )
    dist_m, accepted = filter_and_measure(
        points,
        max_accuracy_m=flt(s.max_ping_accuracy_m) or 50,
        max_speed_kmph=flt(s.max_speed_kmph) or 150,
        min_segment_m=flt(s.min_segment_m) or 20,
    )
    trip.distance_km = flt(dist_m / 1000.0, 3)
    trip.total_pings = len(points)
    trip.accepted_pings = len(accepted)
    coords = [[p["longitude"], p["latitude"]] for p in downsample(accepted)]
    features = []
    if len(coords) >= 2:
        features.append({"type": "Feature", "properties": {},
                         "geometry": {"type": "LineString", "coordinates": coords}})
    if coords:
        features.append({"type": "Feature", "properties": {},
                         "geometry": {"type": "Point", "coordinates": coords[0]}})
    trip.route = json.dumps({"type": "FeatureCollection", "features": features})
    if save:
        trip.db_update()
    return trip


# ---------------------------------------------------------------- read
@frappe.whitelist(methods=["GET"])
def get_trips(limit: int = 30, start: int = 0):
    emp = current_employee()
    return frappe.get_all(
        "ESS Trip",
        filters={"employee": emp.name},
        fields=["name", "status", "trip_date", "start_time", "end_time", "distance_km", "expense_claim",
                "claimed_km", "odometer_start", "odometer_end", "odometer_km", "transport_mode", "personal_km"],
        order_by="start_time desc",
        limit_start=cint(start),
        limit_page_length=min(cint(limit) or 30, 100),
    )


@frappe.whitelist(methods=["GET"])
def get_trip(trip: str):
    emp = current_employee()
    doc = frappe.get_doc("ESS Trip", trip)
    if doc.employee != emp.name:
        frappe.throw(_("Not your trip"), frappe.PermissionError)
    route = json.loads(doc.route or "{}")
    line = next((f["geometry"]["coordinates"] for f in route.get("features", [])
                 if f.get("geometry", {}).get("type") == "LineString"), [])
    return {
        "name": doc.name, "status": doc.status, "trip_date": str(doc.trip_date),
        "start_time": str(doc.start_time), "end_time": str(doc.end_time) if doc.end_time else None,
        "distance_km": flt(doc.distance_km, 2), "expense_claim": doc.expense_claim,
        "points": [[c[1], c[0]] for c in line],  # [lat, lng]
    }
