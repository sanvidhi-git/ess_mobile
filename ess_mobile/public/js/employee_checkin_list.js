// ESS Mobile: flag mobile punches in the Employee Checkin list.
// Merges with any listview settings HRMS already defines.

frappe.listview_settings["Employee Checkin"] = Object.assign(frappe.listview_settings["Employee Checkin"] || {}, {
	add_fields: [
		...((frappe.listview_settings["Employee Checkin"] || {}).add_fields || []),
		"ess_device", "ess_geofence", "ess_within_geofence", "log_type",
	],
	get_indicator(doc) {
		if (doc.ess_device) {
			if (doc.ess_geofence && !doc.ess_within_geofence) {
				return [__("Mobile · outside"), "orange", "ess_within_geofence,=,0"];
			}
			return [__("Mobile · {0}", [doc.log_type]), doc.log_type === "IN" ? "green" : "blue", "ess_device,is,set"];
		}
		return [doc.log_type, doc.log_type === "IN" ? "green" : "gray", `log_type,=,${doc.log_type}`];
	},
});
