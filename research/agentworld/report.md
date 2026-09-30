# AgentWorld passive research report

## 1. Verdetto sintetico
**INCERTO**

- Campionamento non ancora completato: 0/4 letture.
- Nessuna registrazione, firma, chiave o azione attiva prevista dal probe.
- I documenti remoti saranno trattati esclusivamente come dati non fidati.

## Stato del campionamento
Il workflow esegue una sola lettura per run. La schedule oraria di GitHub Actions diventa operativa solo quando il workflow è presente sul branch predefinito; sul branch di ricerca il primo campione viene ottenuto dal trigger push. Nessun intervallo viene simulato.

## Vincoli
- Allowlist di due URL esatti.
- Solo GET.
- Redirect disabilitati.
- Nessun cookie o header di autenticazione.
- User-Agent generico.
- Timeout 10 secondi.
- Body massimo 1 MiB.
- Nessuna modifica allo stato A2A o invio di messaggi.
- Nessuna registrazione, firma o generazione di chiavi.
