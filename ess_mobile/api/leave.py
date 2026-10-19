"""Leave balance, applications and withdrawal."""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from ess_mobile.api.common import current_employee, ensure_enabled


@frappe.whitelist(methods=["GET"])
def get_balance():
    from hrms.hr.doctype.leave_application.leave_application import get_leave_details

    emp = current_employee()
    details = get_leave_details(emp.name, nowdate())
    alloc = details.get("leave_allocation") or {}
    balance = [
        {
            "leave_type": lt,
            "total": flt(v.get("total_leaves")),
            "taken": flt(v.get("leaves_taken")),
            "pending": flt(v.get("leaves_pending_approval")),
            "expired": flt(v.get("expired_leaves")),
            "remaining": flt(v.get("remaining_leaves")),
        }
        for lt, v in alloc.items()
    ]
    lwp = [row[0] if isinstance(row, (list, tuple)) else row for row in (details.get("lwps") or [])]
    return {"balance": balance, "leave_without_pay": lwp, "leave_approver": details.get("leave_approver")}


@frappe.whitelist(methods=["GET"])
def get_leave_days(leave_type: str, from_date: str, to_date: str, half_day: int = 0,
                   half_day_date: str | None = None):
    from hrms.hr.doctype.leave_application.leave_application import get_number_of_leave_days

    emp = current_employee()
    return flt(get_number_of_leave_days(emp.name, leave_type, from_date, to_date,
                                        cint(half_day) or None, half_day_date or None))


@frappe.whitelist(methods=["GET"])
def get_applications(limit: int = 30, start: int = 0):
    emp = current_employee()
    return frappe.get_all(
        "Leave Application",
        filters={"employee": emp.name},
        fields=["name", "leave_type", "from_date", "to_date", "total_leave_days", "half_day", "status",
                "docstatus", "description", "leave_approver_name", "posting_date"],
        order_by="from_date desc",
        limit_start=cint(start),
        limit_page_length=min(cint(limit) or 30, 100),
    )


@frappe.whitelist(methods=["POST"])
def apply(leave_type: str, from_date: str, to_date: str, half_day: int = 0,
          half_day_date: str | None = None, reason: str | None = None):
    ensure_enabled()
    emp = current_employee()
    if getdate(to_date) < getdate(from_date):
        frappe.throw(_("To date cannot be before from date"))
    approver = emp.leave_approver
    if not approver:
        try:
            from hrms.hr.doctype.leave_application.leave_application import get_leave_approver

            approver = get_leave_approver(emp.name)
        except Exception:
            approver = None
    doc = frappe.get_doc({
        "doctype": "Leave Application",
        "employee": emp.name,
        "company": emp.company,
        "leave_type": leave_type,
        "from_date": from_date,
        "to_date": to_date,
        "half_day": cint(half_day),
        "half_day_date": half_day_date if cint(half_day) else None,
        "description": reason,
        "leave_approver": approver,
        "posting_date": nowdate(),
        "status": "Open",
    })
    doc.insert(ignore_permissions=True)
    return {"name": doc.name, "total_leave_days": flt(doc.total_leave_days), "status": doc.status,
            "leave_approver": doc.leave_approver}


@frappe.whitelist(methods=["POST"])
def withdraw(name: str):
    """Delete an application that the approver has not acted on yet."""
    emp = current_employee()
    doc = frappe.get_doc("Leave Application", name)
    if doc.employee != emp.name:
        frappe.throw(_("Not your leave application"), frappe.PermissionError)
    if doc.docstatus != 0 or doc.status != "Open":
        frappe.throw(_("Only open, unapproved applications can be withdrawn. Ask your approver to cancel it."))
    frappe.delete_doc("Leave Application", name, ignore_permissions=True)
    return {"ok": True}
