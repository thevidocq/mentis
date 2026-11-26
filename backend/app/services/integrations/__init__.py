"""Integrations in the core: instances per customer, safe execution of plugin operations,
choice of the operations for a question (planner) and their results as passages for the answer."""

from app.services.integrations.instances import (  # noqa: F401
    IntegrationFailed,
    enabled_plugins,
    for_chat,
    run,
    selectable,
    set_enabled_plugins,
    test,
    usable_connector,
)
