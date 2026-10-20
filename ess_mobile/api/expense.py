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


@frappe.whitelist(methods=["GET"])
def travel_claim_info(trip: str):
    """Everything the claim screen needs for one trip: distances, odometer, modes, limits."""
    t, emp = _trip_and_employee(trip)
    return _claim_info(t, emp)


@frappe.whitelist(methods=["POST"])
def create_travel_claim(trip: str, transport_mode: str | None = None, claim_km: float | None = None,
                        personal_km: float | None = None, description: str | None = None):
    ensure_enabled()
    t, emp = _trip_and_employee(trip)
    return make_travel_claim(emp, t, description, transport_mode=transport_mode, claim_km=claim_km,
                             personal_km=personal_km)


def _trip_and_employee(trip: str):
    """The trip plus its employee. Employees see only their own trips; HR sees any."""
    from ess_mobile.api.admin import check_app_permission

    t = frappe.get_doc("ESS Trip", trip)
    me = frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "name")
    if t.employee != me and not check_app_permission():
        frappe.throw(_("Not your trip"), frappe.PermissionError)
    emp = frappe.db.get_value("Employee", t.employee, ["name", "company", "expense_approver", "ess_transport_mode"],
                              as_dict=True)
    return t, emp


def _limits(t, s):
    tracked = flt(t.distance_km, 2)
    tol = max(0.0, flt(s.get("claim_tolerance_pct")))
    cap = flt(tracked * (1 + tol / 100.0), 2)
    if s.max_claim_km_per_trip and flt(s.max_claim_km_per_trip) < cap:
        cap = flt(s.max_claim_km_per_trip, 2)
    odo_km = flt(t.odometer_km, 1) if t.get("odometer_end") and t.get("odometer_start") else None
    return tracked, cap, odo_km


def _claim_info(t, emp) -> dict:
    from ess_mobile.api.transport import employee_mode, modes

    s = settings()
    tracked, cap, odo_km = _limits(t, s)
    suggested = min(odo_km, cap) if odo_km is not None else min(tracked, cap)
    default = employee_mode(emp, s)
    return {
        "trip": t.name,
        "trip_date": str(t.trip_date),
        "status": t.status,
        "start_time": str(t.start_time) if t.start_time else None,
        "end_time": str(t.end_time) if t.end_time else None,
        "tracked_km": tracked,
        "max_claim_km": cap,
        "tolerance_pct": flt(s.get("claim_tolerance_pct")),
        "min_claim_km": flt(s.min_claim_km),
        "odometer_start": flt(t.odometer_start, 1) if t.get("odometer_start") else None,
        "odometer_end": flt(t.odometer_end, 1) if t.get("odometer_end") else None,
        "odometer_km": odo_km,
        "odometer_start_photo": t.get("odometer_start_photo"),
        "odometer_end_photo": t.get("odometer_end_photo"),
        "suggested_km": flt(max(0, suggested), 2),
        "default_mode": default["mode"] if default else None,
        "modes": [{"mode": m["mode"], "rate_per_km": m["rate_per_km"], "uses_odometer": m["uses_odometer"]}
                  for m in modes(s)],
        "expense_claim": t.expense_claim,
    }


def make_travel_claim(emp, t, description: str | None = None, transport_mode: str | None = None,
                      claim_km: float | None = None, personal_km: float | None = None) -> dict:
    """Draft Expense Claim for a finished trip.

    claim_km is what the employee claims; it may not exceed the distance recorded by live
    tracking (plus the configured tolerance), nor the odometer distance minus personal km.
    """
    from ess_mobile.api.transport import employee_mode, get_mode

    s = settings()
    if t.status == "Active":
        frappe.throw(_("Check out first to finish this trip."))
    if t.expense_claim:
        frappe.throw(_("This trip is already claimed in {0}").format(t.expense_claim))

    default = employee_mode(emp, s)
    mode = get_mode(transport_mode, s) if transport_mode else default
    if transport_mode and not mode:
        frappe.throw(_("{0} is not an enabled mode of transport.").format(transport_mode))
    rate = flt(mode["rate_per_km"]) if mode else flt(s.rate_per_km)
    claim_type = (mode or {}).get("expense_claim_type") or s.travel_expense_type
    if not (claim_type and rate):
        frappe.throw(_("Travel claims are not configured. Set the modes of transport, their rates and the "
                       "Travel Expense Claim Type in ESS Settings."))

    tracked, cap, odo_km = _limits(t, s)
    personal = max(0.0, flt(personal_km))
    if odo_km is not None and personal > odo_km:
        frappe.throw(_("Personal km ({0}) can't be more than the odometer distance ({1} km).").format(personal, odo_km))
    if claim_km in (None, ""):
        claim_km = (odo_km - personal) if odo_km is not None else tracked
        claim_km = min(claim_km, cap)
    km = flt(claim_km, 2)
    if km <= 0:
        frappe.throw(_("Enter the distance to claim."))
    if km > cap + 0.005:
        frappe.throw(_("You can claim at most {0} km for this trip: live tracking recorded {1} km.")
                     .format(cap, tracked), title=_("Distance Too High"))
    if odo_km is not None and km > flt(odo_km - personal, 2) + 0.005:
        frappe.throw(_("Claimed {0} km is more than the odometer distance ({1} km) minus personal km ({2}).")
                     .format(km, odo_km, personal), title=_("Distance Too High"))
    if km < flt(s.min_claim_km):
        frappe.throw(_("Distance {0} km is below the minimum {1} km for a claim.").format(km, s.min_claim_km))

    amount = flt(km * rate, 2)
    mode_name = mode["mode"] if mode else _("Travel")
    parts = [_("{0}: {1} km × {2}/km").format(mode_name, km, rate), _("tracked {0} km").format(tracked)]
    if odo_km is not None:
        parts.append(_("odometer {0} → {1} = {2} km").format(flt(t.odometer_start, 1), flt(t.odometer_end, 1), odo_km))
        if personal:
            parts.append(_("personal {0} km deducted").format(personal))
    if default and mode and mode["mode"] != default["mode"]:
        parts.append(_("employee's usual mode is {0}").format(default["mode"]))
    parts.append(_("Trip {0}").format(t.name))
    text = "; ".join(parts)
    if description:
        text = f"{text}. {description}"

    doc = _new_claim(emp, [{
        "expense_date": t.trip_date, "expense_type": claim_type, "description": text,
        "amount": amount, "sanctioned_amount": amount,
    }], remark=text, trip=t.name)

    # odometer photos go with the claim as evidence for the approver
    for field in ("odometer_start_photo", "odometer_end_photo"):
        url = t.get(field)
        if url:
            frappe.get_doc({"doctype": "File", "file_url": url, "is_private": 1, "attached_to_doctype": "Expense Claim",
                            "attached_to_name": doc.name, "file_name": url.rsplit("/", 1)[-1]}).insert(ignore_permissions=True)

    t.db_set({"expense_claim": doc.name, "claimed_km": km, "personal_km": personal,
              "transport_mode": mode_name, "rate_per_km": rate})
    return {"name": doc.name, "km": km, "amount": amount, "mode": mode_name, "rate": rate,
            "approval_status": doc.approval_status}


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
