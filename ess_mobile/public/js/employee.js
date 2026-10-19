// ESS Mobile: device reset and a mobile-app summary on the Employee form.

frappe.ui.form.on("Employee", {
	refresh(frm) {
		if (frm.is_new() || !frappe.user.has_role(["HR Manager", "HR User", "System Manager"])) return;

		frappe.call({
			method: "ess_mobile.api.admin.employee_summary",
			args: { employee: frm.doc.name },
			callback: ({ message: s }) => {
				if (!s) return;
				const device = s.device
					? __("Phone: {0} (app {1}), last seen {2}", [
						frappe.utils.escape_html(s.device.device_model || "-"),
						frappe.utils.escape_html(s.device.app_version || "-"),
						s.device.last_seen ? frappe.datetime.comment_when(s.device.last_seen) : "-",
					])
					: __("No phone registered");
				frm.dashboard.add_comment(
					`<b>${__("ESS Mobile")}</b> · ${__("Mode")}: <b>${__(s.attendance_mode)}</b>${s.mode_is_default ? ` (${__("company default")})` : ""} · ${device} · ${__("This month")}: ${s.checkins_this_month} ${__("check-ins")},
					${s.km_this_month} km, <span class="${s.rejected_this_month ? "text-danger" : ""}">${s.rejected_this_month} ${__("rejected")}</span>`,
					s.rejected_this_month ? "orange" : "blue", true);

				if (s.device) {
					frm.add_custom_button(__("Reset Mobile Device"), () => {
						frappe.confirm(
							__("Sign {0} out of the app on {1} and allow a new phone to register?",
								[frappe.utils.escape_html(frm.doc.employee_name), frappe.utils.escape_html(s.device.device_model || __("the current phone"))]),
							() => frappe.call({
								method: "ess_mobile.api.admin.reset_device",
								args: { employee: frm.doc.name },
								freeze: true,
								callback: () => {
									frappe.show_alert({ message: __("Device reset"), indicator: "green" });
									frm.reload_doc();
								},
							})
						);
					}, __("ESS Mobile"));
				}
			},
		});

		frm.add_custom_button(__("Mobile Check-ins"), () =>
			frappe.set_route("List", "Employee Checkin", { employee: frm.doc.name, ess_device: ["is", "set"] }), __("ESS Mobile"));
		frm.add_custom_button(__("Trips"), () =>
			frappe.set_route("List", "ESS Trip", { employee: frm.doc.name }), __("ESS Mobile"));
		frm.add_custom_button(__("Attendance Register"), () =>
			frappe.set_route("query-report", "ESS Attendance Register", {
				employee: frm.doc.name, from_date: frappe.datetime.month_start(), to_date: frappe.datetime.get_today(),
			}), __("ESS Mobile"));
	},
});
