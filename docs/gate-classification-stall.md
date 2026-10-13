# Fase 1 — blocco nella classificazione delle evidenze

## Problema osservato

La PR #215 è stata unita nel commit a718b01 e distribuita l'08/10/2026.
Il primo ciclo della nuova istanza Render tphjr, numero 2896, registra:

- 10:12:43.911 UTC: stack `contains_term → commercial_family_scores →
  commercial_family → route_challenge_evidence → observe_challenge →
  _commercial_evidence_quality → director_run → _autopilot_cycle`.
- 10:13:21.515 UTC: fase `gate` 40066.406 ms wall, 6014.367 ms CPU di processo,
  5716.219 ms CPU del thread.
- 10:13:22.618 UTC: `event_loop_stall lag_ms=40999.998`.
- Checkpoint dello stesso ciclo: 5848.654 ms; ciclo totale: 65468.494 ms.
- Snapshot pubblico catturato alle 10:14:20.322 UTC: primo ciclo completato,
  `codec_offthread=false`, un blocco, ritardo massimo 40999.998 ms.

Lo stack campionato non mostra lzma: la procedura precedente si arresta e il
flag codec resta 0. Il deploy è passato, con Arena verde al primo tentativo,
ma `observation_deploy` risultava false. Lo smoke era successivo al primo ciclo.
Il passaggio dello smoke non prova la scomparsa del blocco.

Una successiva cattura, 10:18:47 UTC, mostra `_observe_model_shadow_raw` nello
stesso percorso del gate; al rientro il lag è 28746.646 ms. Questo punto non
viene modificato in questa PR. La misura non attribuisce tutto il tempo del
gate alla singola chiamata campionata e non prova la causa storica delle 06:50.

## Riproduzione e causa isolata

24 issue sintetiche, corpo di 65535 caratteri ciascuna, routing reale tramite
`route_challenge_evidence`, una sola CPU. Non sono state lette le evidenze
private o le variabili Render. Questa dimensione è una condizione del replay,
non la dimensione misurata delle issue in produzione.

Il classificatore originale esegue 252 ricerche regex per testo, comprese le
parole assenti. Il primo profilo registra 4.725 s nelle ricerche regex su
4.851 s di routing totale. La compilazione regex occupa circa 0.068 s:
nessuna correzione della cache è giustificata e non viene introdotta.

## Correzione

Unica funzione runtime modificata: `commercial_family_scores`.
Un prefiltro verifica l'assenza dei termini letterali prima della ricerca
regex. Ogni possibile corrispondenza passa ancora per `contains_term` e la
regex originale: confini di parola, pesi, inflezioni, ordine e tie-break restano
invariati. I tre termini con regex controllate bypassano il prefiltro.

Per le equivalenze Unicode di IGNORECASE, il solo testo del prefiltro usa
casefold e normalizzazione di i senza punto; le regex continuano a leggere
il testo originale in minuscolo. I termini non ASCII bypassano il prefiltro.
I falsi positivi del prefiltro non cambiano i punteggi: li respinge la regex.
Non ci sono troncamenti, nuovi limiti d'importazione, modifiche a memoria,
gate, soglie, codici, Arene o configurazione Render.

## Prova prima/dopo

Comando: `python scripts/reproduce_gate_classification.py`.
Il riferimento nel test conserva lo scorer precedente, senza prefiltro.
Gli output completi del routing sono identici. Dati in
`gate-classification-replay.json`:

| Misura | Prima | Dopo |
| --- | ---: | ---: |
| Routing wall ms | 5765.285 | 469.083 |
| CPU ms | 5763.382 | 469.044 |
| Regex search calls | 6144 | 288 |
| CPU nelle regex ms | 4918.837 | 232.701 |
| Ritardo massimo loop ms | 5756.121 | 459.422 |

Il replay è locale, sintetico, su una CPU: non simula la quota Render di
0,15 core e non riproduce l'intero primo ciclo autopilot. Non è una prova
che in produzione il ritardo totale sarà già sotto 1 s.

Test rosso con lo scorer precedente: `252 not less than 25` scansioni.
Test verde con la correzione: stesso punteggio, meno di 25 ricerche regex.
Equivalenza verificata su tutti gli alias, sovrapposizioni, confini di parola,
inflezioni, Unicode, testi casuali deterministici e testi dei controlli pubblici.

```text
python -m unittest discover -v
Ran 952 tests in 34.886s
OK
Commerciale 24/24; famiglie 24/24; sfide 12/12
Privacy, gate non regressione e fixture nascoste locali: verdi
```

I set nascosti reali Render e il primo ciclo del candidato non distribuito
restano da verificare. Nessun merge o deploy effettuato dall'agente.

## Misura successiva, solo dopo autorizzazione di Andrea

Il flag codec resta 0. Dopo un eventuale deploy autorizzato, confrontare i log
per la stessa fase gate, il ritardo del primo ciclo, gli stack e lo smoke Arena.
Se resta un blocco, riportare la nuova fase campionata; non trattare il verde
locale o dello smoke come chiusura della Fase 1. Questa PR non autorizza il
deploy e non attiva altre correzioni.
