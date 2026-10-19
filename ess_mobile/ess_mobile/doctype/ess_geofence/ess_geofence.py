# Copyright (c) 2026, Sanvidhi Tech Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document


class ESSGeofence(Document):
    def validate(self):
        self.sync_from_map()
        if not (-90 <= (self.latitude or 0) <= 90) or not (-180 <= (self.longitude or 0) <= 180):
            frappe.throw(_("Latitude / Longitude are out of range"))
        if (self.radius_m or 0) <= 0:
            frappe.throw(_("Radius must be greater than zero"))
        self.location_map = json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"point_type": "circle", "radius": self.radius_m},
                "geometry": {"type": "Point", "coordinates": [self.longitude, self.latitude]},
            }],
        })

    def sync_from_map(self):
        """If HR moved the marker on the map, take the new point."""
        if not self.location_map or not self.has_value_changed("location_map"):
            return
        try:
            for feat in json.loads(self.location_map).get("features", []):
                geom = feat.get("geometry") or {}
                if geom.get("type") == "Point":
                    self.longitude, self.latitude = geom["coordinates"][:2]
                    break
        except (ValueError, KeyError, TypeError):
            pass

