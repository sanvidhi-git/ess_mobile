import frappe

from ess_mobile.setup.custom_fields import make_custom_fields


def after_install():
    make_custom_fields()
    _default_settings()


def after_migrate():
    make_custom_fields()


def _default_settings():
    """Single doctypes don't apply JSON defaults until first save."""
    settings = frappe.get_single("ESS Settings")
    for df in settings.meta.fields:
        if df.default is not None and settings.get(df.fieldname) in (None, ""):
            settings.set(df.fieldname, df.default)
    settings.flags.ignore_mandatory = True
    settings.save(ignore_permissions=True)
