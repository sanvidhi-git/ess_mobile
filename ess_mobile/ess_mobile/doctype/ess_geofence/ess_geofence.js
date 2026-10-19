// Copyright (c) 2026, Sanvidhi Tech Pvt. Ltd. and contributors

frappe.ui.form.on("ESS Geofence", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Check-ins Here"), () =>
				frappe.set_route("List", "Employee Checkin", { ess_geofence: frm.doc.name }));
		}
		if (frm.is_new() && navigator.geolocation) {
			frm.add_custom_button(__("Use My Current Location"), () =>
				navigator.geolocation.getCurrentPosition(
					(p) => {
						frm.set_value("latitude", p.coords.latitude);
						frm.set_value("longitude", p.coords.longitude);
					},
					() => frappe.msgprint(__("Could not read your location from the browser."))
				));
		}
	},
});
