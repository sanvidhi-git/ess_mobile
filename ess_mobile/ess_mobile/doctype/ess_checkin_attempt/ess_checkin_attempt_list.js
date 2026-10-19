frappe.listview_settings["ESS Checkin Attempt"] = {
	add_fields: ["reason"],
	get_indicator(doc) {
		const red = ["Mock Location", "Rooted Device", "Unregistered Device", "Face Check Failed"];
		return [__(doc.reason), red.includes(doc.reason) ? "red" : "orange", `reason,=,${doc.reason}`];
	},
};
