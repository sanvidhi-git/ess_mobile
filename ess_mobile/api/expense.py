"""Expense claims from the app.

One Expense Claim can hold any number of tracked trips (one km-based line each, linked to the
trip) plus ordinary expense lines (Food, Per Diem, ...). Drafts can be reopened, edited and
deleted by the employee until the approver acts on them.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from ess_mobile.api.common import current_employee, ensure_enabled, parse_list, save_base64_file, settings

MAX_ITEMS = 30
MAX_RECEIPTS = 10


# ================================================================ read
@frappe.whitelist(methods=["GET"])
def get_expense_types():
    return frappe.get_all("Expense Claim Type", pluck="name", order_by="name asc")


@frappe.whitelist(methods=["GET"])
def get_claims(limit: int = 30, start: int = 0):
    emp = current_employee()
    rows = frappe.get_all(
        "Expense Claim",
        filters={"employee": emp.name},
        fields=["name", "posting_date", "total_claimed_amount", "total_sanctioned_amount", "approval_status",
                "status", "docstatus", "ess_trip", "remark"],
        order_by="posting_date desc, creation desc",
        limit_start=cint(start),
        limit_page_length=min(cint(limit) or 30, 100),
    )
    names = [r.name for r in rows]
    counts = {}
    if names:
        for d in frappe.get_all("Expense Claim Detail", filters={"parent": ["in", names]},
                                fields=["parent", "ess_trip"]):
            c = counts.setdefault(d.parent, {"lines": 0, "trips": 0})
            c["lines"] += 1
            c["trips"] += 1 if d.ess_trip else 0
    for r in rows:
        r.update(counts.get(r.name, {"lines": 0, "trips": 0}))
        r["editable"] = cint(_editable(r))
    return rows


@frappe.whitelist(methods=["GET"])
def get_claim(name: str):
    emp = current_employee()
    doc = _own_claim(name, emp)
    files = frappe.get_all("File", filters={"attached_to_doctype": "Expense Claim", "attached_to_name": doc.name},
                           fields=["name", "file_name", "file_url"], order_by="creation asc")
    return {
        "name": doc.name,
        "posting_date": str(doc.posting_date),
        "approval_status": doc.approval_status,
        "status": doc.status,
        "docstatus": doc.docstatus,
        "editable": cint(_editable(doc)),
        "remark": doc.remark,
        "total_claimed_amount": flt(doc.total_claimed_amount),
        "total_sanctioned_amount": flt(doc.total_sanctioned_amount),
        "expense_approver": doc.expense_approver,
        "lines": [{
            "idx": r.idx, "expense_type": r.expense_type, "expense_date": str(r.expense_date),
            "description": r.description, "amount": flt(r.amount), "sanctioned_amount": flt(r.sanctioned_amount),
            "trip": r.get("ess_trip"),
        } for r in doc.expenses],
        "trips": [_trip_summary(t) for t in frappe.get_all(
            "ESS Trip", filters={"expense_claim": doc.name},
            fields=["name", "trip_date", "distance_km", "claimed_km", "personal_km", "transport_mode", "rate_per_km",
                    "odometer_km"], order_by="trip_date asc")],
        "attachments": files,
    }


@frappe.whitelist(methods=["GET"])
def get_claimable_trips(include_claim: str | None = None):
    """Finished, unclaimed trips at or above the minimum distance, with claim defaults for each.

    include_claim: when editing a draft, also return the trips already on that claim.
    """
    emp = current_employee()
    s = settings()
    filters = {"employee": emp.name, "status": ["!=", "Active"], "distance_km": [">", 0]}
    trips = frappe.get_all("ESS Trip", filters=filters, pluck="name", order_by="trip_date desc, start_time desc",
                           limit_page_length=100)
    out = []
    for name in trips:
        t = frappe.get_doc("ESS Trip", name)
        if t.expense_claim and t.expense_claim != include_claim:
            continue
        if flt(t.distance_km) < flt(s.min_claim_km):
            continue
        info = _claim_info(t, emp)
        if t.expense_claim:  # on the draft being edited: show what was claimed
            info.update({"in_claim": 1, "selected_mode": t.transport_mode, "selected_km": flt(t.claimed_km, 2),
                         "selected_personal_km": flt(t.personal_km, 2)})
        out.append(info)
    return out


@frappe.whitelist(methods=["GET"])
def travel_claim_info(trip: str):
    """Distances, odometer, modes and limits for one trip."""
    t, emp = _trip_and_employee(trip)
    return _claim_info(t, emp)


# ================================================================ write
@frappe.whitelist(methods=["POST"])
def submit_claim(trips=None, items=None, remark: str | None = None, name: str | None = None):
    """Create (or, with name, replace the lines of) a draft claim.

    trips: [{trip, transport_mode, claim_km, personal_km}]
    items: [{expense_type, expense_date, amount, description, attachments: [{filename, data}]}]
    """
    ensure_enabled()
    emp = current_employee(["ess_transport_mode"])
    trips, items = parse_list(trips), parse_list(items)
    if not trips and not items:
        frappe.throw(_("Add at least one trip or expense line."))
    if len(items) > MAX_ITEMS:
        frappe.throw(_("A claim can have at most {0} expense lines.").format(MAX_ITEMS))
    seen = set()
    for tr in trips:
        if tr.get("trip") in seen:
            frappe.throw(_("Trip {0} is listed twice.").format(tr.get("trip")))
        seen.add(tr.get("trip"))

    doc = _own_claim(name, emp) if name else None
    if doc and not _editable(doc):
        frappe.throw(_("Only draft claims that the approver hasn't acted on can be changed."))

    rows, trip_updates, photos = [], [], []
    for tr in trips:
        t = frappe.get_doc("ESS Trip", tr.get("trip"))
        if t.employee != emp.name:
            frappe.throw(_("Not your trip"), frappe.PermissionError)
        if t.expense_claim and (not doc or t.expense_claim != doc.name):
            frappe.throw(_("Trip {0} is already claimed in {1}").format(t.name, t.expense_claim))
        row, upd, urls = _travel_line(emp, t, tr.get("transport_mode"), tr.get("claim_km"), tr.get("personal_km"))
        rows.append(row)
        trip_updates.append((t.name, upd))
        photos.extend(urls)

    receipts = []
    for it in items:
        amount = flt(it.get("amount"), 2)
        etype = it.get("expense_type")
        if not etype or not frappe.db.exists("Expense Claim Type", etype):
            frappe.throw(_("Choose an expense type for every line."))
        if amount <= 0:
            frappe.throw(_("Every expense line needs an amount above zero ({0}).").format(etype))
        edate = getdate(it.get("expense_date") or nowdate())
        if edate > getdate(nowdate()):
            frappe.throw(_("Expense date can't be in the future ({0}).").format(etype))
        rows.append({"expense_date": edate, "expense_type": etype,
                     "description": (it.get("description") or etype)[:500],
                     "amount": amount, "sanctioned_amount": amount})
        receipts.extend(parse_list(it.get("attachments")))
    if len(receipts) > MAX_RECEIPTS:
        frappe.throw(_("Attach at most {0} receipts per claim.").format(MAX_RECEIPTS))

    if doc:
        _free_trips(doc.name)
        doc.set("expenses", [])
        for r in rows:
            doc.append("expenses", r)
        doc.remark = remark
        doc.ess_trip = trip_updates[0][0] if trip_updates else None
        doc.save(ignore_permissions=True)
    else:
        doc = _new_claim(emp, rows, remark=remark, trip=trip_updates[0][0] if trip_updates else None)

    for trip_name, upd in trip_updates:
        frappe.db.set_value("ESS Trip", trip_name, dict(upd, expense_claim=doc.name))
    existing = set(frappe.get_all("File", filters={"attached_to_doctype": "Expense Claim",
                                                   "attached_to_name": doc.name}, pluck="file_url"))
    for url in photos:
        if url not in existing:
            _attach_url(doc.name, url)
            existing.add(url)
    for a in receipts:
        save_base64_file(a.get("data"), a.get("filename") or "receipt.jpg", "Expense Claim", doc.name)

    return {"name": doc.name, "total": flt(doc.total_claimed_amount), "lines": len(doc.expenses),
            "trips": len(trip_updates), "approval_status": doc.approval_status}


@frappe.whitelist(methods=["POST"])
def delete_claim(name: str):
    emp = current_employee()
    doc = _own_claim(name, emp)
    if not _editable(doc):
        frappe.throw(_("Only draft claims that the approver hasn't acted on can be deleted."))
    frappe.delete_doc("Expense Claim", doc.name, ignore_permissions=True)  # on_trash frees the trips
    return {"ok": True}


@frappe.whitelist(methods=["POST"])
def remove_attachment(claim: str, file: str):
    emp = current_employee()
    doc = _own_claim(claim, emp)
    if not _editable(doc):
        frappe.throw(_("Only draft claims can be changed."))
    f = frappe.get_doc("File", file)
    if f.attached_to_doctype != "Expense Claim" or f.attached_to_name != doc.name:
        frappe.throw(_("Not an attachment of this claim"), frappe.PermissionError)
    frappe.delete_doc("File", f.name, ignore_permissions=True)
    return {"ok": True}


# ---- kept for older app versions and the HR desk button
@frappe.whitelist(methods=["POST"])
def create_claim(expense_type: str, expense_date: str, amount: float, description: str | None = None,
                 attachments=None):
    return submit_claim(items=[{"expense_type": expense_type, "expense_date": expense_date, "amount": amount,
                                "description": description, "attachments": parse_list(attachments)[:5]}],
                        remark=description)


@frappe.whitelist(methods=["POST"])
def create_travel_claim(trip: str, transport_mode: str | None = None, claim_km: float | None = None,
                        personal_km: float | None = None, description: str | None = None):
    ensure_enabled()
    t, emp = _trip_and_employee(trip)
    return make_travel_claim(emp, t, description, transport_mode=transport_mode, claim_km=claim_km,
                             personal_km=personal_km)


def make_travel_claim(emp, t, description: str | None = None, transport_mode: str | None = None,
                      claim_km: float | None = None, personal_km: float | None = None) -> dict:
    """Single-trip draft claim (HR desk button and older app versions)."""
    if t.expense_claim:
        frappe.throw(_("This trip is already claimed in {0}").format(t.expense_claim))
    row, upd, urls = _travel_line(emp, t, transport_mode, claim_km, personal_km)
    if description:
        row["description"] = f"{row['description']}. {description}"[:500]
    doc = _new_claim(emp, [row], remark=row["description"], trip=t.name)
    for url in urls:
        _attach_url(doc.name, url)
    frappe.db.set_value("ESS Trip", t.name, dict(upd, expense_claim=doc.name))
    return {"name": doc.name, "km": upd["claimed_km"], "amount": row["amount"], "mode": upd["transport_mode"],
            "rate": upd["rate_per_km"], "approval_status": doc.approval_status}


# ================================================================ helpers
def _editable(doc) -> bool:
    return cint(doc.get("docstatus")) == 0 and (doc.get("approval_status") or "Draft") == "Draft"


def _own_claim(name: str, emp):
    doc = frappe.get_doc("Expense Claim", name)
    if doc.employee != emp.name:
        frappe.throw(_("Not your claim"), frappe.PermissionError)
    return doc


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


def _travel_line(emp, t, transport_mode=None, claim_km=None, personal_km=None):
    """Validated Expense Claim line for one trip.

    Returns (row, trip_values, photo_urls). The claimed km may not exceed the tracked distance
    (plus the configured tolerance), nor the odometer distance minus personal km.
    """
    from ess_mobile.api.transport import employee_mode, get_mode

    s = settings()
    if t.status == "Active":
        frappe.throw(_("Check out first to finish trip {0}.").format(t.name))
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
    label = _("Trip of {0}").format(frappe.format(t.trip_date, {"fieldtype": "Date"}))
    personal = max(0.0, flt(personal_km))
    if odo_km is not None and personal > odo_km:
        frappe.throw(_("{0}: personal km ({1}) can't be more than the odometer distance ({2} km).")
                     .format(label, personal, odo_km))
    if claim_km in (None, ""):
        claim_km = min((odo_km - personal) if odo_km is not None else tracked, cap)
    km = flt(claim_km, 2)
    if km <= 0:
        frappe.throw(_("{0}: enter the distance to claim.").format(label))
    if km > cap + 0.005:
        frappe.throw(_("{0}: you can claim at most {1} km; live tracking recorded {2} km.")
                     .format(label, cap, tracked), title=_("Distance Too High"))
    if odo_km is not None and km > flt(odo_km - personal, 2) + 0.005:
        frappe.throw(_("{0}: {1} km is more than the odometer distance ({2} km) minus personal km ({3}).")
                     .format(label, km, odo_km, personal), title=_("Distance Too High"))
    if km < flt(s.min_claim_km):
        frappe.throw(_("{0}: {1} km is below the minimum {2} km for a claim.").format(label, km, s.min_claim_km))

    amount = flt(km * rate, 2)
    mode_name = mode["mode"] if mode else _("Travel")
    parts = [_("{0}: {1} km × {2}/km").format(mode_name, km, rate), _("tracked {0} km").format(tracked)]
    if odo_km is not None:
        parts.append(_("odometer {0} to {1} = {2} km").format(flt(t.odometer_start, 1), flt(t.odometer_end, 1), odo_km))
        if personal:
            parts.append(_("personal {0} km deducted").format(personal))
    if default and mode and mode["mode"] != default["mode"]:
        parts.append(_("employee's usual mode is {0}").format(default["mode"]))
    parts.append(_("Trip {0}").format(t.name))
    row = {"expense_date": t.trip_date, "expense_type": claim_type, "description": "; ".join(parts)[:500],
           "amount": amount, "sanctioned_amount": amount, "ess_trip": t.name}
    upd = {"claimed_km": km, "personal_km": personal, "transport_mode": mode_name, "rate_per_km": rate}
    urls = [u for u in (t.get("odometer_start_photo"), t.get("odometer_end_photo")) if u]
    return row, upd, urls


def _trip_summary(t) -> dict:
    return {"trip": t.name, "trip_date": str(t.trip_date), "tracked_km": flt(t.distance_km, 2),
            "claimed_km": flt(t.claimed_km, 2), "personal_km": flt(t.personal_km, 2),
            "transport_mode": t.transport_mode, "rate_per_km": flt(t.rate_per_km),
            "odometer_km": flt(t.odometer_km, 1) or None}


def _attach_url(claim: str, url: str):
    """Attach an existing file (odometer photo) to the claim as evidence."""
    frappe.get_doc({"doctype": "File", "file_url": url, "is_private": 1, "attached_to_doctype": "Expense Claim",
                    "attached_to_name": claim, "file_name": url.rsplit("/", 1)[-1]}).insert(ignore_permissions=True)


def _free_trips(claim: str):
    for name in frappe.get_all("ESS Trip", filters={"expense_claim": claim}, pluck="name"):
        frappe.db.set_value("ESS Trip", name, {"expense_claim": None, "claimed_km": 0, "personal_km": 0})


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
    """doc_event: free every trip on a claim that is deleted or cancelled."""
    _free_trips(doc.name)
