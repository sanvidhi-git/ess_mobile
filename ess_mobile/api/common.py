"""Shared helpers for the mobile API."""

import base64
import binascii

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_EXT = {"jpg", "jpeg", "png", "pdf", "webp"}


def settings():
    return frappe.get_cached_doc("ESS Settings")


def ensure_enabled():
    if not cint(settings().enable_app):
        frappe.throw(_("The mobile app is disabled. Please contact HR."), title=_("App Disabled"))


def current_employee(fields: list[str] | None = None) -> frappe._dict:
    """The Active employee linked to the logged-in user, or raise."""
    if frappe.session.user in ("Guest", None):
        raise frappe.AuthenticationError
    base = ["name", "employee_name", "company", "branch", "department", "designation",
            "holiday_list", "leave_approver", "expense_approver", "image", "user_id",
            "ess_geofence_exempt", "ess_attendance_mode"]
    emp = frappe.db.get_value(
        "Employee",
        {"user_id": frappe.session.user, "status": "Active"},
        list(dict.fromkeys(base + (fields or []))),
        as_dict=True,
    )
    if not emp:
        frappe.throw(_("No active Employee record is linked to user {0}.").format(frappe.session.user),
                     frappe.PermissionError, title=_("Not an Employee"))
    return emp


def touch_device(employee: str, device_id: str | None):
    """Validate device binding and update last_seen. Returns ESS Device name or None."""
    s = settings()
    if not device_id:
        if cint(s.bind_device):
            frappe.throw(_("Device ID missing. Please update the app."))
        return None
    active = frappe.db.get_value("ESS Device", {"employee": employee, "is_active": 1},
                                 ["name", "device_id"], as_dict=True)
    if cint(s.bind_device) and active and active.device_id != device_id:
        frappe.throw(_("Your account is registered on another phone. Ask HR to reset your device."),
                     frappe.PermissionError, title=_("Device Not Registered"))
    if active and active.device_id == device_id:
        frappe.db.set_value("ESS Device", active.name, "last_seen", now_datetime(), update_modified=False)
        return active.name
    return None


def save_base64_file(b64: str, filename: str, doctype: str, docname: str,
                     fieldname: str | None = None, is_private: int = 1) -> str:
    if not b64:
        return None
    if "," in b64[:100] and b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    try:
        content = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        frappe.throw(_("Invalid file encoding"))
    if len(content) > MAX_UPLOAD_BYTES:
        frappe.throw(_("File is larger than {0} MB").format(MAX_UPLOAD_BYTES // (1024 * 1024)))
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext not in ALLOWED_EXT:
        frappe.throw(_("File type .{0} is not allowed").format(ext))
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "attached_to_doctype": doctype,
        "attached_to_name": docname,
        "attached_to_field": fieldname,
        "is_private": is_private,
        "content": content,
        "decode": False,
    })
    file_doc.save(ignore_permissions=True)
    return file_doc.file_url


def parse_list(value):
    if isinstance(value, str):
        value = frappe.parse_json(value)
    return value or []


def log_rejected_attempt(emp, reason: str, message: str, ctx: dict):
    """Keep a record of a blocked check-in for HR, even though the request itself fails.

    Committed immediately because the frappe.throw that follows rolls back the request.
    """
    try:
        lat, lng = flt(ctx.get("latitude")), flt(ctx.get("longitude"))
        doc = frappe.get_doc({
            "doctype": "ESS Checkin Attempt",
            "employee": emp.name,
            "attempt_time": now_datetime(),
            "log_type": ctx.get("log_type"),
            "reason": reason,
            "message": message,
            "latitude": lat,
            "longitude": lng,
            "accuracy": flt(ctx.get("accuracy")),
            "is_mocked": cint(ctx.get("is_mocked")),
            "geofence": ctx.get("geofence"),
            "distance_m": ctx.get("distance_m"),
            "device_id": (ctx.get("device_id") or "")[:140],
            "location_map": frappe.as_json({"type": "FeatureCollection", "features": [{
                "type": "Feature", "properties": {},
                "geometry": {"type": "Point", "coordinates": [lng, lat]}}]}) if (lat or lng) else None,
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.log_error("ESS: could not log rejected check-in")
