# Copyright (c) 2026, Sanvidhi Tech Pvt. Ltd. and contributors

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class ESSSettings(Document):
    def validate(self):
        seen = set()
        for row in self.transport_modes or []:
            row.mode = (row.mode or "").strip()
            key = row.mode.lower()
            if key in seen:
                frappe.throw(_("Mode of transport {0} is listed twice").format(row.mode))
            seen.add(key)
            if flt(row.rate_per_km) < 0:
                frappe.throw(_("Rate per km cannot be negative ({0})").format(row.mode))
        enabled = [r.mode for r in self.transport_modes or [] if r.enabled]
        if self.default_transport_mode and self.default_transport_mode not in enabled:
            frappe.throw(_("Default Mode of Transport must be one of the enabled modes: {0}").format(", ".join(enabled) or "-"))
        if flt(self.claim_tolerance_pct) < 0:
            self.claim_tolerance_pct = 0

    def on_update(self):
        from ess_mobile.api.transport import sync_employee_mode_options

        sync_employee_mode_options(self)
