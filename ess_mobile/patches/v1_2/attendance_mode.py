"""Replace the old tracking switches (ESS Settings enable_tracking / track_all_employees and the
Employee 'Enable Travel Tracking' checkbox) with the explicit Attendance Mode, keeping behaviour."""

import frappe
from frappe.utils import cint

from ess_mobile.setup.custom_fields import make_custom_fields


def execute():
    make_custom_fields()  # ensure Employee.ess_attendance_mode exists before copying into it

    old = dict(frappe.db.sql(
        """select field, value from `tabSingles`
           where doctype='ESS Settings' and field in ('enable_tracking', 'track_all_employees')"""))
    enabled, track_all = cint(old.get("enable_tracking")), cint(old.get("track_all_employees"))

    default = "Live Tracking" if (enabled and track_all) else "Check-in Only"
    frappe.db.set_single_value("ESS Settings", "default_attendance_mode", default)

    if enabled and not track_all and frappe.db.has_column("Employee", "ess_tracking_enabled"):
        frappe.db.sql("""update `tabEmployee` set ess_attendance_mode='Live Tracking'
                         where ess_tracking_enabled=1""")

    if frappe.db.exists("Custom Field", "Employee-ess_tracking_enabled"):
        frappe.delete_doc("Custom Field", "Employee-ess_tracking_enabled", ignore_permissions=True)
    frappe.db.sql("delete from `tabSingles` where doctype='ESS Settings' and field in ('enable_tracking', 'track_all_employees')")
