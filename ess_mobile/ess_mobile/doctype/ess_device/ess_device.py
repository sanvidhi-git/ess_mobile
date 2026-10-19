# Copyright (c) 2026, Sanvidhi Tech Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ESSDevice(Document):
    def validate(self):
        if self.is_active:
            other = frappe.db.exists(
                "ESS Device",
                {"employee": self.employee, "is_active": 1, "name": ("!=", self.name)},
            )
            if other:
                frappe.throw(_("Employee {0} already has an active device ({1}). Deactivate it first.").format(self.employee, other))

