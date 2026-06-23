# Entità Home Assistant generate dal custom component `omoda9`

> Device unico **"Omoda 9"** (identificato dal VIN). Totale: **57 entità** (0 unavailable, v0.3.0).
> L'`entity_id` deriva dallo slug del nome (`omoda9_*`), tranne i pulsanti comando che usano `omoda9_<chiave>`.

---

## 🔘 BINARY_SENSOR — 23 (stati on/off, aperto/chiuso)

### Porte (4)
| # | entity_id | Nome |
|---|---|---|
| 1 | `binary_sensor.omoda9_porta_anteriore_sx` | Porta anteriore SX |
| 2 | `binary_sensor.omoda9_porta_anteriore_dx` | Porta anteriore DX |
| 3 | `binary_sensor.omoda9_porta_posteriore_sx` | Porta posteriore SX |
| 4 | `binary_sensor.omoda9_porta_posteriore_dx` | Porta posteriore DX |

### Aperture (2)
| # | entity_id | Nome |
|---|---|---|
| 5 | `binary_sensor.omoda9_cofano` | Cofano |
| 6 | `binary_sensor.omoda9_portellone_in_movimento` | Portellone in movimento |

### Finestrini / tetto (5)
| # | entity_id | Nome |
|---|---|---|
| 7 | `binary_sensor.omoda9_finestrino_anteriore_sx` | Finestrino anteriore SX |
| 8 | `binary_sensor.omoda9_finestrino_anteriore_dx` | Finestrino anteriore DX |
| 9 | `binary_sensor.omoda9_finestrino_posteriore_sx` | Finestrino posteriore SX |
| 10 | `binary_sensor.omoda9_finestrino_posteriore_dx` | Finestrino posteriore DX |
| 11 | `binary_sensor.omoda9_tendina_tetto` | Tendina tetto |

### Clima / comfort (9)
| # | entity_id | Nome |
|---|---|---|
| 12 | `binary_sensor.omoda9_purificazione_aria` | Purificazione aria |
| 13 | `binary_sensor.omoda9_sbrinamento_parabrezza` | Sbrinamento parabrezza |
| 14 | `binary_sensor.omoda9_riscaldamento_parabrezza` | Riscaldamento parabrezza |
| 15 | `binary_sensor.omoda9_riscaldamento_lunotto` | Riscaldamento lunotto |
| 16 | `binary_sensor.omoda9_riscaldamento_volante` | Riscaldamento volante |
| 17 | `binary_sensor.omoda9_riscaldamento_sedile_guida` | Riscaldamento sedile guida |
| 18 | `binary_sensor.omoda9_riscaldamento_sedile_passeggero` | Riscaldamento sedile passeggero |
| 19 | `binary_sensor.omoda9_ventilazione_sedile_guida` | Ventilazione sedile guida |
| 20 | `binary_sensor.omoda9_ventilazione_sedile_passeggero` | Ventilazione sedile passeggero |

### Diagnostici (3)
| # | entity_id | Nome |
|---|---|---|
| 21 | `binary_sensor.omoda9_connessa` | Connessa (connettività) |
| 22 | `binary_sensor.omoda9_auto_sveglia` | Auto sveglia |
| 23 | `binary_sensor.omoda9_sessione` | Sessione |

---

## 📊 SENSOR — 15

### Livelli sedili posteriori (6)
| # | entity_id | Nome |
|---|---|---|
| 1 | `sensor.omoda9_riscaldamento_sedile_post_sx` | Riscaldamento sedile post. SX |
| 2 | `sensor.omoda9_riscaldamento_sedile_post_dx` | Riscaldamento sedile post. DX |
| 3 | `sensor.omoda9_riscaldamento_sedile_post_centrale` | Riscaldamento sedile post. centrale |
| 4 | `sensor.omoda9_ventilazione_sedile_post_sx` | Ventilazione sedile post. SX |
| 5 | `sensor.omoda9_ventilazione_sedile_post_dx` | Ventilazione sedile post. DX |
| 6 | `sensor.omoda9_ventilazione_sedile_post_centrale` | Ventilazione sedile post. centrale |

### Marcia / batteria (2)
| # | entity_id | Nome | Unità |
|---|---|---|---|
| 7 | `sensor.omoda9_batteria` | Batteria | % |
| 8 | `sensor.omoda9_velocita` | Velocità | km/h |

### Diagnostici (7)
| # | entity_id | Nome |
|---|---|---|
| 9 | `sensor.omoda9_stato_sessione` | Stato sessione |
| 10 | `sensor.omoda9_esito_comando` | Esito comando |
| 11 | `sensor.omoda9_esito_sveglia` | Esito sveglia |
| 12 | `sensor.omoda9_esito_sonda_posizione` | Esito sonda posizione |
| 13 | `sensor.omoda9_ultimo_contatto` | Ultimo contatto (timestamp) |
| 14 | `sensor.omoda9_ultima_sveglia` | Ultima sveglia (timestamp) |
| 15 | `sensor.omoda9_ultima_posizione` | Ultima posizione (timestamp) |

---

## 🔒 LOCK — 1
| # | entity_id | Nome |
|---|---|---|
| 1 | `lock.omoda9_serratura` | Serratura (blocca/sblocca porte) |

## 🎚️ SWITCH — 1
| # | entity_id | Nome |
|---|---|---|
| 1 | `switch.omoda9_clima` | Clima (ON = 21° per 15 min) |

## 🪟 COVER — 3
| # | entity_id | Nome |
|---|---|---|
| 1 | `cover.omoda9_baule` | Baule (apri/chiudi) |
| 2 | `cover.omoda9_finestrini` | Finestrini (apri/chiudi tutti e 4) |
| 3 | `cover.omoda9_tetto` | Tetto (apri/chiudi) |

## 📍 DEVICE_TRACKER — 1
| # | entity_id | Nome |
|---|---|---|
| 1 | `device_tracker.omoda9_posizione` | Posizione GPS |

## ⌨️ TEXT — 1
| # | entity_id | Nome |
|---|---|---|
| 1 | `text.omoda9_codice_otp` | Codice OTP (recupero sessione) |

---

## 🔲 BUTTON — 12 (comandi)

### Comandi auto (8)
| # | entity_id | Nome |
|---|---|---|
| 1 | `button.omoda9_defrost_parabrezza` | Sbrina parabrezza |
| 2 | `button.omoda9_defrost_lunotto` | Sbrina lunotto |
| 3 | `button.omoda9_volante_caldo` | Volante riscaldato |
| 4 | `button.omoda9_sedile_guida_caldo` | Sedile guida riscaldato |
| 5 | `button.omoda9_sedile_guida_aria` | Sedile guida ventilato |
| 6 | `button.omoda9_finestrini_ventila` | Ventila finestrini |
| 7 | `button.omoda9_trova_auto` | Trova auto (lampeggio) |
| 8 | `button.omoda9_localizza` | Localizza auto (GPS) |

### Azioni di servizio (4)
| # | entity_id | Nome |
|---|---|---|
| 9 | `button.omoda9_sveglia_auto` | Sveglia auto |
| 10 | `button.omoda9_aggiorna_posizione` | Aggiorna posizione |
| 11 | `button.omoda9_richiedi_codice_otp` | Richiedi codice OTP (diagnostico) |
| 12 | `button.omoda9_conferma_otp` | Conferma OTP (diagnostico) |

---

## Riepilogo

| Tipo | N° |
|---|---|
| binary_sensor | 23 |
| sensor | 15 |
| button | 12 |
| cover | 3 |
| lock | 1 |
| switch | 1 |
| device_tracker | 1 |
| text | 1 |
| **TOTALE** | **57** |

> **Nota:** i comandi blocca/sblocca, clima on/off, baule/finestrini/tetto apri/chiudi **non** sono
> pulsanti separati — sono fusi nelle entità "ricche" `lock`, `switch` e `cover` (il tap sull'entità
> invoca lo stesso comando del catalogo).
