# Confronto baseline — sintetico vs reale

## Baseline
Configurazione Arena che replica la forma del gate corrente senza modificarlo.

| Dataset | Casi | Precision REAL_DEMAND | Recall REAL_DEMAND | FP vendor |
|---|---:|---:|---:|---:|
| synthetic | 24 | 1.000 | 0.875 | 0/8 |
| real-review | 24 | 1.000 | 0.250 | 0/8 |

La recall scende di **0,625** (62,5 punti percentuali) sul campione reale.

## REAL_DEMAND proposti: condizioni storicamente mancanti
Conteggio sui soli 8 casi REAL_DEMAND del campione reale; un caso può avere più condizioni mancanti:

- PAID_DEMAND + (BUY_INTENT oppure PAIN): 7
- almeno 1 fonte buyer commercialmente forte: 4
- stesso problema concreto: 3
- almeno 3 domini indipendenti: 2
- almeno 2 fonti fresche: 2
- tagger corrente/fidato: 1

## Interpretazione
Il sintetico contiene esempi costruiti con segnali espliciti e co-localizzati nella stessa frase, quindi il marker evaluator li riconosce facilmente.

Nel reale i segnali sono spesso **parziali o distribuiti**:
- pain senza paid demand;
- paid signal senza buyer intent sufficientemente chiaro;
- segnali validi ma associati a un problem bucket troppo generico;
- un singolo dominio forte senza convergenza indipendente;
- record legacy non più affidabili dopo la migrazione del tagger.

Il caso più vicino al gate resta `manual_data_entry`: gap 70, BUY_INTENT + PAID_DEMAND e una fonte forte, ma soltanto 1 dominio indipendente e 1 fonte fresca. Il gate richiede 3 domini/21 giorni e 2 freschi/7 giorni.

## Limite metodologico
L'evaluator Arena opera sul singolo caso testuale; il gate produzione opera anche a livello di cluster e convergenza temporale. Quindi questa baseline è un **proxy di classificazione**, non una replica eseguibile del gate di produzione. Nessun risultato viene adottato automaticamente.
