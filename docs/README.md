# Custom Lovelace cards — Omoda / Jaecoo

Card companion (opzionali) per l'integrazione `omoda_jaecoo`. Ogni card è un **singolo file**
vanilla JS (nessun build, zero dipendenze), distribuibile come risorsa Lovelace in `config/www/`
e registrata come *Modulo JavaScript*.

| Card | File | Requisiti |
|---|---|---|
| **Charging Energy** — istogramma energia di ricarica (casa verde / fuori casa giallo) con selettore periodo stile Energy | `www/omoda-jaecoo-energy-card.js` | [energy-card-requirements.md](energy-card-requirements.md) |

## Installazione (comune)

1. Copiare il file `.js` in `config/www/`.
2. Impostazioni → Dashboard → ⋮ → Risorse → Aggiungi: URL `/local/<file>.js`, tipo *Modulo JavaScript*.
3. Aggiungere la card a una dashboard (**Aggiungi scheda → Manuale**) con la config YAML della card.

> Aggiornando il file, **bumpare la query version** della risorsa (`?v=N`) per forzare il
> refetch del modulo dal browser (i moduli ES sono cache-ati per URL).

Convenzioni condivise: tutti gli entity_id hanno default sensati derivati dallo slug del nome
entità e sono override-abili nella config; il nucleo logico è isolato in piccoli oggetti puri
(seme OOP) senza dipendenze da DOM/hass, per essere testabile.
