"""Login / logout / bootstrap for the mobile app.

The app authenticates with username + password once; the server returns an
API key/secret pair which the app keeps in encrypted storage and sends as
`Authorization: token <key>:<secret>` on every call.
"""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, flt, now_datetime

from ess_mobile.api.common import current_employee, ensure_enabled, settings


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=600)
def login(usr: str, pwd: str, device_id: str, device_model: str | None = None,
          os_version: str | None = None, app_version: str | None = None):
    ensure_enabled()
    if not device_id:
        frappe.throw(_("Device ID missing. Please update the app."))

    login_manager = frappe.local.login_manager
    login_manager.authenticate(user=usr, pwd=pwd)  # raises AuthenticationError on bad credentials
    user = login_manager.user

    # act as the user for the rest of the request
    frappe.set_user(user)
    emp = current_employee()
    device = _bind_device(emp, user, device_id, device_model, os_version, app_version)

    user_doc = frappe.get_doc("User", user)
    if not user_doc.api_key:
        user_doc.api_key = frappe.generate_hash(length=15)
    api_secret = frappe.generate_hash(length=15)
    user_doc.api_secret = api_secret
    user_doc.flags.ignore_permissions = True
    user_doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "api_key": user_doc.api_key,
        "api_secret": api_secret,
        "user": user,
        "device": device,
        "bootstrap": _bootstrap(emp),
    }


@frappe.whitelist(methods=["GET"])
def bootstrap():
    """Profile + settings the app needs at start-up."""
    ensure_enabled()
    emp = current_employee()
    return _bootstrap(emp)


@frappe.whitelist(methods=["POST"])
def logout():
    """Invalidate the secret this device holds."""
    user_doc = frappe.get_doc("User", frappe.session.user)
    user_doc.api_secret = frappe.generate_hash(length=15)
    user_doc.save(ignore_permissions=True)
    return {"ok": True}


def _bind_device(emp, user, device_id, device_model, os_version, app_version):
    s = settings()
    active = frappe.db.get_value("ESS Device", {"employee": emp.name, "is_active": 1},
                                 ["name", "device_id"], as_dict=True)
    if active and active.device_id == device_id:
        frappe.db.set_value("ESS Device", active.name, {
            "last_seen": now_datetime(), "app_version": app_version, "os_version": os_version,
        }, update_modified=False)
        return active.name
    if active and cint(s.bind_device):
        frappe.throw(_("Your account is registered on another phone. Ask HR to reset your device."),
                     frappe.PermissionError, title=_("Device Not Registered"))
    if active:  # binding disabled: retire the old device record
        frappe.db.set_value("ESS Device", active.name, "is_active", 0)
    doc = frappe.get_doc({
        "doctype": "ESS Device",
        "employee": emp.name,
        "user": user,
        "device_id": device_id,
        "device_model": device_model,
        "os_version": os_version,
        "app_version": app_version,
        "registered_on": now_datetime(),
        "last_seen": now_datetime(),
        "is_active": 1,
    }).insert(ignore_permissions=True)
    return doc.name


def _bootstrap(emp):
    from ess_mobile.api.attendance import applicable_geofences, today_status

    s = settings()
    from ess_mobile.api.tracking import attendance_mode

    from ess_mobile.api.transport import employee_mode, modes, odometer_applies

    mode = attendance_mode(emp)
    tracking = mode == "Live Tracking"
    tmodes = modes(s)
    my_mode = employee_mode(emp, s)
    return {
        "server_time": str(now_datetime()),
        "employee": {
            "id": emp.name,
            "name": emp.employee_name,
            "company": emp.company,
            "branch": emp.branch,
            "department": emp.department,
            "designation": emp.designation,
            "image": emp.image,
            "geofence_exempt": cint(emp.ess_geofence_exempt),
        },
        "settings": {
            "require_selfie": cint(s.require_selfie),
            "require_liveness": cint(s.require_liveness),
            "block_mock_location": cint(s.block_mock_location),
            "block_rooted_devices": cint(s.block_rooted_devices),
            "max_accuracy_m": s.max_accuracy_m or 100,
            "enforce_geofence": cint(s.enforce_geofence) and not cint(emp.ess_geofence_exempt),
            "attendance_mode": mode,
            "tracking_enabled": cint(tracking),
            "ping_interval_sec": cint(s.ping_interval_sec) or 60,
            "min_distance_filter_m": cint(s.min_distance_filter_m) or 25,
            "rate_per_km": (my_mode or {}).get("rate_per_km") or s.rate_per_km or 0,
            "travel_claim_enabled": cint(any(m["expense_claim_type"] and m["rate_per_km"] for m in tmodes)
                                         or bool(s.travel_expense_type and s.rate_per_km)),
            "transport_modes": [{"mode": m["mode"], "rate_per_km": m["rate_per_km"],
                                 "uses_odometer": m["uses_odometer"]} for m in tmodes],
            "transport_mode": (my_mode or {}).get("mode"),
            "odometer_capture": s.get("odometer_capture") or "Off",
            "min_claim_km": flt(s.min_claim_km),
            "odometer_applies": cint(tracking and odometer_applies(emp, s)),
        },
        "geofences": applicable_geofences(emp),
        "today": today_status(emp),
    }
