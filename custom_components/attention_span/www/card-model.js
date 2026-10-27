// Räknar fram vad AttentionSpan-kortet ska visa ur hass. Ingen DOM här.

const DOMAIN = "attention_span";
// Dataformatet kortet är byggt mot. Kortet laddas med integrationens version, så ett
// annat värde betyder att kort och integration inte hör ihop; sådana notiser läses inte.
const CONTRACT = 1;

// Nivåer som behöver hushållet och ritas som ett eget kort per notis. Så länge en notis
// har någon av dem är det inte lugnt, även när kortet inte kan rita notisens Typ.
export const NEEDS_ATTENTION = ["alarm", "problem", "ongoing"];

// Typer som kortet kan rita. Notiser av andra Typer ritas inte förrän kortet kan det.
const DRAWN_TYPES = ["value", "status"];

// Kortets egna texter, valda efter användarens språk (ADR 0001). status är Typen Status:
// tillståndet och hur länge det har gällt.
const STRINGS = {
  en: { calm: "All is calm at home.", status: (state, duration) => `${state} for ${duration}` },
  sv: { calm: "Allt är lugnt hemma.", status: (state, duration) => `${state} i ${duration}` },
};

function language(hass) {
  return hass.locale?.language ?? hass.language;
}

export function strings(hass) {
  return STRINGS[language(hass)] ?? STRINGS.en;
}

// Hur länge, i hela minuter under en timme, i timmar under två dygn och därefter i dygn.
function duration(ms, lang) {
  const minutes = Math.max(0, Math.floor(ms / 60_000));
  const [amount, unit] =
    minutes < 60
      ? [minutes, "minute"]
      : minutes < 48 * 60
        ? [Math.floor(minutes / 60), "hour"]
        : [Math.floor(minutes / (24 * 60)), "day"];
  return new Intl.NumberFormat(lang, { style: "unit", unit, unitDisplay: "short" }).format(amount);
}

// Det notisens Typ visar om entiteten.
function content(hass, type, shown, now) {
  if (!shown) return "–";
  const state = hass.formatEntityState(shown);
  if (type !== "status") return state;
  return strings(hass).status(state, duration(now - Date.parse(shown.last_changed), language(hass)));
}

function row(hass, stateObj, now) {
  const a = stateObj.attributes;
  return {
    name: a.friendly_name ?? stateObj.entity_id,
    icon: a.icon ?? null,
    type: a.type,
    text: content(hass, a.type, hass.states[a.entities?.[0]], now),
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

// now är tiden i millisekunder, så att «hur länge» kan räknas.
export function cardModel(hass, now) {
  const notices = Object.keys(hass.entities ?? {})
    .filter((id) => hass.entities[id].platform === DOMAIN)
    .map((id) => hass.states[id])
    .filter((s) => s?.attributes.contract === CONTRACT);
  const atLevel = (level) =>
    notices
      .filter((s) => s.state === level && DRAWN_TYPES.includes(s.attributes.type))
      .sort(byRuleOrder)
      .map((s) => row(hass, s, now));
  return {
    calm: !notices.some((s) => NEEDS_ATTENTION.includes(s.state)),
    alarm: atLevel("alarm"),
    problem: atLevel("problem"),
    ongoing: atLevel("ongoing"),
    glance: atLevel("glance"),
    quiet: atLevel("quiet"),
  };
}
