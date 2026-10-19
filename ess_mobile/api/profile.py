"""Employee profile for the app's Profile screen."""

import frappe
from frappe.utils import cint

from ess_mobile.api.common import current_employee

PROFILE_FIELDS = [
    "employee_name", "first_name", "gender", "date_of_birth", "date_of_joining", "company", "branch",
    "department", "designation", "grade", "employment_type", "reports_to", "cell_number", "company_email",
    "personal_email", "current_address", "emergency_phone_number", "person_to_be_contacted", "image",
    "holiday_list", "leave_approver", "expense_approver", "bank_name", "attendance_device_id",
]


@frappe.whitelist(methods=["GET"])
def get_profile():
    emp = current_employee()
    meta = frappe.get_meta("Employee")
    fields = [f for f in PROFILE_FIELDS if meta.has_field(f)]
    data = frappe.db.get_value("Employee", emp.name, fields, as_dict=True) or {}
    data["employee"] = emp.name
    if data.get("reports_to"):
        data["reports_to_name"] = frappe.db.get_value("Employee", data["reports_to"], "employee_name")
    for key in ("date_of_birth", "date_of_joining"):
        if data.get(key):
            data[key] = str(data[key])
    device = frappe.db.get_value("ESS Device", {"employee": emp.name, "is_active": 1},
                                 ["device_model", "registered_on"], as_dict=True)
    data["device"] = {"model": device.device_model, "registered_on": str(device.registered_on)} if device else None
    data["geofence_exempt"] = cint(emp.ess_geofence_exempt)
    return data
