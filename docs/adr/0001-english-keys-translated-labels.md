# English keys in code and contract, Swedish via translations

State values, attribute names, service names and domain terms are English slugs (`alarm`, `hidden`, `snoozed_until`); Swedish appears only through Home Assistant's `translations/` files. The data format is a public, versioned contract that third-party cards and themes build against, and the integration is distributed via HACS to non-Swedish users, so renaming keys later would break consumers. Non-ASCII state values (`pågår`) would also be awkward in templates and URLs.
