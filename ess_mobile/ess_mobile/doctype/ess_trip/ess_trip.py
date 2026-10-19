# Copyright (c) 2026, Sanvidhi Tech Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ESSTrip(Document):
    def recompute(self, save=True):
        from ess_mobile.api.tracking import recompute_trip

        recompute_trip(self, save=save)

