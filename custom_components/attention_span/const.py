"""Konstanter för AttentionSpan."""

from typing import Final

DOMAIN: Final = "attention_span"

SUBENTRY_RULE: Final = "rule"

CONF_TYPE: Final = "type"
CONF_ICON: Final = "icon"
CONF_ENTITIES: Final = "entities"
CONF_LEVELS: Final = "levels"
CONF_PRIORITY: Final = "priority"
# Signalen med regelns nya ordningstal, när bara det har ändrats. Formateras med regelns id.
SIGNAL_PRIORITY: Final = DOMAIN + "_priority_{}"
# Hide condition (dölj-villkor, «Dölj när» i formuläret): gör regeln dold oavsett nivåvillkor.
CONF_HIDE: Final = "hide"

TYPE_STATUS: Final = "status"
TYPE_PROGRESS: Final = "progress"
TYPE_VALUE: Final = "value"
TYPE_UPCOMING: Final = "upcoming"
TYPE_CUSTOM: Final = "custom"
TYPES: Final = (TYPE_STATUS, TYPE_PROGRESS, TYPE_VALUE, TYPE_UPCOMING, TYPE_CUSTOM)
# Hur många tillfällen Typen Kommande visar.
CONF_COUNT: Final = "count"
# Lovelace-kortkonfigurationen som Typen Eget kort visar.
CONF_CARD: Final = "card"
# Orsaken: en färdig mall för Typen eller «custom», med templaten i CONF_REASON_TEMPLATE.
# Saknas den har regeln ingen orsak.
CONF_REASON: Final = "reason"
CONF_REASON_TEMPLATE: Final = "reason_template"
# Åtgärderna: tjänsteanrop som kortet visar som knappar.
CONF_ACTIONS: Final = "actions"
# Hur länge ett kvitterat Larm väntar innan det larmar igen; None betyder aldrig.
CONF_REALARM_AFTER: Final = "realarm_after"
# Fladdergränsen: hur länge regeln måste ha varit under en nivå innan villkoret räknas som
# släppt.
CONF_FLAP_LIMIT: Final = "flap_limit"

# Nivåerna, den allvarligaste först (ADR 0002).
LEVELS: Final = ("alarm", "problem", "ongoing", "glance", "quiet")
# Larm, den enda nivån som kan kvitteras.
ALARM: Final = "alarm"
# Nivåerna som kan läggas åt sidan: Problem och Pågår.
SNOOZABLE: Final = ("problem", "ongoing")
# Tillståndet när ingen nivå gäller. Ingen nivå i sig.
HIDDEN: Final = "hidden"
# Värdet för en nivå i CONF_LEVELS som gäller utan villkor. Övriga nivåer i CONF_LEVELS
# har en lista med HA-villkor, och en nivå som saknas där har inget villkor.
ALWAYS: Final = "always"

# Dataformatets version. Ändringar som bryter kontraktet kräver ett nytt värde.
CONTRACT_VERSION: Final = 1
SOURCE_RULE: Final = "rule"

# Tjänsten som kvitterar ett Larm för hela hushållet.
SERVICE_ACKNOWLEDGE: Final = "acknowledge"
# Tjänsterna som lägger ett Problem eller en Pågår-notis åt sidan för hela hushållet, till
# ATTR_UNTIL eller tills det är lagat, och tar fram den igen.
SERVICE_SNOOZE: Final = "snooze"
SERVICE_UNSNOOZE: Final = "unsnooze"
ATTR_UNTIL: Final = "until"
