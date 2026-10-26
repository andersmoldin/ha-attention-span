"""Schemabiblioteket som Home Assistant bygger på: probatio, tidigare voluptuous."""

try:
    import probatio as vol
except ImportError:  # Home Assistant före bytet till probatio
    import voluptuous as vol  # type: ignore[no-redef]

__all__ = ["vol"]
