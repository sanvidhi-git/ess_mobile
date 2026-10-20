"""Custom fields added to standard HRMS / ERPNext doctypes.

Fields are appended after the last existing field of each doctype so the
standard layout is not disturbed, whatever the exact HRMS minor version.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def _last_field(doctype: str) -> str:
    meta = frappe.get_meta(doctype)
    own = [df.fieldname for df in meta.fields if not df.fieldname.startswith("ess_")]
    return own[-1] if own else None


def _chain(doctype: str, fields: list[dict]) -> list[dict]:
    after = _last_field(doctype)
    out = []
    for df in fields:
        df = dict(df, insert_after=after)
        after = df["fieldname"]
        out.append(df)
    return out


CHECKIN_FIELDS = [
    {"fieldname": "ess_section", "fieldtype": "Section Break", "label": "Mobile App Capture", "collapsible": 1},
    {"fieldname": "ess_selfie", "fieldtype": "Attach Image", "label": "Selfie", "read_only": 1},
    {"fieldname": "ess_liveness_passed", "fieldtype": "Check", "label": "Liveness Passed", "read_only": 1},
    {"fieldname": "ess_face_count", "fieldtype": "Int", "label": "Faces Detected", "read_only": 1},
    {"fieldname": "ess_col1", "fieldtype": "Column Break"},
    {"fieldname": "ess_latitude", "fieldtype": "Float", "label": "Latitude", "precision": "7", "read_only": 1},
    {"fieldname": "ess_longitude", "fieldtype": "Float", "label": "Longitude", "precision": "7", "read_only": 1},
    {"fieldname": "ess_accuracy", "fieldtype": "Float", "label": "GPS Accuracy (m)", "read_only": 1},
    {"fieldname": "ess_is_mocked", "fieldtype": "Check", "label": "Mock Location Reported", "read_only": 1},
    {"fieldname": "ess_col2", "fieldtype": "Column Break"},
    {"fieldname": "ess_geofence", "fieldtype": "Link", "label": "Geofence", "options": "ESS Geofence", "read_only": 1},
    {"fieldname": "ess_distance_m", "fieldtype": "Float", "label": "Distance From Geofence Centre (m)", "read_only": 1},
    {"fieldname": "ess_within_geofence", "fieldtype": "Check", "label": "Within Geofence", "read_only": 1},
    {"fieldname": "ess_device", "fieldtype": "Link", "label": "ESS Device", "options": "ESS Device", "read_only": 1},
    {"fieldname": "ess_trip", "fieldtype": "Link", "label": "Trip", "options": "ESS Trip", "read_only": 1},
]

EMPLOYEE_FIELDS = [
    {"fieldname": "ess_tab", "fieldtype": "Tab Break", "label": "Mobile App"},
    {"fieldname": "ess_geofence_exempt", "fieldtype": "Check", "label": "Exempt from Geofence",
     "description": "Field staff who may check in from anywhere."},
    {"fieldname": "ess_attendance_mode", "fieldtype": "Select", "label": "Attendance Mode",
     "options": "\nCheck-in Only\nLive Tracking", "in_standard_filter": 1,
     "description": "Blank = company default from ESS Settings. Check-in Only: selfie + location at IN and OUT. "
                    "Live Tracking: also records the route from check-in to check-out."},
    {"fieldname": "ess_transport_mode", "fieldtype": "Select", "label": "Mode of Transport",
     "options": "", "in_standard_filter": 1,
     "description": "Default for this employee's travel claims (rates are in ESS Settings). "
                    "Blank = ESS Settings default. The employee can pick another mode when claiming."},
]

EXPENSE_CLAIM_FIELDS = [
    {"fieldname": "ess_trip", "fieldtype": "Link", "label": "Travel Trip", "options": "ESS Trip", "read_only": 1},
]

EXPENSE_CLAIM_DETAIL_FIELDS = [
    {"fieldname": "ess_trip", "fieldtype": "Link", "label": "Trip", "options": "ESS Trip", "read_only": 1,
     "in_list_view": 0},
]


def make_custom_fields():
    keep = frappe.db.get_value("Custom Field", {"dt": "Employee", "fieldname": "ess_transport_mode"}, "options")
    create_custom_fields(
        {
            "Employee Checkin": _chain("Employee Checkin", CHECKIN_FIELDS),
            "Employee": _chain("Employee", EMPLOYEE_FIELDS),
            "Expense Claim": _chain("Expense Claim", EXPENSE_CLAIM_FIELDS),
            "Expense Claim Detail": _chain("Expense Claim Detail", EXPENSE_CLAIM_DETAIL_FIELDS),
        },
        update=True,
    )
    if keep:
        frappe.db.set_value("Custom Field", {"dt": "Employee", "fieldname": "ess_transport_mode"}, "options", keep)
