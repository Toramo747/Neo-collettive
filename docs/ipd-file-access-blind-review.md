# IPD – Revisione cieca dei segnali «accesso ai file»

La prima misurazione HN ha trovato **8 discussioni** (punteggio esplorativo 42); una seconda acquisizione con finestra temporale approssimata ha trovato **9 discussioni**. Non abbiamo conservato gli ID della prima campionatura: **non sono gli stessi casi dimostrati**. Tutte e quattro le ricerche della seconda fase erano tronche a 30 risultati; il campione non è rappresentativo.

La revisione privata e' una procedura *prospettica di diagnosi*, non un risultato svolto. Richiede **due veri revisori umani indipendenti**, che non possono essere sostituiti da due copie dello stesso valutatore automatico.

## Procedura (su macchina locale con Python e dipendenze)
1. `python experiments/demand-pressure/private_blind_review.py plan` — nessuna rete, nessun file.
2. `python experiments/demand-pressure/private_blind_review.py collect --private-dir /percorso/assoluto/riservato/nuovo` — massimo quattro interrogazioni HN pubbliche; salva dati identificabili *solo* nella cartella locale privata. Il nome deve essere nuovo. Nessun dato testuale o link entra negli artefatti GitHub.
3. Consegnare ai due revisori **solo** `blind_cases.jsonl` e una copia indipendente del proprio modello CSV. Custodire `private_machine_annotations.json` separatamente, senza mostrarlo ai revisori; non comunicare le priorità prodotte dalla macchina. Le etichette ammesse sono `real_problem`, `not_problem`, `uncertain`; richiesta esplicita `yes`, `no`, `uncertain`; tipologia `access_control`, `sharing_sync`, `retrieval`, `other`, `uncertain`. Non equiparare `real_problem` a compratore verificato.
4. Compilare indipendentemente `reviewer_1.csv` e `reviewer_2.csv`, sigillare le risposte prima del confronto.
5. `python experiments/demand-pressure/private_blind_review.py aggregate --private-dir /percorso/assoluto/riservato/nuovo` — genera soltanto `review_aggregate.json` locale, con conteggi senza testi, URL o identificativi. Incompletezze e disaccordi bloccano qualunque interpretazione conclusiva.

**Limiti:** il semplice fatto di avere due file compilati non verifica l'indipendenza di due persone; gli HN commenti e utenti non garantiscono identità di richiedenti distinti. I nuovi casi possono differire dai 9 della seconda acquisizione. Le ricerche sono campionate/troncate. Non stimare la precisione generale a partire da questa raccolta.

Nessun merge/deploy automatico, nessuna scrittura della memoria, nessuna modifica dei gate, dei prezzi, delle soglie o dello studente. Costo 0. Il protocollo e i test possono essere verificati in GitHub CI; la raccolta privata deve essere eseguita esclusivamente su un ambiente controllato.
