app_name = "ess_mobile"
app_title = "ESS Mobile"
app_publisher = "Sanvidhi Tech Pvt. Ltd."
app_description = "Employee Self Service mobile app: selfie + geo attendance, travel tracking, leave, payslips, expenses"
app_email = "vijayshastri11@gmail.com"
app_license = "mit"
app_logo_url = "/assets/ess_mobile/images/ess-mobile-logo.svg"
app_home = "/desk/ess-mobile"

required_apps = ["frappe/erpnext", "frappe/hrms"]

# Apps screen (/apps) and the v16 desktop grid both read this entry.
add_to_apps_screen = [
    {
        "name": "ess_mobile",
        "logo": "/assets/ess_mobile/images/ess-mobile-logo.svg",
        "title": "ESS Mobile",
        "route": app_home,
        "has_permission": "ess_mobile.api.admin.check_app_permission",
    }
]

after_install = "ess_mobile.install.after_install"
after_migrate = "ess_mobile.install.after_migrate"

# Desk form enhancements on standard doctypes
doctype_js = {
    "Employee Checkin": "public/js/employee_checkin.js",
    "Employee": "public/js/employee.js",
}
doctype_list_js = {
    "Employee Checkin": "public/js/employee_checkin_list.js",
}

scheduler_events = {
    "hourly": ["ess_mobile.api.tracking.close_stale_trips"],
}

doc_events = {
    "Expense Claim": {
        # free the trip again if the travel claim is deleted or cancelled
        "on_trash": "ess_mobile.api.expense.release_trip",
        "on_cancel": "ess_mobile.api.expense.release_trip",
    },
}
