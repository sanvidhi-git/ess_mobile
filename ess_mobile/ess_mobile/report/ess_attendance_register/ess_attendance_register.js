// Copyright (c) 2026, Sanvidhi Tech Pvt. Ltd. and contributors

frappe.query_reports["ESS Attendance Register"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1,
			default: frappe.datetime.get_today() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1,
			default: frappe.datetime.get_today() },
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{ fieldname: "department", label: __("Department"), fieldtype: "Link", options: "Department" },
		{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee" },
		{ fieldname: "log_type", label: __("Log Type"), fieldtype: "Select", options: "\nIN\nOUT" },
		{ fieldname: "mobile_only", label: __("Mobile App Punches Only"), fieldtype: "Check", default: 1 },
		{ fieldname: "include_rejected", label: __("Include Rejected Attempts"), fieldtype: "Check", default: 1 },
		{ fieldname: "exceptions_only", label: __("Exceptions Only"), fieldtype: "Check", default: 0 },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "status") {
			const color = data.status === "Rejected" ? "red" : (data.exception ? "orange" : "green");
			return `<span class="indicator-pill ${color}">${value}</span>`;
		}
		if (column.fieldname === "reason" && data.reason) {
			return `<span class="text-danger">${value}</span>`;
		}
		if (column.fieldname === "accuracy" && data.accuracy > 100) {
			return `<span class="text-warning">${value}</span>`;
		}
		return value;
	},
};
