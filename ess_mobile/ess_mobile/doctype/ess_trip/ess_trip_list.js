frappe.listview_settings["ESS Trip"] = {
	add_fields: ["status", "expense_claim", "distance_km"],
	get_indicator(doc) {
		if (doc.status === "Active") return [__("Active"), "blue", "status,=,Active"];
		if (doc.expense_claim) return [__("Claimed"), "green", "expense_claim,is,set"];
		if (doc.status === "Auto Closed") return [__("Auto Closed"), "orange", "status,=,Auto Closed"];
		return [__("Completed"), "gray", "status,=,Completed"];
	},
};
