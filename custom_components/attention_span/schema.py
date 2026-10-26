"""HA bytte schemabibliotek från voluptuous till probatio. Stöd båda."""

try:
    import probatio as vol
except ImportError:  # Äldre Home Assistant
    import voluptuous as vol  # type: ignore[no-redef]

__all__ = ["vol"]
