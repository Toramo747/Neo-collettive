# IPD — Prima campagna reale, risultati e decisione (10 ottobre 2026)

## Osservazioni pubbliche, eseguite in shadow
- Prima raccolta HN #38025904361: 16 interrogazioni, quattro temi, 4 settimane; categoria `file_access`: 8 discussioni e IPD esplorativo **42/100**; altre categorie: 2 prenotazioni, 0 inventario, 0 resi. Non usare IPD come probabilita' di mercato.
- Audit limitato #38026097023: 4 interrogazioni `file access`, massimo 30 risultati per settimana (tutte troncate), 120 messaggi esaminati, 9 thread selezionati; 5 marcatori automatici di richiesta esplicita, 3 rilevanza debole, 0 revisori umani. La prima raccolta non aveva conservato identita': non esiste replay esatto.
- Copertura ad alta raccolta #38026482139: 4 interrogazioni, fino a 500 risultati a finestra; restituiti 95, 90, 141 e 97 contenuti (423 complessivi), 22 discussioni distinte superano i filtri lessicali; 15 marcate come richiesta esplicita, 8 con sovrapposizione tematica debole, 1 con indizio da venditore; 15 richiedono revisione di contesto. Altre 13 discussioni rispetto alla vista first-30 del medesimo run; non confrontare 22 con 8 come aumento nel tempo.
- Il provider ha indicato `exhaustiveNbHits=false` su tutte le finestre: pur restituendo esattamente il totale stimato, **non ha provato che l'insieme fosse completo**. La metrica finale e' `INCONCLUSIVE_SOURCE_CAPPED_OR_APPROXIMATE`; trend del mercato **non determinabile**.
- Tutti i test mirati del workflow di copertura passati, privacy e invarianti eseguiti. Nessuna dimostrazione di acquisti o identita' indipendenti. Nessuna modifica di `main` o Render.

## Problema tecnico effettivamente scoperto
Il vecchio `hitsPerPage=30` tagliava discussioni rilevanti dal **campione osservato**: l'esperimento controllato di copertura trova 13 thread ulteriori rispetto ai primi 30 di ogni settimana. **Questa e' una limitazione di recall nel protocollo di ricerca**, non una prova che il classificatore sbagli i guard. La sorgente non garantisce ancora esaustivita'. Le metriche IPD **non devono crescere automaticamente in produzione** sulla sola base del nuovo volume di ricerca.

## Decisione
1. La ricerca di mercato continua solo in shadow, come classe `EXPLORATORY_UNVERIFIED`.
2. Per dire `problema reale` o `richiesta di soluzione` servono due giudizi indipendenti con contesto, raccolti mediante `private_blind_review.py` fuori dal repository; un duplicato artificiale di giudizi non conta. Il codice non invia né allena automaticamente.
3. Se serve misurare trend di popolazione, richiedere finestre complete o metodo di campionamento con esposizione normalizzata e stabilita; `exhaustiveNbHits=false` va rappresentato come incompletezza, senza inventare precisione.
4. Dopo doppia revisione umana e replica su almeno un'altra fonte, si potra' tarare sperimentalmente `IPD`. Il gate commerciale e i test pubblico/nascosto 6/6 restano invariati. Nessuna promozione prima della prova indipendente.

## Riproducibilita'
- Programma pubblico solo aggregati: `python experiments/demand-pressure/file_access_coverage.py --execute`, **massimo quattro interrogazioni gratuite**.
- Revisione privata: `python experiments/demand-pressure/private_blind_review.py plan`; `collect --private-dir <absolute-new-path>` **solo in ambiente privato, mai in CI pubblica**.
- CI: `python -m unittest -v test_demand_pressure_high_recall test_demand_pressure_private_blind_review`.

**Conclusione:** il difetto di limitazione del campione e' misurato e riproducibile, ma il numero di reali buyer indipendenti resta **zero verificati**. Il lavoro tecnico su PR #242 puo' essere revisionato, non promosso automaticamente in produzione.
