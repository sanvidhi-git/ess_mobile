"""Salary slip list and PDF download."""

import frappe
from frappe import _
from frappe.utils import cint, flt

from ess_mobile.api.common import current_employee, settings


@frappe.whitelist(methods=["GET"])
def get_salary_slips(limit: int = 24, start: int = 0):
    emp = current_employee()
    return frappe.get_all(
        "Salary Slip",
        filters={"employee": emp.name, "docstatus": 1},
        fields=["name", "start_date", "end_date", "posting_date", "gross_pay", "total_deduction", "net_pay",
                "currency", "payment_days", "total_working_days"],
        order_by="start_date desc",
        limit_start=cint(start),
        limit_page_length=min(cint(limit) or 24, 60),
    )


@frappe.whitelist(methods=["GET"])
def get_salary_slip(name: str):
    doc = _own_slip(name)
    return {
        "name": doc.name,
        "start_date": str(doc.start_date),
        "end_date": str(doc.end_date),
        "currency": doc.currency,
        "gross_pay": flt(doc.gross_pay),
        "total_deduction": flt(doc.total_deduction),
        "net_pay": flt(doc.net_pay),
        "payment_days": flt(doc.payment_days),
        "total_working_days": flt(doc.total_working_days),
        "earnings": [{"component": r.salary_component, "amount": flt(r.amount)} for r in doc.earnings],
        "deductions": [{"component": r.salary_component, "amount": flt(r.amount)} for r in doc.deductions],
    }


@frappe.whitelist(methods=["GET"])
def download_salary_slip(name: str):
    doc = _own_slip(name)
    fmt = settings().salary_slip_print_format or None
    # ownership verified above; employees often lack print permission on Salary Slip
    frappe.flags.ignore_print_permissions = True
    try:
        pdf = frappe.get_print("Salary Slip", doc.name, print_format=fmt, doc=doc, as_pdf=True)
    finally:
        frappe.flags.ignore_print_permissions = False
    frappe.local.response.filename = f"{doc.name}.pdf"
    frappe.local.response.filecontent = pdf
    frappe.local.response.type = "pdf"


def _own_slip(name: str):
    emp = current_employee()
    doc = frappe.get_doc("Salary Slip", name)
    if doc.employee != emp.name or doc.docstatus != 1:
        frappe.throw(_("Salary slip not found"), frappe.DoesNotExistError)
    return doc
