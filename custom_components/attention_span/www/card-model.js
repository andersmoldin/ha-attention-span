// Räknar fram vad AttentionSpan-kortet ska visa ur hass. Ingen DOM här.

const DOMAIN = "attention_span";
// Dataformatet kortet är byggt mot. Kortet laddas med integrationens version, så ett
// annat värde betyder att kort och integration inte hör ihop; sådana notiser läses inte.
const CONTRACT = 1;

// Nivåer som behöver hushållet. Så länge en notis har någon av dem är det inte lugnt,
// även när kortet ännu inte ritar nivån.
const NEEDS_ATTENTION = ["alarm", "problem", "ongoing"];

// Typer som kortet kan rita. Notiser av andra Typer ritas inte förrän kortet kan det.
const DRAWN_TYPES = ["value"];

function row(hass, stateObj) {
  const a = stateObj.attributes;
  const shown = hass.states[a.entities?.[0]];
  return {
    name: a.friendly_name ?? stateObj.entity_id,
    icon: a.icon ?? null,
    value: shown ? hass.formatEntityState(shown) : "–",
  };
}

// Regelns ordningstal, lägst först; entitets-id avgör mellan lika tal. Tillgänglighet
// saknar ordningstal och kommer före reglerna.
function byRuleOrder(a, b) {
  const pa = a.attributes.priority ?? -Infinity;
  const pb = b.attributes.priority ?? -Infinity;
  if (pa !== pb) return pa < pb ? -1 : 1;
  return a.entity_id.localeCompare(b.entity_id);
}

export function cardModel(hass) {
  const notices = Object.keys(hass.entities ?? {})
    .filter((id) => hass.entities[id].platform === DOMAIN)
    .map((id) => hass.states[id])
    .filter((s) => s?.attributes.contract === CONTRACT);
  const atLevel = (level) =>
    notices
      .filter((s) => s.state === level && DRAWN_TYPES.includes(s.attributes.type))
      .sort(byRuleOrder)
      .map((s) => row(hass, s));
  return {
    calm: !notices.some((s) => NEEDS_ATTENTION.includes(s.state)),
    glance: atLevel("glance"),
    quiet: atLevel("quiet"),
  };
}
