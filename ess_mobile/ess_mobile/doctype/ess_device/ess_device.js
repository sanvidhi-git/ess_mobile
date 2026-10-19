// Copyright (c) 2026, Sanvidhi Tech Pvt. Ltd. and contributors

frappe.ui.form.on("ESS Device", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.is_active) return;
		frm.add_custom_button(__("Reset Device"), () =>
			frappe.confirm(__("Sign this phone out and let the employee register a new one?"), () =>
				frappe.call({
					method: "ess_mobile.api.admin.reset_device",
					args: { employee: frm.doc.employee },
					freeze: true,
					callback: () => frm.reload_doc(),
				})));
	},
});
