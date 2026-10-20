"""Modes of transport (ESS Settings table) and per-employee defaults."""

import frappe
from frappe.utils import cint, flt

DEFAULT_MODES = [
    # Seed values only: HR sets the real rates in ESS Settings.
    {"mode": "Public Transport", "rate_per_km": 3, "uses_odometer": 0},
    {"mode": "Two Wheeler", "rate_per_km": 4, "uses_odometer": 1},
    {"mode": "Car", "rate_per_km": 10, "uses_odometer": 1},
]


def _settings():
    return frappe.get_cached_doc("ESS Settings")


def modes(s=None) -> list[dict]:
    s = s or _settings()
    fallback = flt(s.get("rate_per_km"))
    return [
        {
            "mode": r.mode,
            "rate_per_km": flt(r.rate_per_km) or fallback,
            "uses_odometer": cint(r.uses_odometer),
            "expense_claim_type": r.expense_claim_type or s.travel_expense_type,
        }
        for r in (s.get("transport_modes") or [])
        if cint(r.enabled) and r.mode
    ]


def get_mode(name: str | None, s=None) -> dict | None:
    for m in modes(s):
        if m["mode"] == name:
            return m
    return None


def employee_mode(emp, s=None) -> dict | None:
    """Employee's own mode, else the company default, else the first enabled mode."""
    s = s or _settings()
    own = emp.get("ess_transport_mode") if hasattr(emp, "get") else None
    return get_mode(own, s) or get_mode(s.get("default_transport_mode"), s) or (modes(s) or [None])[0]


def odometer_applies(emp, s=None) -> bool:
    s = s or _settings()
    if (s.get("odometer_capture") or "Off") == "Off":
        return False
    m = employee_mode(emp, s)
    return bool(m and m["uses_odometer"])


def sync_employee_mode_options(s=None):
    """Keep the Employee 'Mode of Transport' dropdown in step with ESS Settings."""
    s = s or frappe.get_single("ESS Settings")
    names = [r.mode for r in (s.get("transport_modes") or []) if cint(r.enabled) and r.mode]
    cf = frappe.db.get_value("Custom Field", {"dt": "Employee", "fieldname": "ess_transport_mode"}, "name")
    if not cf:
        return
    options = "\n" + "\n".join(names)
    if frappe.db.get_value("Custom Field", cf, "options") != options:
        frappe.db.set_value("Custom Field", cf, "options", options)
        frappe.clear_cache(doctype="Employee")


def seed_defaults():
    """First-time defaults for transport modes and odometer capture (install + upgrade)."""
    s = frappe.get_single("ESS Settings")
    changed = False
    if not s.get("transport_modes"):
        for m in DEFAULT_MODES:
            s.append("transport_modes", dict(m, enabled=1))
        changed = True
    if not s.get("default_transport_mode"):
        s.default_transport_mode = "Two Wheeler" if any(r.mode == "Two Wheeler" for r in s.transport_modes) \
            else s.transport_modes[0].mode
        changed = True
    if not s.get("odometer_capture"):
        s.odometer_capture = "Optional"
        changed = True
    if changed:
        s.flags.ignore_mandatory = True
        s.save(ignore_permissions=True)
    else:
        sync_employee_mode_options(s)
