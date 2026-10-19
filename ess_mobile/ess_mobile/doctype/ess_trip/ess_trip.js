// Copyright (c) 2026, Sanvidhi Tech Pvt. Ltd. and contributors

frappe.ui.form.on("ESS Trip", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.dashboard.add_indicator(__("{0} km", [format_number(frm.doc.distance_km || 0, null, 2)]), "purple");
		frm.dashboard.add_indicator(__("{0} of {1} GPS points used", [frm.doc.accepted_pings || 0, frm.doc.total_pings || 0]),
			"gray");

		frm.add_custom_button(__("Recompute Distance"), () =>
			frappe.call({
				method: "ess_mobile.api.admin.recompute_trip",
				args: { trip: frm.doc.name },
				freeze: true,
				callback: () => frm.reload_doc(),
			}), __("Actions"));

		if (frm.doc.status === "Active") {
			frm.add_custom_button(__("Close Trip"), () =>
				frappe.confirm(__("Close this trip at the last received GPS point?"), () =>
					frappe.call({
						method: "ess_mobile.api.admin.close_trip",
						args: { trip: frm.doc.name },
						freeze: true,
						callback: () => frm.reload_doc(),
					})), __("Actions"));
		}

		if (frm.doc.status !== "Active" && !frm.doc.expense_claim && frm.doc.distance_km > 0) {
			frm.add_custom_button(__("Create Travel Claim"), () => {
				frappe.prompt(
					[{ fieldname: "description", fieldtype: "Data", label: __("Purpose of visit") }],
					(v) => frappe.call({
						method: "ess_mobile.api.admin.create_travel_claim",
						args: { trip: frm.doc.name, description: v.description },
						freeze: true,
						callback: ({ message }) => {
							frappe.show_alert({
								message: __("Expense Claim {0} created for {1} km", [message.name, message.km]),
								indicator: "green",
							});
							frm.reload_doc();
						},
					}),
					__("Create Travel Claim"), __("Create"));
			}, __("Actions"));
		}

		frm.add_custom_button(__("Live Map"), () => frappe.set_route("ess-live-map"));
	},
});
