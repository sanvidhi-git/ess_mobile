"""Expense claims, including km-based travel claims from tracked trips."""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from ess_mobile.api.common import current_employee, ensure_enabled, parse_list, save_base64_file, settings


@frappe.whitelist(methods=["GET"])
def get_expense_types():
    return frappe.get_all("Expense Claim Type", pluck="name", order_by="name asc")


@frappe.whitelist(methods=["GET"])
def get_claims(limit: int = 30, start: int = 0):
    emp = current_employee()
    return frappe.get_all(
        "Expense Claim",
        filters={"employee": emp.name},
        fields=["name", "posting_date", "total_claimed_amount", "total_sanctioned_amount", "approval_status",
                "status", "docstatus", "ess_trip", "remark"],
        order_by="posting_date desc, creation desc",
        limit_start=cint(start),
        limit_page_length=min(cint(limit) or 30, 100),
    )


@frappe.whitelist(methods=["POST"])
def create_claim(expense_type: str, expense_date: str, amount: float, description: str | None = None,
                 attachments=None):
    """attachments: [{"filename": "bill.jpg", "data": "<base64>"}]"""
    ensure_enabled()
    emp = current_employee()
    if flt(amount) <= 0:
        frappe.throw(_("Amount must be greater than zero"))
    if getdate(expense_date) > getdate(nowdate()):
        frappe.throw(_("Expense date cannot be in the future"))
    doc = _new_claim(emp, [{
        "expense_date": expense_date, "expense_type": expense_type,
        "description": description or expense_type, "amount": flt(amount), "sanctioned_amount": flt(amount),
    }], remark=description)
    for a in parse_list(attachments)[:5]:
        save_base64_file(a.get("data"), a.get("filename") or "receipt.jpg", "Expense Claim", doc.name)
    return {"name": doc.name, "total": flt(doc.total_claimed_amount), "approval_status": doc.approval_status}


@frappe.whitelist(methods=["POST"])
def create_travel_claim(trip: str, description: str | None = None):
    ensure_enabled()
    emp = current_employee()
    t = frappe.get_doc("ESS Trip", trip)
    if t.employee != emp.name:
        frappe.throw(_("Not your trip"), frappe.PermissionError)
    return make_travel_claim(emp, t, description)


def make_travel_claim(emp, t, description: str | None = None) -> dict:
    """Draft Expense Claim for a finished trip at the configured rate per km."""
    s = settings()
    if not (s.travel_expense_type and flt(s.rate_per_km)):
        frappe.throw(_("Travel claims are not configured. Set Travel Expense Claim Type and Rate per km in ESS Settings."))
    if t.status == "Active":
        frappe.throw(_("Check out first to finish this trip."))
    if t.expense_claim:
        frappe.throw(_("This trip is already claimed in {0}").format(t.expense_claim))
    km = flt(t.distance_km, 2)
    if s.max_claim_km_per_trip and km > flt(s.max_claim_km_per_trip):
        km = flt(s.max_claim_km_per_trip, 2)
    if km < flt(s.min_claim_km):
        frappe.throw(_("Distance {0} km is below the minimum {1} km for a claim.").format(km, s.min_claim_km))
    amount = flt(km * flt(s.rate_per_km), 2)
    text = _("Travel {0} km on {1} @ {2}/km (Trip {3})").format(km, t.trip_date, flt(s.rate_per_km), t.name)
    if description:
        text = f"{text} - {description}"
    doc = _new_claim(emp, [{
        "expense_date": t.trip_date, "expense_type": s.travel_expense_type, "description": text,
        "amount": amount, "sanctioned_amount": amount,
    }], remark=text, trip=t.name)
    t.db_set({"expense_claim": doc.name, "claimed_km": km})
    return {"name": doc.name, "km": km, "amount": amount, "approval_status": doc.approval_status}


def _new_claim(emp, rows, remark=None, trip=None):
    company = emp.company
    doc = frappe.new_doc("Expense Claim")
    doc.update({
        "employee": emp.name,
        "company": company,
        "posting_date": nowdate(),
        "expense_approver": emp.expense_approver,
        "approval_status": "Draft",
        "remark": remark,
        "ess_trip": trip,
    })
    if doc.meta.has_field("payable_account") and not doc.payable_account:
        doc.payable_account = frappe.get_cached_value("Company", company, "default_expense_claim_payable_account")
    if doc.meta.has_field("cost_center") and not doc.cost_center:
        doc.cost_center = frappe.get_cached_value("Company", company, "cost_center")
    for r in rows:
        doc.append("expenses", r)
    doc.insert(ignore_permissions=True)
    return doc


def release_trip(doc, method=None):
    """doc_event: free the trip when its travel claim is deleted or cancelled."""
    if doc.get("ess_trip"):
        frappe.db.set_value("ESS Trip", doc.ess_trip, {"expense_claim": None, "claimed_km": 0})
