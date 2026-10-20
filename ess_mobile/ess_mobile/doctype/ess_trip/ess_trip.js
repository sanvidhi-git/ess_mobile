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
				frappe.call({
					method: "ess_mobile.api.expense.travel_claim_info",
					args: { trip: frm.doc.name },
					callback: ({ message: info }) => {
						const rates = Object.fromEntries(info.modes.map((m) => [m.mode, m.rate_per_km]));
						const d = new frappe.ui.Dialog({
							title: __("Create Travel Claim"),
							fields: [
								{ fieldname: "transport_mode", fieldtype: "Select", label: __("Mode of Transport"),
									options: info.modes.map((m) => m.mode), default: info.default_mode, reqd: 1,
									description: __("Employee's usual mode: {0}", [info.default_mode || "-"]) },
								{ fieldname: "personal_km", fieldtype: "Float", label: __("Personal km to deduct"),
									hidden: info.odometer_km == null, default: 0 },
								{ fieldname: "claim_km", fieldtype: "Float", label: __("Distance to claim (km)"), reqd: 1,
									default: info.suggested_km,
									description: __("Tracked {0} km · max {1} km{2}", [info.tracked_km, info.max_claim_km,
										info.odometer_km != null ? __(" · odometer {0} km", [info.odometer_km]) : ""]) },
								{ fieldname: "description", fieldtype: "Data", label: __("Purpose of visit") },
								{ fieldname: "amount_html", fieldtype: "HTML" },
							],
							primary_action_label: __("Create"),
							primary_action: (v) => frappe.call({
								method: "ess_mobile.api.admin.create_travel_claim",
								args: { trip: frm.doc.name, ...v },
								freeze: true,
								callback: ({ message }) => {
									d.hide();
									frappe.show_alert({
										message: __("Expense Claim {0}: {1} km, {2}", [message.name, message.km,
											format_currency(message.amount)]),
										indicator: "green",
									});
									frm.reload_doc();
								},
							}),
						});
						const update = () => {
							const v = d.get_values(true);
							if (info.odometer_km != null) {
								const max = Math.min(info.max_claim_km, info.odometer_km - (v.personal_km || 0));
								if (v.claim_km > max) d.set_value("claim_km", Math.max(0, Math.round(max * 100) / 100));
							}
							const rate = rates[v.transport_mode] || 0;
							d.fields_dict.amount_html.$wrapper.html(`<div class="text-muted">${__("Amount")}:
								<b>${format_currency((v.claim_km || 0) * rate)}</b> (${v.claim_km || 0} km × ${format_currency(rate)})</div>`);
						};
						["transport_mode", "personal_km", "claim_km"].forEach((f) => d.fields_dict[f].$input.on("change", update));
						d.show();
						update();
					},
				});
			}, __("Actions"));
		}

		frm.add_custom_button(__("Live Map"), () => frappe.set_route("ess-live-map"));
	},
});
