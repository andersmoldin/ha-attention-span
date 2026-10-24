# AttentionSpan – teknisk lösning

En relevansstyrd dashboard för Home Assistant: hemskärmen visar bara det som är viktigt nu, och allt annat är dolt tills det blir relevant.
Bygger på designskisserna i `~/Developer/home-assistant/research/UI/`, främst «Det som är viktigt nu» (runda 2).

## Sammanfattning

En HACS-integration i Python där varje relevansregel ställs in i gränssnittet som en ordnad lista med steg (villkor → nivå) och exponeras som en egen sensor med nivå, prioritet, orsak, typ och «åt sidan»-status som attribut.
Integrationen sparar «åt sidan» och kvitteringar för hela hushållet, låter en sak återkomma när tiden gått ut, villkoret återkommer eller regeln går upp ett steg, och skapar själv Problem-poster för trasiga integrationer.
Samma repo levererar ett kort till sections-vyn som rangordnar posterna och ritar dem med fem generella typer eller en valfri kortkonfiguration, medan andra kort och teman kan byggas mot samma dataformat.

## Principer

- **Bedömning och presentation är skilda åt.** Backend avgör vad som är relevant; frontend ritar bara. Samma bedömning kan då användas av automationer, notiser, röstassistent och andra kort.
- **Inga hårdkodade entiteter eller apparater.** Allt som rör ett specifikt hem är konfiguration, eftersom lösningen distribueras via HACS.
- **Inget eget regelspråk.** Villkor uttrycks med Home Assistants inbyggda villkor och templates.

## Nivåmodellen

| Nivå | Betydelse | Beteende |
|---|---|---|
| Larm | Läcka o.d. | Överst, stort, rött. Kan kvitteras, aldrig läggas åt sidan. |
| Problem | Integration eller anslutning nere | Överst tills det läggs åt sidan, sedan ett litet chip. |
| Pågår | Tvätt, avresa, öppen port, kaffekokare | Ett kort per sak, försvinner när det är klart. |
| Blick | Bilens laddning, inomhustemperatur | Alltid där, en rad. |
| Tyst | Nästa bussar, sophämtning | Alltid där, lågmält, längst ner. |

Nivåerna är fasta. Ordning inom en nivå styrs av ett prioritetstal, inte av fler nivåer.

## Regler

En regel konfigureras i gränssnittet (en post per sak, t.ex. som config subentry) och består av:

- **Namn och ikon.**
- **Steg:** en ordnad lista med *villkor → nivå*. Det första uppfyllda steget gäller; inget uppfyllt steg betyder att saken är dold. Villkor anges med inbyggda villkors- eller template-väljare.
- **Prioritet** inom nivån.
- **Typ** (se Kortet) och vilka entiteter typen ska visa, t.ex. entiteten med tid kvar.
- **Åtgärder** (valfritt): tjänsteanrop som kortet visar som knappar, t.ex. «Stäng» eller «Starta nu».
- **Orsak** (valfritt): kort text, gärna template, som förklarar varför saken visas.

Exempel:

- *Findus*: `sensor.findus_remaining_time > 0` → Pågår, typ förlopp.
- *Vatten*: läcka = sant och inte kvitterad → Larm; läcka kvitterad men givaren blöt → Pågår; annars dold.
- *Buss 3*: alltid → Tyst, typ lista.
- *Findus offline*: offline → Problem; offline > 2 h → Larm.

## Dataformat (kontraktet mot frontend)

Varje regel blir en entitet, t.ex. `sensor.attention_span_findus`.

- **Tillstånd:** `larm`, `problem`, `pågår`, `blick`, `tyst` eller `dold`.
- **Attribut:** `level_index` (vilket steg som gäller), `priority`, `reason`, `type`, `entities` (de entiteter typen visar), `actions`, `snoozed_until`, `snooze_reason`, `acknowledged`, `since`.

Integrationen lyssnar på entiteterna i varje regels villkor och räknar om när de ändras. Tidsbaserade villkor räknas om på en timer.

Attributnamnen är ett versionerat, dokumenterat kontrakt så att tredjepartskort och teman kan byggas mot det.

Integrationen exponerar också tjänster: `attention_span.snooze` (till en tidpunkt), `attention_span.unsnooze` och `attention_span.acknowledge`.

## Lägg åt sidan och kvittera

- Gäller hela hushållet; samma läge på väggplatta och telefoner.
- Sparas i Home Assistants lagring (`Store`) och överlever omstart.
- Larm kan bara kvitteras, aldrig läggas åt sidan.
- En sak som lagts åt sidan visas igen när något av följande inträffar:
  1. **Tiden har gått ut.**
  2. **Ny händelse:** villkoret har blivit falskt och sedan sant igen.
  3. **Högre steg:** regeln har gått till ett allvarligare steg än när saken lades åt sidan.

Senare, utan ändring i datamodellen: **mätvärde** – regeln pekar på ett tal, och saken återkommer om talet blir sämre med en viss marginal (t.ex. frysen 4 °C → 7 °C).

## Automatiska problem

Integrationen bevakar själv integrationer som har slutat fungera (config entries som inte laddats) och entiteter som inte går att nå. Den skapar Problem-poster för dessa utan att någon regel behöver skrivas.
Funktionen kan stängas av helt, och enskilda integrationer kan uteslutas.

## Kortet

Ett eget Lovelace-kort som läggs i en vanlig sections-vy. Det läser alla AttentionSpan-entiteter, rangordnar dem efter nivå och prioritet och ritar dem.

Fem generella typer:

1. **Förlopp:** tid kvar eller procent (tvättmaskin, diskmaskin, laddning).
2. **Öppen/på med åtgärd:** tillstånd, hur länge och en knapp (garageport, kaffekokare).
3. **Larm:** stort, rött, med knapp för att kvittera.
4. **Rad:** kort text och värde (bilen 52 %, inomhustemperatur) för nivån Blick.
5. **Lista:** nästa avgångar, sophämtning för nivån Tyst.

För sådant som inte passar kan en regel ange en valfri kortkonfiguration som kortet då visar.
Detaljvyer bakom ett tryck använder Home Assistants vanliga dialogrutor för mer information.
Problem som lagts åt sidan visas som ett chip med antal, och om inget är relevant visas ett lugnt tomt läge.

Utseende (Natt/Dag) hanteras med Home Assistant-teman och CSS-variabler; teman ändrar färg och typsnitt, inte layout.

## Paketering

- Ett HACS-repo av typen integration.
- Integrationen levererar kortets JavaScript och registrerar det som frontend-resurs automatiskt, så att kort och integration alltid har matchande versioner.
- Andra kort och teman kan byggas i separata repon mot dataformatet.

## Senare

- Mätvärde som fjärde sätt att återkomma från «åt sidan».
- En dashboard-strategi som genererar hela vyn, inklusive ikonraden.
- Fler typer om de generella formerna inte räcker.
