# Requisiti — Charging Energy Card (Omoda / Jaecoo)

> Custom Lovelace card che mostra l'**energia di ricarica** dell'auto come **istogramma**
> per periodo, distinguendo la ricarica **a casa** (verde) da quella **fuori casa** (giallo),
> con un **selettore di periodo in stile dashboard Energy** (Giorno / Settimana / Mese +
> navigazione avanti/indietro).

- **Deliverable**: un unico file `www/omoda-jaecoo-energy-card.js` + questo documento.
- **Companion** dell'integrazione `omoda_jaecoo` (non è un frontend plugin).

---

## 1. Obiettivo

Rispondere a "quanta energia ho caricato, quando, e dove (casa vs fuori)" con una lettura
immediata: barre impilate per intervallo temporale, verde = casa, giallo = fuori casa, e un
selettore per scorrere i periodi come nella dashboard Energy nativa.

## 2. Sorgenti dati

Due sensori dell'integrazione, entrambi `device_class: energy`, unità `kWh`,
`state_class: TOTAL_INCREASING` → **idonei alle statistiche a lungo termine** (requisito
essenziale: l'istogramma legge le statistiche, non lo stato istantaneo).

| Ruolo | Default entity_id | Override config |
|---|---|---|
| Ricarica **a casa** (verde) | `sensor.home_charging_energy` | `home_entity` |
| Ricarica **fuori casa** (giallo) | `sensor.away_charging_energy` | `away_entity` |

I due sensori sono generati dall'integrazione solo per veicoli **BEV** con l'opzione
`charge_energy_sensors` attiva. La separazione casa/fuori usa lo zone helper `car_zone`
(presenza "At Home").

## 3. Selettore di periodo (stile Energy)

Tre modalità, con `‹` / `›` per scorrere e un'etichetta centrale del periodo corrente:

| Modalità | Granularità barre | N. barre | `period` statistico |
|---|---|---|---|
| **Giorno** (default) | oraria | 24 (00–23) | `hour` |
| **Settimana** | giornaliera (lun–dom) | 7 | `day` |
| **Mese** | giornaliera | 28–31 | `day` |

- Cambiando modalità l'ancora torna al **periodo corrente** (oggi / questa settimana / questo mese).
- Il pulsante `›` è **disabilitato** sul periodo corrente (niente futuro).
- Le etichette sono in italiano (mesi/giorni), il range mostra es. `24 luglio 2026`,
  `20 lug – 26 lug 2026`, `luglio 2026`.

## 4. Dati: statistiche a lungo termine

Fonte: WebSocket `recorder/statistics_during_period` con `types: ["change"]`.

```js
hass.callWS({
  type: 'recorder/statistics_during_period',
  start_time: <ISO inizio periodo, ora locale>,
  end_time:   <ISO fine periodo>,
  statistic_ids: [home_entity, away_entity],
  period: 'hour' | 'day',
  types: ['change'],
})
```

- `change` = energia (kWh) accumulata nel bucket = incremento del contatore in quell'intervallo.
- Ogni bucket ha `start` come **epoch-ms** (numero) o ISO (stringa): entrambi gestiti.
- Valori `change` nulli o **≤ 0** sono ignorati (l'energia non decresce; eventuali reset del
  contatore sono già gestiti da HA nel calcolo di `change`).
- I bucket sono assegnati al bin `[start, end)` del range che ne contiene lo `start`
  (allineamento in **ora locale**, coerente con la dashboard Energy).

## 5. Rendering

- **Istogramma SVG** responsive (`viewBox`, larghezza 100%), barre **impilate**:
  verde (casa) in basso, giallo (fuori) sopra.
- Asse Y con 4 gridline e scala superiore "arrotondata" (1/2/5 ×10ⁿ); etichette in kWh.
- Asse X: etichette diradate quando le barre sono molte (ogni 3 per la settimana lunga,
  ogni 5 per il mese; tutte per il giorno con passo adattivo).
- **Totali** sopra il grafico: totale periodo + parziale casa (🟢) e fuori (🟡).
- **Tooltip** nativo per barra (`<title>`): valore totale + scomposizione casa/fuori.
- **Legenda** casa / fuori casa.
- Stati speciali: *Carico…* durante il fetch; *Nessuna ricarica in questo periodo* se il
  totale è 0; messaggio d'errore se le statistiche non sono disponibili (con dettaglio).

## 6. Colori

- Casa (home): **verde** `#43c46d`.
- Fuori casa (away): **giallo** `#f2c94c`.
- Cromie fisse di serie (come le serie della dashboard Energy), indipendenti dal tema;
  testo/griglia usano le variabili CSS di HA (`--primary-text-color`, `--divider-color`, …)
  così la card resta leggibile in tema chiaro e scuro.

## 7. Configurazione (esempio YAML)

```yaml
type: custom:omoda-jaecoo-energy-card
# tutti opzionali:
home_entity: sensor.home_charging_energy
away_entity: sensor.away_charging_energy
title: "Energia di ricarica"
```

Registrazione risorsa: `/local/omoda-jaecoo-energy-card.js` come *Modulo JavaScript*.

## 8. Architettura (seme OOP)

Oggetti puri (niente DOM/hass), il nucleo verificabile:

- **`DateRange`** — `mode` + data d'ancora → `{start, end, period, bins[], label}`. Calcola i
  confini in ora locale e i bin `[s,e)` per ogni barra. Gestisce `shift(±1)` per navigare.
- **`EnergyModel`** — dati i bucket statistici home/away e i bin, produce
  `{rows[{label,tip,home,away}], totHome, totAway, total, max}`. Deterministico.
- **`StatsClient`** — sottile wrapper su `hass.callWS` per `statistics_during_period`.
- **`OmodaJaecooEnergyCard`** (HTMLElement) — orchestrazione: selettore, fetch con guardia
  anti-race (`_reqId`), render SVG.

## 8-bis. Localizzazione (i18n)

Etichette UI con **base inglese** (Home/Away coerenti con `translations/en.json`:
Home Charging Energy / Away Charging Energy) e **traduzione italiana** (mesi e giorni
inclusi). Lingua auto-selezionata da `hass.language`, override con `language: it|en` in
config, fallback `en`. Dizionario `STRINGS = { en, it }` con helper `tr(lang,key)`; `DateRange`
riceve la lingua per produrre le etichette di periodo localizzate (es. `24 July 2026` ↔
`24 luglio 2026`). Il titolo di default segue la lingua (`Charging Energy` / `Energia di
ricarica`) se non impostato esplicitamente con `title:`.

## 9. Requisiti non funzionali

- Nessun build step: vanilla JS ES module, zero dipendenze.
- Anti-race: richieste sovrapposte scartate (`_reqId`); l'ultima vince.
- Degrado grazioso: assenza di statistiche o errore WS non rompono la card.
- `Date`/`new Date()` usati lato browser (leciti nel contesto card).
- Accessibilità: pulsanti con `aria-label`, tooltip informativi, contrasto adeguato.

## 10. Prerequisiti / note operative

- Le statistiche a lungo termine si popolano nel tempo: i sensori appena creati mostreranno
  poco storico finché non accumulano ricariche.
- La card mostra **energia**, non potenza; il bucket orario è l'energia caricata in quell'ora.
- Fuso orario: i confini periodo sono in **ora locale** dell'istanza/browser.

## 11. Fuori scope (per ora)

- Editor grafico della card (config via YAML).
- Granularità "Anno" (barre mensili) — aggiungibile con `period: 'month'`.
- Esportazione CSV / confronto tra periodi.
- Costi in valuta (nessuna tariffa modellata).
