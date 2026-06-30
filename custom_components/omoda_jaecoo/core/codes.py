#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
codes.py — Mappa UNICA dei codici di risposta tspconsole/BFF Chery → testo leggibile.

Sorgente di verità per i SOLI testi diagnostici mostrati all'utente (HA/monitor).
Prima della FASE 1 lo stesso codice (es. A07900) aveva 3 significati diversi
sparsi in commands/wake/probe/provision; questa mappa li unifica. NON cambia la
logica dei comandi: i moduli decidono il flusso sui codici, qui c'è solo la
traduzione del codice in una frase.

⚠️ Alcuni codici (in primis A07900) sono CONTESTUALI sul backend Chery: il testo
qui è quello più ricorrente/utile; ogni chiamante può aggiungere contesto.
"""

# Codice → frase leggibile (italiano, per non tecnici).
CODE_MEANING = {
    "000000": "ok ✅",
    "A00079": "command accepted ✅",
    # A00084 (i18n: "No vehicle control command permission"): l'account/veicolo non ha il
    # permesso PER QUEL comando. Visto dal vivo su remoteStart (2026-06-21): la nostra Omoda / Jaecoo
    # non consente l'avvio remoto del motore, mentre clima/serratura/GPS funzionano.
    "A00084": "command not allowed on this car 🚫 (permission denied for this function)",
    "A00089": "invalid taskId ❌ (requires a taskId authenticated by checkPassword)",
    "A00546": "invalid taskId ❌ (incorrect scene in checkPassword)",
    "A00567": "incomplete checkPassword parameters ❌",
    "A00000": "token expired/invalid ❌ (please redo OTP login)",
    "A07312": "wake rate-limit 🚫 (car is refusing further wake requests right now, try again later)",
    # A07900 è contestuale: in poll/probe = auto a riposo; coi comandi = firma o
    # car_token non validi. Testo neutro che copre il caso più frequente.
    "A07900": "car asleep / unreachable (or signature/car_token invalid) ⌛",
}


def meaning(code, default=None):
    """Ritorna la frase leggibile per `code`. Se sconosciuto ritorna `default`
    (o una stringa generica col codice grezzo). Accetta anche code=None/non-str."""
    if code is None:
        return default if default is not None else "nessun codice"
    key = str(code)
    if key in CODE_MEANING:
        return CODE_MEANING[key]
    return default if default is not None else f"codice {key}"


if __name__ == "__main__":
    for c in ("000000", "A00079", "A07900", "A99999", None):
        print(f"{c!s:>8} -> {meaning(c)}")
