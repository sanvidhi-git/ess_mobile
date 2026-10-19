// Copyright (c) 2026, Sanvidhi Tech Pvt. Ltd. and contributors

frappe.query_reports["ESS Travel Summary"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1,
			default: frappe.datetime.month_start() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1,
			default: frappe.datetime.get_today() },
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{ fieldname: "department", label: __("Department"), fieldtype: "Link", options: "Department" },
		{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee" },
		{ fieldname: "group_by", label: __("Show"), fieldtype: "Select", options: "Employee\nTrip",
			default: "Employee" },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "unclaimed_km" && data.unclaimed_km > 0) {
			return `<span class="text-warning">${value}</span>`;
		}
		return value;
	},
};
