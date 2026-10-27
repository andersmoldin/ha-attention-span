# AttentionSpan

A relevance-driven Home Assistant dashboard: the home screen shows only what matters now, and everything else stays hidden until it becomes relevant.

## Language

**Rule** (regel):
A household-specific configuration describing when something deserves attention and at which Level.
_Avoid_: Watch, source

**Notice** (notis):
Something that currently deserves the household's attention at a given Level, produced by a Rule or by an Availability watch.
_Avoid_: Item, display, card, alert, notification

**Level condition** (nivåvillkor):
A Home Assistant condition attached to one Level of a Rule. When it holds, the Rule qualifies for that Level; the most severe qualifying Level wins.
_Avoid_: Step, threshold

**Hide condition** (dölj-villkor):
A condition of a Rule that, when it holds, makes the Rule Hidden regardless of its Level conditions.
_Avoid_: Exception, override

**Reason** (orsak):
The short text on a Notice that says why it is shown, from a ready-made template for the Type or an own template.
_Avoid_: Description, subtitle

**Action** (åtgärd):
A service call that a Rule offers as a button on its Notice, optionally with a confirmation text the household is asked first.
_Avoid_: Command, shortcut

**Placement** (placering):
Where a Rule stands among the Rules that can reach the same Level, which decides the order of their Notices within a Level. Saved as the Rule's `priority`, lowest first.
_Avoid_: Rank, weight

**Availability watch** (tillgänglighetsbevakning):
A household-wide setting that turns an integration that fails to load, or a chosen device that cannot be reached, into a Problem or Alarm after a set time. While it applies, Rules about the same device are Hidden.
_Avoid_: Automatic problem, health check

**Hidden** (dold):
The state of a Rule when no Level applies. Not a Level in itself.

**Snooze** (lägga åt sidan):
Moving a Problem or Ongoing Notice out of the way for the whole household until a chosen time (or with no end time), a New occurrence, or a more severe Level.
_Avoid_: Dismiss, mute, acknowledge

**New occurrence** (ny händelse):
A Rule reaching a Level again after having been below it (at a lower Level or Hidden).
_Avoid_: Retrigger

**Acknowledge** (kvittera):
Marking an Alarm as known by the household. The Alarm stays visible in compact form until its condition no longer holds or a set time has passed.
_Avoid_: Dismiss, confirm, snooze

### Levels

**Level** (nivå):
One of a fixed set of classes of attention that decide how prominently a Notice is shown.
_Avoid_: Tier, severity, step

**Alarm** (larm):
Something is wrong and needs action now.

**Problem** (problem):
Something is wrong and needs action, but not now. Includes integrations and connections that are down.

**Ongoing** (pågår):
Something is happening or waiting for the household, and ends by itself or through an action. Nothing is wrong.
_Avoid_: Active

**Glance** (blick):
Worth seeing in passing.

**Quiet** (tyst):
There if you look for it.

### Types

**Type** (typ):
The shape of a Notice's content, independent of its Level. Any Type can appear at any Level and carry actions.
_Avoid_: Card type, template

**Status** (status):
A state and how long it has held, for one entity or a group.
_Avoid_: Open/on with action

**Progress** (förlopp):
Time remaining or percent complete.

**Value** (värde):
A number with a unit.
_Avoid_: Row

**Upcoming** (kommande):
The next occurrence, or the next few, from a calendar or a sensor with timestamps.
_Avoid_: List

**Custom card** (eget kort):
Any Lovelace card configuration, for content no other Type fits.
