# Changelog — Omoda / Jaecoo for Home Assistant (English fork)

What changes in each update, in plain words. Newest entries at the top.
Update via **HACS → Omoda / Jaecoo → Update**, then restart Home Assistant.

This is the **English fork** of the original Omoda 9 / Jaecoo integration. Everything
above the "Pre-fork history" divider is the English fork; everything below it is the
original project's changelog (Italian + English), preserved for history.

## v1.5.41 — 2026-07-03

- **Find Car / Locate Car: fixed the recurring regression for good.** After some updates these
  buttons vanished (shown as "no longer provided") and Italian text crept back. Root cause: the
  bundled protocol modules load by generic names (`commands`, `wake`, …), and the command
  catalog could be served from the wrong copy — a stale bytecode cache, a leftover cached module
  after a reload, or even another integration's `commands.py`. The integration now loads its own
  catalog directly from its files on every start, so the correct English command set (including
  Find Car and Locate Car) is always what the buttons are built from.

## v1.5.42 — 2026-07-05

- **Stable entity IDs for the diagnostic result sensors (fixes the failed-command blueprint).**
  The "Command Result", "Wake-up Result" and "Location Probe Result" sensors used to derive
  their entity ID from their display name, so the translation work renamed them and silently
  moved the entity ID (e.g. to `sensor.diagnostic_command_result`) - which is why the
  failed-command blueprint stopped finding the sensor. They now have fixed entity IDs
  (`sensor.omoda_jaecoo_command_result`, `…_wake_result`, `…_location_probe_result`) that no
  longer change when the name changes, and anyone left on the old drifted ID is migrated
  automatically on the next start. The blueprint default matches again.

## v1.5.40 — 2026-07-03

- **Card: fixed "Configuration error" on the mobile app.** The card worked on desktop but
  failed to load in the companion app. Two causes fixed: the card used a modern JS feature
  (optional chaining) that older Android WebView builds can't parse — which silently stopped
  the card from registering at all — and an unescaped vehicle name could throw while rendering.
  The card now uses only broadly-supported JavaScript, escapes the name, wraps rendering so any
  error shows inline instead of blanking the card, guards against double-registration, and adds
  iOS/Safari CSS fallbacks. If the card still won't load on the mobile app, add it as a resource
  once: **Settings → Dashboards → ⋮ → Resources → + Add**, URL `/omoda_jaecoo_card/omoda-card.js`,
  type **JavaScript module**, then reopen the app.

## v1.5.39 — 2026-07-03

- **Queued commands stay snappy.** Building on the new command queue: each command returns
  as soon as it's sent (instant feedback), while the short spacing before the next queued
  command happens in the background — so a single command no longer waits on the settle.

## v1.5.38 — 2026-07-03

- **Commands now queue instead of erroring.** The car handles one command at a time, so a
  second command (or an accidental tap) now **waits its turn and then runs**, instead of
  failing with "another command is still in progress". Each command is spaced until the car
  confirms the previous one (or a short timeout), and a genuine pile-up still surfaces a clear
  message after ~30s rather than piling up forever.

## v1.5.37 — 2026-07-03

- **Fixed for good: old code running after a HACS update.** A HACS update overwrites the code
  but leaves the old compiled bytecode cache behind, and the protocol modules kept loading the
  stale copy — which is why Italian text and the missing Find/Locate buttons kept coming back.
  The stale cache is now cleared automatically on load, so a normal update + restart is enough.
- **Card: swapped range and lock.** The lock status (Locked/Unlocked) now shows under the
  vehicle name, and the estimated range moved to the metrics row.

## v1.5.36 — 2026-07-03

- **Faster commands, fewer sign-ins.** The vehicle authentication (taskId) is now cached and
  reused for ~10 minutes, so most commands skip the PIN/login round-trip and go straight
  through. If it expires the integration re-authenticates automatically and retries once.
- **Card: read-only Lock status.** Replaced the duplicated range with a **Locked / Unlocked**
  text tile (no button, so it can't be pressed by accident).
- **Card: tap the photo to open the vehicle's device page** (settings/all entities) instead of
  a control.

## v1.5.35 — 2026-07-03

- **Card now respects decimal places.** Values on the card (range, odometer, battery) are
  formatted the way Home Assistant displays them, so setting a sensor's display precision to
  0 shows "145 mi" and "65%" instead of the raw converted number with many decimals.

## v1.5.34 — 2026-07-03

- **Sleeker card.** Redesigned the vehicle card: a photo hero (uses your **Vehicle image URL**
  from the integration options) with the name, battery and charging/range, a clean metrics
  strip (range · charging · odometer), and warnings only when active. It shows just the
  essentials by default — set `show_all: true` to list everything.

## v1.5.33 — 2026-07-03

- **Speed can now show in mph.** The Speed sensor was missing its distance/speed type, so
  Home Assistant couldn't convert it. It now follows your unit system (mph in imperial) and
  you can override the unit per-entity.
- **Miles-per-kWh efficiency sensor added.** Home Assistant can't convert energy-per-distance
  units (kWh/100 km), so there's now a separate **Electric Efficiency** sensor in **mi/kWh**
  for miles users, alongside the existing kWh/100 km one.
- **Clearer status messages.** Removed jargon from the wake/refresh messages (e.g.
  "BREAKTHROUGH" → "Live data received from the vehicle") for plain, professional wording.

## v1.5.32 — 2026-07-03

- **Fixed the remaining Italian text** in command results and status messages (e.g.
  "comando accettato", "SVOLTA: dati realtime…"). It wasn't the API — it was old cached
  copies of the protocol code still in memory. ALL of that code is now refreshed from disk
  on load, so the English versions apply. (One full restart still needed to load this.)
- **Vehicle image on the card.** You can now set a **Vehicle image URL** in the
  integration options (Settings → Devices & Services → Omoda/Jaecoo → Configure). The
  custom card uses it as its header image automatically — no card editing needed.
- **Card now refreshes properly on update** (cache-busting), so you get the current
  simplified card instead of an old cached version. If it still looks busy, hard-refresh
  the browser (Ctrl-Shift-R).

## v1.5.31 — 2026-07-03

- **Fixed: buttons keeping old/stale entity keys after an update.** The car-protocol code is
  cached in memory, so a reload (rather than a full Home Assistant restart) could keep the
  old command list — which made buttons like Find Car / Locate Car go missing while old
  ones lingered. The command list is now refreshed from disk on every load, so a normal
  reload is enough. (You still need one full restart to pick up this version.)

## v1.5.30 — 2026-07-03

- **Auto-remove the old Italian-named leftover buttons** (Trova auto, Localizza, the
  clima raffredda/riscalda ON/OFF, finestrini ventila, antifurto ON/OFF). These were
  orphaned "no longer provided" entities from early fork versions whose command keys were
  later renamed to English or turned into switches. They're now cleaned up automatically on
  load, so only the English entities remain.

## v1.5.29 — 2026-07-03

- **Fixed: entity names reverting to Italian.** This happened whenever the integration
  failed to finish loading (a temporary car-connection / certificate / session hiccup):
  Home Assistant then fell back to each entity's old stored name. Now the entities always
  load first and the car connection is established in the background, so it can no longer
  take the whole integration (and your English names) down with it. If the car is briefly
  unreachable the entities just show as *unavailable* — with their correct English names.

## v1.5.28 — 2026-07-03

- **Fixed: doors, windows, lock, charge state no longer show "unknown".** These now also
  read from the realtime channel (which carries them), so a parked car — which sends no
  live push data — shows its real state instead of blank.
- **Fixed: range/battery/telemetry no longer stay blank with "Automatic update" off.** A
  one-time read-only refresh now runs shortly after startup regardless of the switch (it's
  read-only — no wake, no 12V drain), so the sensors populate on their own.
- **New curated dashboard card.** The card now shows the important things at a glance —
  vehicle name, battery %, charging state, estimated range — and warnings (tyre, low
  battery, offline) only when something's actually wrong. Set `show_all: true` to also list
  everything, or `entities: [...]` to add your own rows.
- Range in miles vs km follows your Home Assistant unit system (Settings → System →
  General), or override per-sensor — no separate setting needed.

## v1.5.27-EN — 2026-07-03

- **English only.** Removed the Italian translation file, so entity names are always in
  English regardless of your Home Assistant language (previously stale Italian names could
  reappear). Hardened startup so the new cleanup/re-auth steps can never stop the
  integration from loading.

## v1.5.26-EN — 2026-07-03

- **Windows are now a single 3-position control** — Closed / Ventilate / Open — instead of
  a cover plus a separate "Ventilate" button.

## v1.5.25-EN — 2026-07-03

- **The custom dashboard card now appears in the card picker automatically** — no need to
  add a dashboard resource by hand.
- **Retired entities are removed automatically on upgrade** (old charge-limit, the on/off
  buttons that became switches, and fuel-only sensors on an electric car), instead of
  lingering as "unavailable".

## v1.5.24-EN — 2026-07-03

- **The integration adapts to your specific vehicle.** It reads the climate temperature
  range and the powertrain from your account, so climate control matches your car and pure
  electric cars no longer show fuel-only sensors.
- **New "Charging" sensor** — on while the car is actively charging.
- **Re-authentication prompt.** If your session expires (e.g. you open the official app),
  Home Assistant now asks you to re-authenticate with a fresh code instead of the data
  silently going stale.
- **Removed the charge-limit control.** The Omoda/Jaecoo backend has no way to set a charge
  limit (it's car-screen-only), so the non-working entities were removed.

## v1.5.23-EN — 2026-07-03

- **Works for electric (BEV) and plug-in hybrid (PHEV) cars.** Range, consumption and
  related sensors now read the correct field for your car — e.g. estimated range remaining
  now shows correctly on electric cars.
- **New sensors:** Charging Power and WLTP range.
- **Rewrote the dashboard card** (the old one was broken); it auto-discovers your vehicle's
  entities and works for any model.
- **Tidier controls** — removed duplicate on/off buttons where a switch already exists.
- **Full English translation** of the whole integration (code comments + user messages).
- **Added a standalone API "sandbox" tool** (`sandbox/` in the repo) for testing the car's
  API outside Home Assistant.

## v1.5.22-EN — Initial English Fork Release & Complete Localization

- **Domain Rename**: Completely renamed the integration domain from `omoda9` to `omoda_jaecoo` to better reflect support for Jaecoo vehicles and the shared app platform.
- **English Native**: Translated all default entity names, binary sensors, buttons, and switches from Italian to English.
- **Dynamic Translation Keys**: Reworked all entity lookup strings to use standard `snake_case` english keys.
- **Backward Compatibility**: Injected all legacy Italian entity translation strings as fallbacks into the English dictionary so that existing users upgrading to this fork will seamlessly transition without broken dashboard names.
- **Automation Blueprint**: Renamed and translated the `failed_command.yaml` blueprint into English.
- **Web API**: Forced HTTP requests to the Omoda backend to use the `"Accept-Language": "en-GB"` header so that OTP codes and emails are dispatched in English.

---

# Pre-fork history — original Italian project

The entries below are the **original Omoda 9 / Jaecoo project's** changelog (Italian, with
an English section per entry), kept unchanged for historical reference. The English fork
starts at v1.5.22-EN above.

## v1.5.22 — 2026-06-24

### 🇮🇹 Italiano

- **Ora i dati dell'auto si aggiornano da soli mentre guidi.** Prima, durante un viaggio, valori
  come batteria, chilometri percorsi e autonomia restavano fermi finché non premevi a mano il
  pulsante "Aggiorna stato completo": l'auto in movimento, infatti, non invia aggiornamenti
  spontanei. Adesso l'integrazione se ne accorge da sola e, mentre sei in marcia, aggiorna i dati
  da sola circa ogni minuto, senza che tu debba toccare niente. A vettura ferma o in ricarica non
  cambia nulla rispetto a prima. Tutto questo avviene **solo a lettura**: non viene inviato alcun
  comando all'auto e non si consuma la batteria. Funziona con l'interruttore "Aggiornamento
  automatico" acceso (come già era).

### 🇬🇧 English

- **Your car's data now updates by itself while you drive.** Until now, during a trip, values like
  battery, distance travelled and range stayed frozen until you manually pressed the "Refresh full
  status" button: a moving car doesn't send updates on its own. Now the integration notices this by
  itself and, while you're driving, refreshes the data roughly every minute with no action from you.
  When the car is parked or charging nothing changes compared to before. This is **read-only**: no
  command is ever sent to the car and it doesn't drain the battery. It works with the "Automatic
  update" switch turned on (as it already was).

## v1.5.21 — 2026-06-23

### 🇮🇹 Italiano

- **Risolto: non si riusciva più ad aggiungere l'integrazione (errore "not_implemented").**
  Chi installava l'integrazione da zero, alla voce **Aggiungi integrazione → Omoda 9 / Jaecoo**,
  riceveva subito un errore "not_implemented" e non riusciva a inserire email e PIN. La schermata
  di accesso non veniva proposta per niente. Ora la procedura di configurazione (email → codice
  ricevuto via mail → eventuale scelta dell'auto) funziona di nuovo correttamente. Chi aveva già
  configurato l'integrazione in precedenza non era interessato dal problema.

### 🇬🇧 English

- **Fixed: the integration could no longer be added (error "not_implemented").**
  Anyone installing the integration from scratch, under **Add integration → Omoda 9 / Jaecoo**,
  immediately got a "not_implemented" error and couldn't enter their email and PIN. The login
  screen wasn't shown at all. The setup process (email → code received by mail → optional vehicle
  selection) now works correctly again. Anyone who had already configured the integration was not
  affected by this problem.

## v1.5.20 — 2026-06-23

- **Nomi delle entità in italiano o inglese, in automatico secondo la lingua di Home
  Assistant.** Finora i nomi delle entità (Batteria, Autonomia, Porte…) erano sempre in
  italiano. Ora ogni entità è **tradotta**: chi usa Home Assistant in inglese vede "Battery",
  "Total range", "Front left door"…, chi lo usa in italiano vede "Batteria", "Autonomia
  totale", "Porta anteriore SX". Il nome del veicolo fa da prefisso (es. **"Omoda 9 Battery"**,
  o **"Jaecoo 7 Battery"** per chi ha un Jaecoo). `entity_id`, storico, automazioni e dashboard
  **non cambiano**. (Se avevi rinominato a mano qualche entità, il tuo nome personalizzato
  resta e ha la precedenza.)

## v1.5.19 — 2026-06-23

- **Il dispositivo prende il nome reale della tua auto (Omoda 9, Jaecoo 7…).** Prima il
  dispositivo si chiamava sempre "Omoda 9", anche per chi ha un Jaecoo. Ora il nome (e
  marca/modello) vengono **rilevati automaticamente dall'auto** — è lo stesso nome che vedi
  nell'app. Se preferisci, puoi cambiarlo a mano in **Impostazioni → Dispositivi e servizi →
  Omoda 9 / Jaecoo → Configura → "Nome veicolo"**. Gli `entity_id`, lo storico, le automazioni
  e le dashboard **non cambiano** (il dispositivo è identificato dal numero di telaio).

## v1.5.18 — 2026-06-23

- **Il sensore "Connessa" si chiama ora "Connessione".** È sempre lo stesso sensore (uno
  solo, con stato **Connesso/Disconnesso**): il nome neutro si legge meglio quando l'auto
  è offline. Niente di tecnico cambia e i riferimenti esistenti restano validi.

## v1.5.17 — 2026-06-23

- **"Autonomia totale" corretta + nuovo dato "Autonomia benzina".** Il valore che
  l'integrazione chiamava "Autonomia totale" (215 km) in realtà era **solo l'autonomia
  a benzina**, non la somma con l'elettrico: lo si è verificato perché restava fermo a
  215 km mentre l'autonomia elettrica calava (e il serbatoio era invariato). Ora:
  **"Autonomia benzina"** mostra i km col solo motore termico, e **"Autonomia totale"**
  mostra il valore corretto = **elettrico + benzina** (es. 27 + 215 = 242 km).
- **Pressione gomme in bar (come nell'app).** Le quattro pressioni degli pneumatici ora
  sono mostrate in **bar** invece che in kPa (es. 2,79 bar invece di 279 kPa), così
  coincidono con quanto vedi nell'app dell'auto. Potresti vedere una notifica una-tantum
  di "unità cambiata": si risolve da sola, lo storico viene convertito automaticamente.

## v1.5.16 — 2026-06-23

- **L'aggiornamento automatico della ricarica ora parte subito anche dopo un riavvio
  di Home Assistant.** Nella versione precedente, se riavviavi Home Assistant mentre
  l'auto era già in carica, il monitoraggio in tempo reale poteva non avviarsi da solo
  finché non scattava il controllo periodico (anche mezz'ora dopo) — perché l'auto, da
  ferma, non "annuncia" nulla. Ora, **pochi secondi dopo l'avvio**, l'integrazione fa
  una lettura: se trova l'auto in carica (o in marcia) **fa partire immediatamente**
  l'aggiornamento ogni paio di minuti. Sempre in sola lettura, nessun comando all'auto.

## v1.5.15 — 2026-06-23

- **Piccola regolazione del controllo periodico durante la ricarica (ogni 30 minuti
  invece di 39).** È solo una rete di sicurezza: a seguire la carica in tempo reale
  ci pensa già l'aggiornamento automatico ogni paio di minuti introdotto qui sopra.
  Nessun cambiamento visibile nell'uso di tutti i giorni.

## v1.5.14 — 2026-06-23

- **La carica si segue da sola: mentre l'auto è attaccata alla colonnina, batteria,
  tempo che manca alla fine e potenza di ricarica si aggiornano automaticamente.**
  Prima, anche durante la ricarica i dati potevano restare "fermi" all'ultimo valore
  per ore (l'auto non li manda da sola): bisognava premere "Aggiorna stato completo"
  per vederli. Ora, **appena colleghi il cavo, l'integrazione inizia a rileggere i
  dati di carica ogni paio di minuti** e li tiene aggiornati per tutta la durata della
  ricarica — vedi la percentuale che sale e il tempo residuo che scende senza fare
  nulla. Quando stacchi il cavo, smette da sola. Tutto in sola lettura: **nessun
  comando viene inviato all'auto** (durante la carica i dati veri sono già disponibili).

## v1.5.13 — 2026-06-23

- **I chilometri e la batteria ora si aggiornano da soli quando guidi.** Era
  emerso che l'odometro restava "fermo" all'ultimo valore e la batteria sembrava
  bloccata. Il motivo: l'auto comunica i dati **veri** (chilometri totali, carica
  della batteria, tensione) **solo quando l'alta tensione è accesa** — cioè mentre
  la guidi o la ricarichi. A macchina parcheggiata e spenta non c'è nessun dato
  nuovo da leggere (vale anche per l'app ufficiale). Ora, **appena l'auto si
  accende o va in carica, l'integrazione legge i dati freschi più volte di
  seguito**, così i chilometri salgono e la batteria si aggiorna **automaticamente
  durante e dopo ogni viaggio**, senza che tu debba fare nulla.
- **Nuovo pulsante "Aggiorna stato completo".** Se vuoi vedere subito i
  chilometri e la batteria aggiornati mentre l'auto è parcheggiata, premilo:
  accende il **clima per circa un minuto** (è l'unico modo per "risvegliare"
  l'alta tensione), legge i dati reali e poi **rispegne il clima da solo**. Da
  usare solo quando ti serve il dato fresco al volo: nell'uso normale non serve,
  perché ora si aggiorna da sé quando guidi.
- **Niente più "batteria 0%" fuorviante.** Se l'integrazione non ha ancora mai
  letto una carica reale, mostra **"sconosciuto"** invece di un falso 0% — finché
  non arriva il primo dato vero (al primo viaggio/ricarica o col pulsante qui
  sopra).

## v1.5.12 — 2026-06-22

- **La batteria non va più a 0 quando l'auto è parcheggiata.** Quando l'auto è
  ferma e spenta non comunica la carica reale della batteria (manda uno "zero"
  segnaposto): prima questo faceva apparire la **batteria allo 0%** e la
  **tensione/corrente** dell'alta tensione azzerate. Ora l'integrazione riconosce
  questi valori finti e **mantiene l'ultimo valore reale** — esattamente come fa
  l'app ufficiale, che mostra sempre l'ultima carica nota. I valori "veri" di
  batteria, tensione, corrente e consumo elettrico tornano ad aggiornarsi da soli
  quando l'auto è **in marcia o in ricarica** (gli unici momenti in cui l'auto li
  trasmette davvero).

## v1.5.11 — 2026-06-22

- **Login e avvio più robusti.** Migliorata la stabilità in alcune situazioni
  poco comuni: se il server dell'auto risponde in modo inatteso durante l'invio
  del codice OTP o la verifica del captcha, ora l'integrazione **riprova invece
  di bloccarsi**. All'avvio, se qualcosa va storto, **non lascia più processi o
  controlli automatici "appesi"** in sottofondo, e durante lo spegnimento fa
  pulizia in modo più ordinato. Il file con le credenziali dell'auto viene salvato
  in modo **a prova di interruzione** (non può più corrompersi se Home Assistant
  si chiude proprio in quel momento). Infine, quando spegni l'interruttore
  **"Aggiornamento automatico"**, l'aggiornamento periodico si ferma **davvero**,
  senza più riattivarsi da solo. Sono tutti miglioramenti "dietro le quinte": l'uso
  di tutti i giorni non cambia.

## v1.5.10 — 2026-06-22

- **Più facile chiedere aiuto se qualcosa non va.** Aggiunto il pulsante **"Scarica
  diagnostica"** nella pagina dell'integrazione (menù ⋮): con un clic scarichi un file da
  inviare per farti aiutare, **già reso anonimo** — la tua email, il PIN, il numero di
  telaio e soprattutto la **posizione dell'auto** sono nascosti automaticamente, e di
  password e certificati non viene mai mostrato il contenuto. Nel manuale (README) trovi ora
  una sezione **"Risoluzione problemi"** che spiega in parole semplici dove trovare i log e
  come inviarli in sicurezza.

## v1.5.9 — 2026-06-22

- **"Raffredda tutto" e "Riscalda tutto" ora si spengono davvero del tutto (sedili
  posteriori inclusi).** Per spegnere tutto usa lo stesso pulsante **"Raffredda tutto"**
  (o "Riscalda tutto") e mettilo su **OFF**: così spegni aria + **tutti** i sedili, anche
  quelli posteriori. ⚠️ Attenzione: il pulsante **"Clima"** spegne solo l'aria condizionata
  (e, sull'auto, i sedili anteriori che le sono collegati), ma **non** i sedili posteriori —
  quelli sono indipendenti. Inoltre l'interruttore ora **resta acceso** mentre il preset è
  attivo (prima si rispegneva subito e non riuscivi a comandarne lo spegnimento), e **si
  spegne da solo** dopo circa 15 minuti, quando l'auto chiude il preset. Anche lo spegnimento
  sveglia l'auto da solo, così arriva fino ai sedili posteriori.

## v1.5.8 — 2026-06-22

- **"Raffredda tutto" e "Riscalda tutto": basta un tocco, anche con l'auto parcheggiata.**
  I sedili, il volante e gli sbrinatori l'auto li accende solo quando è **sveglia**: se la
  premevi a vettura ferma da un po', l'auto era "addormentata" e rispondeva con un errore.
  Ora la macro **sveglia l'auto da sola e aspetta qualche secondo** prima di mandare il
  comando, quindi ti basta premere una volta e funziona (ci mette ~40 secondi a partire:
  è normale, sta svegliando l'auto). Inoltre il pulsante ora fa **sempre l'accensione**
  quando lo premi: prima, se era rimasto "acceso", il tocco mandava per sbaglio lo
  spegnimento (che dava errore). 💡 Per il momento miglior risultato, usalo con l'**auto
  spenta**.

## v1.5.7 — 2026-06-22

- **"Raffredda tutto" e "Riscalda tutto" ora accendono DAVVERO tutto** (e si corregge
  quanto detto nelle due note precedenti). Le macro tornano a fare ciò che ti aspetti, con
  un unico comando come l'app ufficiale:
  - **❄️ Raffredda tutto** = aria condizionata al massimo freddo **+ ventilazione di tutti
    e quattro i sedili**.
  - **🔥 Riscalda tutto** = aria calda al massimo **+ riscaldamento di tutti e quattro i
    sedili + volante riscaldato + sbrinatore parabrezza + sbrinatore lunotto**.

  Perché prima sembravano "non disponibili": i comandi del comfort (sedili, volante,
  sbrinatori) l'auto li accetta **solo a vettura spenta e con il clima acceso**. Se l'auto
  è accesa/occupata, o se si prova ad accendere un sedile col clima spento, l'auto li
  rifiuta con un errore — e questo mi aveva tratto in inganno facendomi credere, a torto,
  che certi comfort non fossero installati. Verificato dal vivo a motore spento: clima,
  tutti i sedili, volante, parabrezza e lunotto rispondono correttamente. **Consiglio
  d'uso:** lancia "Raffredda/Riscalda tutto" con l'**auto spenta**.

## v1.5.6 — 2026-06-21

- **"Raffredda tutto" e "Riscalda tutto" ora sono vere macro su misura per la tua auto.**
  Abbiamo provato sul campo, uno per uno, tutti i comfort dell'auto per vedere quali
  rispondono davvero ai comandi a distanza. Su questa vettura risultano installati (e
  funzionanti) soltanto il **sedile guidatore ventilato** e lo **sbrinatore del lunotto**;
  riscaldamento dei sedili, volante riscaldato, sbrinatore del parabrezza e ventilazione
  dei sedili passeggero/posteriori **non sono presenti** e andavano solo in errore. Quindi
  adesso:
  - **❄️ Raffredda tutto** = aria condizionata al massimo freddo **+ ventilazione del
    sedile guidatore**.
  - **🔥 Riscalda tutto** = aria calda al massimo **+ sbrinatore del lunotto**.

  I comandi vengono inviati **in sequenza, uno alla volta** (l'auto ne esegue uno per
  volta), quindi la macro impiega qualche secondo in più a completarsi ma non si "accavalla"
  e non genera più gli errori che vedevi. Niente più tentativi sui comfort che la tua auto
  non ha.

## v1.5.5 — 2026-06-21

- **"Raffredda tutto" e "Riscalda tutto" ora funzionano davvero.** Prima questi due
  pulsanti usavano un comando "tutto-in-uno" che la tua auto non riesce a eseguire: dava un
  finto "comando inviato" e subito dopo un errore, e il clima non partiva. Ora usano il
  comando del climatizzatore semplice (lo stesso, affidabile, del termostato "Clima"):
  **"Raffredda tutto"** accende l'aria al massimo freddo, **"Riscalda tutto"** al massimo
  caldo (e accende anche gli sbrinatori di parabrezza e lunotto). Il riscaldamento/la
  ventilazione dei **sedili** non fanno più parte di questi due pulsanti — l'auto non li
  accettava in quel comando — ma restano comandabili dai loro interruttori dedicati.

## v1.5.4 — 2026-06-21

- **Niente più comandi accavallati se premi troppe volte.** L'auto esegue **un comando
  alla volta**: ora, finché un comando è in corso, le pressioni successive vengono
  ignorate con un avviso ("attendi qualche secondo, un comando è già in corso") invece di
  accavallarsi e farsi rifiutare dall'auto come "occupato". Appena l'auto conferma, il
  comando successivo riparte subito. Vale per tutti i comandi che **agiscono** sull'auto
  (clima, serrature, baule/finestrini/tetto, ricarica, sedili, antifurto, "Raffredda/
  Riscalda tutto").

## v1.5.3 — 2026-06-21

- **L'aggiornamento automatico ora parte SPENTO.** Per non svegliare l'auto senza che tu
  lo voglia, la funzione "Aggiornamento automatico" è **disattivata di default**: quando la
  vuoi, accendi tu l'interruttore **"Aggiornamento automatico"** (e regoli gli intervalli
  dalle opzioni). Resta valido il pulsante "Aggiorna posizione" per un aggiornamento manuale.

## v1.5.2 — 2026-06-21

- **Aggiornamento automatico dei dati dell'auto.** Ora Home Assistant aggiorna **da solo**,
  a intervalli regolari, le informazioni dell'auto (posizione, batteria, autonomia, gomme,
  consumi…) svegliando brevemente la vettura. Di **default ogni 60 minuti**, e **ogni 39
  minuti quando l'auto è attaccata alla colonnina** (così segui meglio la ricarica).
  - Puoi cambiare i due intervalli — o disattivarli mettendo **0** — dalle opzioni
    dell'integrazione: **Impostazioni → Dispositivi e servizi → Omoda 9 → Configura**.
  - C'è anche un nuovo interruttore **"Aggiornamento automatico"** per accendere o spegnere
    tutto con un tocco, senza entrare nelle opzioni.
  - ⚠️ Quando è attivo l'auto viene svegliata periodicamente: comodo per avere dati sempre
    freschi, ma comporta un piccolo consumo della batteria a vettura ferma. Se preferisci,
    spegnilo e aggiorna a mano col pulsante "Aggiorna posizione".

- **Stati della ricarica più chiari.** Le informazioni "Stato ricarica", "Presa ricarica
  rapida" e "Ricarica programmata" ora mostrano un **testo leggibile** (es. "Non in ricarica",
  "In ricarica", "Collegata") invece di un codice numerico.

## v1.5.1 — 2026-06-21

- **Correzione: le nuove informazioni dall'auto ora compaiono davvero.** Per un problema
  tecnico, i dati che l'auto comunica quando è sveglia — autonomia, chilometri, pressione e
  temperatura delle gomme, consumi, carburante, tensione della batteria, e perfino **livello
  batteria e velocità** — non venivano letti e restavano vuoti. Ora vengono letti
  correttamente: i relativi sensori si popolano non appena l'auto si sveglia.

- **Avviso quando un comando all'auto non riesce (opzionale).** Ora è disponibile un
  "blueprint" pronto all'uso: se lo importi, ricevi un **popup in Home Assistant** (e, se
  vuoi, una notifica sul telefono) ogni volta che un comando all'auto non va a buon fine —
  ad esempio quando l'auto è occupata da un altro comando, non è raggiungibile, o la
  sessione è scaduta. Riconosce solo i veri errori, quindi non disturba quando va tutto
  bene. L'integrazione di suo continua a **non inviare nessuna notifica**: il blueprint è
  del tutto facoltativo e si attiva con un clic dal README.

## v1.5.0 — 2026-06-21

- **Tante nuove informazioni che arrivano direttamente dall'auto.** Quando l'auto è
  sveglia, Home Assistant ora mostra molti più dati utili, finora non disponibili:
  - **Autonomia**: quanti chilometri restano in elettrico e in totale (elettrico + benzina).
  - **Chilometri totali** dell'auto (contachilometri) e chilometri percorsi in ibrido.
  - **Gomme**: pressione e temperatura di ognuna delle quattro ruote, con un **avviso**
    dedicato per ciascuna gomma se qualcosa non va.
  - **Consumi medi**, sia di benzina sia di energia elettrica.
  - **Carburante rimasto** nel serbatoio (in litri).
  - **Batteria di trazione**: tensione e corrente (informazioni tecniche).
  - **Clima**: la temperatura impostata sui due lati dell'abitacolo.
  - **Ricarica**: stato della presa, stato della ricarica programmata e, quando l'auto è
    in carica, il tempo che manca al termine.
  - **Avviso "batteria scarica"** quando il livello è basso.

  Sono tutte informazioni di **sola lettura** (l'auto non riceve nessun comando) e si
  aggiornano quando l'auto si sveglia. Le trovi sotto il dispositivo "Omoda 9": quelle
  più tecniche (temperature gomme, tensione batteria, ecc.) sono raggruppate tra i
  "dettagli diagnostici".

## v1.4.0 — 2026-06-21

- **Nuovo interruttore "Antifurto".** Puoi accendere e spegnere l'allarme antifurto
  dell'auto direttamente da Home Assistant. Quando è acceso, l'auto fa scattare l'allarme
  e ti avvisa in caso di movimento non autorizzato del veicolo, tentativi di scasso delle
  porte, rottura dei finestrini o altre potenziali effrazioni. L'interruttore mostra anche
  se l'antifurto è già attivo (lo legge dall'auto).
- **Due nuovi tasti "comfort": Raffredda tutto e Riscalda tutto.** Con un solo
  interruttore prepari l'abitacolo per la stagione. **"Raffredda tutto"** accende il
  clima al massimo del freddo e avvia la **ventilazione di tutti i sedili**.
  **"Riscalda tutto"** accende il clima al massimo del caldo e attiva insieme lo
  **sbrinamento di parabrezza e lunotto, il volante riscaldato e il riscaldamento di
  tutti i sedili**. I due tasti si escludono a vicenda: accendendone uno, l'altro si
  spegne. Comodi per scaldare o rinfrescare l'auto in un colpo solo prima di partire.
- **Ricarica programmata: ora scegli l'orario al minuto.** L'ora di inizio della
  ricarica programmata era un cursore a sole ore intere (es. solo "le 8"); adesso c'è un
  vero **selettore d'orario** "Ricarica · orario di inizio" con cui imposti anche i minuti
  (es. **07:45**). La durata resta il cursore in ore. ⚠️ Dopo l'aggiornamento il vecchio
  cursore "Ricarica · ora di inizio" resterà "non disponibile" e si può togliere: al suo
  posto usa il nuovo selettore d'orario.

## v1.3.0 — 2026-06-21

- **Il clima ora si imposta alla temperatura che vuoi.** Prima c'era un semplice
  interruttore che accendeva il clima fisso a 21°; ora trovi un vero **termostato**:
  scegli la temperatura desiderata (da 16° a 30°) e l'auto la applica, riscaldando o
  raffreddando l'abitacolo. Puoi anche regolare per quanti minuti deve restare acceso.
  ⚠️ Dopo l'aggiornamento, al posto del vecchio interruttore "Clima" comparirà il nuovo
  termostato "Clima": se avevi messo il vecchio interruttore in una schermata, sostituiscilo
  con il nuovo (il vecchio resterà "non disponibile" e si può togliere).
- **Comandi per la ricarica elettrica.** Due nuovi interruttori: **"Ricarica"** per
  avviare o fermare subito la ricarica, e **"Ricarica programmata"** per far caricare
  l'auto in una fascia oraria scelta (imposti ora di inizio e durata con i due cursori
  dedicati). Funzionano quando l'auto è collegata alla colonnina/wallbox.
- **I sedili e gli sbrinamenti non si toccano più accendendo il clima.** Il nuovo
  termostato agisce solo sull'aria: riscaldamento sedili, volante e sbrinamenti restano
  controlli a parte e non vengono spenti quando accendi o spegni il clima.

## v1.2.0 — 2026-06-21

- **Comandi anche per i sedili passeggero e posteriori.** Finora potevi accendere e
  spegnere solo il sedile del posto guida; ora trovi gli stessi interruttori (caldo e
  aria) anche per il **passeggero** e per i due **sedili posteriori** (sinistro e
  destro). Come per il guida, su ogni sedile caldo e aria si escludono a vicenda.
- **Nuove informazioni dall'auto.** Compaiono tre nuove indicazioni quando l'auto è
  sveglia: se la **spina di ricarica è collegata**, se il **motore è acceso**, e lo
  stato di movimento del **tetto apribile** (quest'ultimo tra i dettagli tecnici).
- **L'esito dei comandi ora arriva davvero dall'auto.** Prima la voce "Esito comando"
  diceva solo che il comando era stato *accettato* dal server; adesso, quando l'auto
  risponde, viene aggiornata con l'esito **reale**: comando eseguito e confermato,
  ancora in corso, oppure non riuscito (con il motivo segnalato dall'auto).

- **Riscaldamenti e sbrinamenti ora si spengono con un tocco.** Sbrinamento
  parabrezza, sbrinamento lunotto, volante riscaldato e i sedili (caldo/aria) del
  posto guida diventano dei normali interruttori: prima potevi solo accenderli (e si
  spegnevano da soli dopo 15 minuti), ora li accendi **e li spegni** quando vuoi,
  vedendo lo stato acceso/spento nella stessa card.
- **Sedile guida più furbo.** Caldo e aria del sedile guida non possono stare accesi
  insieme: accendendo l'aria il riscaldamento si spegne (e viceversa), proprio come
  fa l'auto — e ora la card lo mostra subito.
- **Tasto "Sveglia auto" più affidabile.** Se la sveglia via SMS non risponde
  (capitava che l'auto restasse a riposo), l'integrazione prova in automatico a
  contattare l'auto con la richiesta di posizione, che la sveglia al primo colpo e
  in più aggiorna la posizione GPS.
- **Schermata più pulita.** Un paio di indicazioni che l'auto non comunica mai da
  ferma (tendina del tetto, riscaldamento parabrezza) sono state spostate tra i
  dettagli diagnostici, così non restano "in dubbio" tra i controlli principali.

## v1.0.0 — 2026-06-21

- **Versione 1.0: l'integrazione diventa stabile e più affidabile.** Tante piccole
  rifiniture sotto il cofano per un funzionamento più solido di tutti i giorni.
- **Connessione all'auto più robusta.** Se il collegamento cade viene ristabilito
  da solo, senza lasciare l'integrazione "appesa"; meno disconnessioni inattese e
  un avvio più pulito quando l'auto non è raggiungibile.
- **Accesso più sicuro e protetto.** Migliorata la gestione dell'accesso per evitare
  che la sessione si perda da sola; aggiunta una protezione che ferma i tentativi se
  il PIN risulta sbagliato, così l'account non rischia il blocco.
- **Informazioni sempre veritiere dopo un riavvio.** Dopo aver riavviato Home
  Assistant, gli esiti dei comandi non mostrano più un risultato vecchio: o è
  aggiornato o resta vuoto, niente informazioni fuorvianti.
- **Stati più coerenti.** Porte, serratura, baule, finestrini, tetto e clima
  vengono interpretati in modo uniforme: niente più "acceso" o "aperto" mostrati
  per sbaglio quando il dato non c'è.
- **Comandi con conferma a schermo.** Quando premi un comando (chiudi/apri/clima)
  la card si aggiorna subito e, se qualcosa non va a buon fine, te lo segnala invece
  di restare bloccata su uno stato mai raggiunto.
- **Pronta anche fuori dall'Europa.** In fase di configurazione si può ora indicare
  il server dell'auto della propria zona, così l'integrazione funziona anche fuori
  dalla regione europea.
- **La posizione GPS resta salvata.** L'ultima posizione nota viene conservata e
  ricompare dopo un riavvio, invece di sparire.

## v0.3.0 — 2026-06-21

- **La serratura ora è un vero lucchetto.** La blocchi e la sblocchi con un solo
  tocco, e vedi lo stato (chiusa/aperta) nella stessa card. Prima erano
  un'indicazione separata e due pulsanti distinti.
- **Il clima ora è un interruttore.** Lo accendi e lo spegni come una normale luce
  (l'accensione avvia la climatizzazione a 21° per 15 minuti).
- **Baule, finestrini e tetto si comandano come tapparelle.** Apri e chiudi
  direttamente, con stato e comando insieme. (La ventilazione finestrini resta un
  pulsante a parte.)
- **Schermata principale più pulita.** Le informazioni di servizio — esiti dei
  comandi, orari dell'ultimo contatto, stato della sessione e campo del codice OTP —
  sono state spostate nella sezione "diagnostica" del dispositivo, così in primo
  piano restano solo i controlli che usi davvero.
- **Andamenti nel tempo per batteria e velocità.** Ora vengono registrate
  storicamente: puoi vederne i grafici e usarle nelle statistiche.

## v0.2.6 — 2026-06-21

- Aggiunto questo elenco delle novità (changelog), così a ogni aggiornamento
  vedi in chiaro cosa è cambiato.
- README più chiaro: per iniziare bastano **email + PIN** del tuo account
  (più un **codice OTP** via email al primo accesso). Tutto il resto è automatico.

## v0.2.4 — 21 giugno 2026

- **Certificati automatici.** Non devi più procurarti o inserire alcun
  certificato: l'integrazione li installa da sola in base alla tua regione.
  L'attivazione richiede ora soltanto email e PIN.

## v0.2.1 — 21 giugno 2026

- **Accesso più semplice.** Ora puoi accedere direttamente da Home Assistant
  inserendo email e PIN e confermando il codice OTP ricevuto via email, senza
  strumenti esterni e su qualunque installazione (anche Home Assistant OS).

## Versioni precedenti

- Prime versioni dell'integrazione: collegamento dell'auto a Home Assistant
  (stato porte/serrature/baule/cofano/finestrini/tetto/clima/sedili), posizione
  GPS su richiesta, batteria e velocità ad auto in marcia, pulsanti dei comandi.
