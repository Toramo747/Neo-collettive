# PR #215 — procedura del deploy di osservazione

Problema osservato: il codec sincrono ha bloccato il loop nel replay locale
post-ripristino di 3 MiB; lo stack è stato catturato sulla chiamata lzma.
Il blocco storico di 27,5 s su Render resta da attribuire. Questa PR contiene
la correzione candidata **spenta** e consente un confronto sullo stesso codice.
Nessun merge, deploy o intervento su Render è stato eseguito dall'agente.

## Comportamento e limiti

- `NEO_CHECKPOINT_CODEC_OFFTHREAD` assente o `0`: codec sincrono invariato.
  Solo `1` attiva `asyncio.to_thread` per zlib/lzma, base64 e controllo dimensione.
- Il JSON viene congelato in bytes immutabili prima dell'await; resta sul loop
  per evitare letture concorrenti dello stato mutabile. Algoritmi, preset,
  payload, limiti, memoria, soglie e gate rimangono invariati. Un errore nel
  worker raggiunge il chiamante; nessun valore parziale del checkpoint viene
  pubblicato. La cancellazione non arresta il worker Python, ma il worker
  comprime soltanto bytes e non effettua scritture.
- `codec_offthread` è un booleano privato/pubblico. Il segnale
  `first_autopilot_cycle_completed` è per processo, inizialmente falso e diventa
  vero dopo la finalizzazione del primo ciclo e il tentativo di checkpoint.
  `first_autopilot_cycle_number` distingue questo ciclo dai contatori ripristinati.
  Il segnale non deriva da una vecchia `cycles_completed` recuperata dalla memoria.
- Il workflow verifica prima health, versione e commit, quindi attende il segnale
  al massimo 300 s. Gli smoke delle dieci superfici/verifiche HTTP effettuano
  al massimo 3 tentativi, 20 s fra tentativi e 30 s per richiesta. Lo smoke Arena
  è riusabile dopo il riavvio e mantiene tutte le asserzioni precedenti.
- `observation_deploy=true` è ammesso solo per `Toramo747` (Andrea), anche su
  una riesecuzione. Ogni uso emette un avviso. Gli smoke definitivamente falliti
  diventano avvisi; il riepilogo riporta il fallimento, il rollback automatico
  è saltato. Un'attesa del primo ciclo fallita resta visibile come avviso.
  I controlli di integrità, commerciali e nascosti restano obbligatori e fatali.
  Senza questa opzione il fallimento provoca il normale rollback.
- Le misure sono per processo, le fasi annidate si sovrappongono. JSON, decode,
  compattazione e salvataggi locali restano sincroni: se dominano i log, fermarsi
  e riportare quella fase. La correzione non è una prova della causa storica.

## Procedura eseguita da Andrea

1. Prima del merge, disabilita temporaneamente **NEO Render Deploy** nella
   pagina Actions del repository: il merge modifica file inclusi nel trigger
   `push` e avvierebbe altrimenti un deploy normale, senza observation_deploy.
   Nessuna di queste azioni è stata eseguita dall'agente. Sul servizio
   `neo-collettive`, workspace `My Workspace`, lascia/imposta personalmente
   `NEO_CHECKPOINT_CODEC_OFFTHREAD=0` per la prima misura.
2. Esegui il merge solo dopo la tua approvazione, riabilita il workflow e usa
   **Run workflow**, branch `main`, account Andrea/Toramo747:
   `observation_deploy=true`, `extended_validation=false`; non abilitare
   `emergency_deploy` salvo una tua decisione separata. Annota SHA, ID della run,
   UTC di avvio e ID dell'istanza. Verifica l'avviso OBSERVATION_DEPLOY.
3. Nei log Render del primo ciclo individua `event_loop_stall`, `event_loop_stack` e
   `runtime_phase`; registra `event_loop_stalls`, `event_loop_max_lag_ms`,
   `last_project_stack`, durata/CPU di `checkpoint_json`, `checkpoint_zlib`,
   `checkpoint_lzma`, `checkpoint`, `autopilot` e delle altre fasi più lente.
   Leggi la telemetria privata già autorizzata da `/api/autonomy/status` e lo
   snapshot pubblico; verifica `codec_offthread=false` e il numero del primo
   ciclo. Conserva solo nomi delle funzioni e aggregati, mai segreti o evidenze.
4. **Condizione di arresto:** se lo stack sincrono non identifica la chiamata
   `lzma.compress` dentro `compress_checkpoint` (o identifica un'altra funzione),
   non attivare la correzione. Riporta la fase e i dati. Uno stack assente rende
   la prova insufficiente: il campionatore può non operare se il GIL resta
   occupato o il processo è completamente deschedulato. Non attribuire il
   blocco alla compressione per sola somiglianza delle durate.
5. Solo con quella prova, imposta personalmente su Render
   `NEO_CHECKPOINT_CODEC_OFFTHREAD=1` e riavvia il servizio mantenendo lo stesso
   commit. La modifica della variabile può già avviare un nuovo container:
   evita un secondo riavvio durante il primo ciclo. Annota il nuovo ID istanza
   e UTC; attendi il completamento del primo ciclo di questa istanza.
6. Ripeti la lettura del punto 3, verifica `codec_offthread=true` e confronta
   le due finestre. I contatori di processo ripartono: non sottrarre valori
   appartenenti a istanze diverse. Non rilanciare il workflow di deploy per
   effettuare lo smoke dopo il riavvio.
7. Dal checkout dello stesso SHA, con `HEARTBEAT_TOKEN` già disponibile in modo
   sicuro nell'ambiente locale, esegui il polling e lo stesso smoke Arena:

   ```bash
   python scripts/wait_first_autopilot_cycle.py
   OBSERVATION_DEPLOY=true python scripts/retry_deploy_smoke.py scripts/smoke_arena_surface.sh
   ```

   Non usare shell tracing e non stampare il token. Il primo comando fallisce
   se il segnale non arriva entro 5 minuti. Il secondo registra ogni tentativo;
   in observation mode un fallimento finale restituisce 0 ma emette un avviso:
   **l'assenza di avvisi e il successo su `attempt=1/3` sono la prova dello smoke**.
8. Successo: con `1`, `event_loop_max_lag_ms < 1000` nella finestra del primo
   ciclo e tutte le asserzioni Arena passano al primo tentativo. Registra prima/
   dopo, SHA e istanze nella PR. Se il criterio fallisce, conserva i log e
   riporta la fase responsabile; nessuna ulteriore correzione è implicita.
   `extended_validation=false` evita le ulteriori attività estese previste dal
   workflow. Le verifiche Pathwren e dialogo A2A già obbligatorie restano presenti,
   con gli stessi retry degli altri smoke.

## Verifica locale

Il test usa payload sintetico deterministico di 3,145,752 bytes, ripristino e
3 codifiche reali; subprocess vincolato a una sola CPU. Non simula la quota
Render di 0,15 core né riproduce l'intero autopilot. Le due modalità producono
lo stesso SHA-256 del valore codificato:
`95d56197ef942252318c1efafbbede44daf8714009140845859d31242d58a6c2`.

I test verificano anche errore propagato senza PUT del checkpoint, modalità
predefinita sincrona, segnale nuovo per processo, attesa massima, 3 tentativi,
avviso in observation mode, rollback normale e autorizzazione di Andrea.
I risultati finali sono riportati nella PR; i set nascosti reali su Render
non sono stati eseguiti per questo candidato non distribuito.

Output finale della suite e del replay incluso nella suite:

```text
python -m unittest discover -v
Ran 949 tests in 32.543s
OK
Commercial 24/24; famiglie 24/24; sfide 12/12
Gate e privacy: verdi (suite completa)
Modalità 0: max lag 5509.633 ms; lzma max 2100.447 ms
Modalità 1: max lag 8.292 ms; lzma max 1927.156 ms
YAML deploy/heartbeat e tutti i blocchi bash: validi
```

File modificati per questa aggiunta: `state_codec.py`, `cloud_mcp.py` (switch
compressione e segnale); `runtime_observation.py`, `public_snapshot.py` (modalità
e segnale aggregati); workflow deploy, `scripts/wait_first_autopilot_cycle.py`,
`scripts/retry_deploy_smoke.py`, `scripts/smoke_arena_surface.sh` (attesa e smoke);
`scripts/reproduce_loop_stall.py`, `test_checkpoint_observation_deploy.py` (prove);
questo documento e `runtime-observation.md` (procedura e limiti aggiornati).
