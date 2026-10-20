"""Seed modes of transport and odometer settings on existing sites."""

from ess_mobile.api.transport import seed_defaults
from ess_mobile.setup.custom_fields import make_custom_fields


def execute():
    make_custom_fields()
    seed_defaults()
