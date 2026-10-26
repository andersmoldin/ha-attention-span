"""Konstanter för AttentionSpan."""

from typing import Final

DOMAIN: Final = "attention_span"

SUBENTRY_RULE: Final = "rule"

CONF_TYPE: Final = "type"
CONF_ICON: Final = "icon"
CONF_ENTITIES: Final = "entities"
CONF_LEVELS: Final = "levels"
CONF_PRIORITY: Final = "priority"

TYPE_VALUE: Final = "value"
TYPES: Final = (TYPE_VALUE,)

# Nivåerna, den allvarligaste först (ADR 0002).
LEVELS: Final = ("alarm", "problem", "ongoing", "glance", "quiet")
# Tillståndet när ingen nivå gäller. Ingen nivå i sig.
HIDDEN: Final = "hidden"
# Nivåer som en regel kan få «Alltid» på i formuläret.
ALWAYS_LEVELS: Final = ("glance", "quiet")
# Värdet för en nivå i CONF_LEVELS som gäller utan villkor.
ALWAYS: Final = "always"

# Dataformatets version. Ändringar som bryter kontraktet kräver ett nytt värde.
CONTRACT_VERSION: Final = 1
SOURCE_RULE: Final = "rule"
