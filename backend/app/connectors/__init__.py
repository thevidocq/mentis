"""Integrations (connectors): the plugin contract and the core runtime that runs plugins safely.

`contract` is the only module plugins import. It uses the standard library only, so a plugin can
be developed and tested without the rest of the core.
"""
