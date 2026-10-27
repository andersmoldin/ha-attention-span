// Räknar fram vad AttentionSpan-kortet ska visa ur hass. Ingen DOM här.

const DOMAIN = "attention_span";
// Dataformatet kortet är byggt mot. Kortet laddas med integrationens version, så ett
// annat värde betyder att kort och integration inte hör ihop; sådana notiser läses inte.
const CONTRACT = 1;

// Nivåer som behöver hushållet och ritas som ett eget kort per notis. Så länge en notis
// har någon av dem är det inte lugnt, även när kortet inte kan rita notisens Typ.
export const NEEDS_ATTENTION = ["alarm", "problem", "ongoing"];

// Typer som kortet kan rita. Notiser av andra Typer ritas inte förrän kortet kan det.
const DRAWN_TYPES = ["value", "status", "progress", "upcoming", "custom"];

// Kortets egna texter, valda efter användarens språk (ADR 0001). status är Typen Status:
// tillståndet och hur länge det har gällt, och group hur många medlemmar i en grupp som har
// gruppens tillstånd. left är tid kvar för Typen Förlopp. now, soon,
// today och tomorrow säger när ett tillfälle för Typen Kommande är.
const STRINGS = {
  en: {
    calm: "All is calm at home.",
    status: (state, duration) => `${state} for ${duration}`,
    group: (state, count, total) => `${state} · ${count} of ${total}`,
    left: (duration) => `${duration} left`,
    now: "now",
    soon: (duration) => `in ${duration}`,
    today: "today",
    tomorrow: "tomorrow",
  },
  sv: {
    calm: "Allt är lugnt hemma.",
    status: (state, duration) => `${state} i ${duration}`,
    group: (state, count, total) => `${state} · ${count} av ${total}`,
    left: (duration) => `${duration} kvar`,
    now: "nu",
    soon: (duration) => `om ${duration}`,
    today: "i dag",
    tomorrow: "i morgon",
  },
};

function language(hass) {
  return hass.locale?.language ?? hass.language;
}

export function strings(hass) {
  return STRINGS[language(hass)] ?? STRINGS.en;
}

// Hur länge, i hela minuter under en timme, i timmar under två dygn och därefter i dygn.
// round avrundar till hela minuter: nedåt för hur länge något har gällt, uppåt för tid kvar.
function duration(ms, lang, round = Math.floor) {
  const minutes = Math.max(0, round(ms / 60_000));
  const [amount, unit] =
    minutes < 60
      ? [minutes, "minute"]
      : minutes < 48 * 60
        ? [Math.floor(minutes / 60), "hour"]
        : [Math.floor(minutes / (24 * 60)), "day"];
  return new Intl.NumberFormat(lang, { style: "unit", unit, unitDisplay: "short" }).format(amount);
}

const clamp = (fraction) => Math.min(1, Math.max(0, fraction));

// En timers längd och tid kvar, «H:MM:SS», i millisekunder.
function hms(text) {
  const [h, m, s] = (text ?? "").split(":").map(Number);
  return ((h * 60 + m) * 60 + s) * 1000;
}

// När Förloppet började och slutar, i millisekunder, eller null när det inte går att veta.
// En timer har sin längd och sluttid. En sluttid i en sensor räknas från när den sattes.
function span(shown, now) {
  const a = shown.attributes;
  if (shown.entity_id.startsWith("timer.")) {
    const total = hms(a.duration);
    const end = shown.state === "active" ? Date.parse(a.finishes_at) : now + hms(a.remaining);
    return shown.state === "idle" ? null : { start: end - total, end };
  }
  if (a.device_class === "timestamp") {
    return { start: Date.parse(shown.last_changed), end: Date.parse(shown.state) };
  }
  return null;
}

// Typen Förlopp: tid kvar eller procent, och hur långt det har kommit (0–1) för stapeln.
function progress(hass, shown, now) {
  const state = hass.formatEntityState(shown);
  if (shown.attributes.unit_of_measurement === "%") {
    const percent = Number.parseFloat(shown.state);
    return { text: state, done: Number.isFinite(percent) ? clamp(percent / 100) : null };
  }
  const { start, end } = span(shown, now) ?? {};
  if (!Number.isFinite(start) || !Number.isFinite(end)) return { text: state, done: null };
  const left = duration(end - now, language(hass), Math.ceil);
  return { text: strings(hass).left(left), done: end > start ? clamp((now - start) / (end - start)) : 1 };
}

// Tidszonen som användaren har valt i sin profil i HA: serverns eller enhetens.
function timeZone(hass) {
  return hass.locale?.time_zone === "server" ? hass.config?.time_zone : undefined;
}

// Ett datum, «2026-10-29», som dagar sedan 1970, för att räkna hela dagar mellan datum.
function dayNumber(isoDate) {
  const [y, m, d] = isoDate.split("-").map(Number);
  return Date.UTC(y, m - 1, d) / 86_400_000;
}

// När ett tillfälle är, med så lite text som behövs: nu, om en stund, i dag, i morgon,
// veckodagen under den närmaste veckan och annars datumet. Heldag saknar klockslag.
function when(hass, occurrence, now) {
  const lang = language(hass);
  const zone = timeZone(hass);
  const text = strings(hass);
  const allDay = !occurrence.start.includes("T");
  // Ett heldagsdatum gäller hushållets kalender; mitt på dagen i UTC är samma datum i alla tidszoner.
  const start = allDay ? Date.parse(`${occurrence.start}T12:00:00Z`) : Date.parse(occurrence.start);
  const format = (options) =>
    new Intl.DateTimeFormat(lang, { ...options, timeZone: allDay ? "UTC" : zone }).format(start);
  if (!allDay && start <= now) return text.now;
  if (!allDay && start - now < 60 * 60_000) {
    return text.soon(duration(start - now, lang, Math.ceil));
  }
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: zone }).format(now);
  const day = allDay ? occurrence.start : new Intl.DateTimeFormat("en-CA", { timeZone: zone }).format(start);
  const days = dayNumber(day) - dayNumber(today);
  const date =
    days <= 0
      ? text.today
      : days === 1
        ? text.tomorrow
        : days < 7
          ? format({ weekday: "short" })
          : format({ day: "numeric", month: "short" });
  return allDay ? date : `${date} ${format({ timeStyle: "short" })}`;
}

// Typen Kommande: de närmaste tillfällena, med vad det är när det står i kalendern.
function upcoming(hass, occurrences, now) {
  const shown = (occurrences ?? []).map((occurrence) =>
    [when(hass, occurrence, now), occurrence.summary].filter(Boolean).join(" "),
  );
  return { text: shown.join(" · ") || "–", done: null };
}

// Medlemmarna om entiteten är en grupp: i domänen group eller en grupphjälpare (plattformen
// group). Andra entiteter kan också ha listan entity_id, till exempel scener.
function members(hass, shown) {
  const group =
    shown.entity_id.startsWith("group.") || hass.entities?.[shown.entity_id]?.platform === "group";
  const ids = shown.attributes.entity_id;
  return group && Array.isArray(ids) ? ids : null;
}

// Det notisens Typ visar: en text och, för Förlopp, hur långt det har kommit. moreInfo är
// entiteten som ett tryck visar i HA:s detaljdialog.
function content(hass, attributes, now) {
  if (attributes.type === "upcoming") return upcoming(hass, attributes.occurrences, now);
  // Eget kort visar sin kortkonfiguration i stället för en text.
  if (attributes.type === "custom") return { text: "", done: null };
  const type = attributes.type;
  const shown = hass.states[attributes.entities?.[0]];
  if (!shown) return { text: "–", done: null };
  if (type === "progress") return progress(hass, shown, now);
  const state = hass.formatEntityState(shown);
  if (type !== "status") return { text: state, done: null };
  const group = members(hass, shown);
  if (group) {
    const count = group.filter((id) => hass.states[id]?.state === shown.state).length;
    const text = strings(hass).group(state, count, group.length);
    return { text, done: null, moreInfo: shown.entity_id };
  }
  const since = duration(now - Date.parse(shown.last_changed), language(hass));
  return { text: strings(hass).status(state, since), done: null };
}

function row(hass, stateObj, now) {
  const a = stateObj.attributes;
  const { text, done, moreInfo = null } = content(hass, a, now);
  return {
    id: stateObj.entity_id,
    name: a.friendly_name ?? stateObj.entity_id,
    icon: a.icon ?? null,
    type: a.type,
    text,
    done,
    card: a.type === "custom" ? a.card : null,
    moreInfo,
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
