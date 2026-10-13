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

1. Esegui **Squash and merge** con il titolo del commit finale contenente
   `[skip ci]`, per esempio:
   `Phase 1 deploy reliability and loop observation [skip ci]`.
   Verifica il titolo nel dialogo finale prima di confermare. GitHub salta i
   workflow attivati da `push` per quel commit; non occorre disabilitare il
   workflow. La correzione del test sulla PR viene invece pubblicata senza
   istruzioni di skip, così tutti i controlli possono essere verificati.
2. **Actions → NEO Render Deploy (neo-render-deploy.yml) → Run workflow**, branch
   `main`, account Andrea/Toramo747: `observation_deploy=true`,
   `extended_validation=false`, `emergency_deploy=false`.
   `NEO_CHECKPOINT_CODEC_OFFTHREAD` resta `0`, il valore predefinito.
   Annota SHA, run, UTC e ID istanza; verifica l'avviso OBSERVATION_DEPLOY.
3. L'agente legge **in sola lettura** log Render e telemetria del primo ciclo:
   `event_loop_max_lag_ms`, `event_loop_stalls`, stack catturato e durata/CPU
   per fase (`checkpoint_json`, `checkpoint_zlib`, `checkpoint_lzma`,
   `checkpoint`, `autopilot` e altre fasi lente). Nei log cerca
   `event_loop_stall`, `event_loop_stack`, `runtime_phase`; verifica
   `codec_offthread=false` e il numero del primo ciclo. Se lo stack non
   identifica `lzma.compress` dentro `compress_checkpoint`, **ci si ferma** e
   si riporta la fase. Uno stack assente è prova insufficiente. Riportare solo
   funzioni e aggregati, mai segreti o evidenze.
4. Solo con quella prova, Andrea imposta personalmente
   `NEO_CHECKPOINT_CODEC_OFFTHREAD=1` su Render e riavvia il servizio sullo
   stesso commit. Se il salvataggio avvia già un nuovo container, non
   interrompere il primo ciclo con un secondo riavvio. Annota istanza e UTC.
5. L'agente ripete la lettura sul primo ciclo della nuova istanza, verifica
   `codec_offthread=true` e lancia lo stesso smoke Arena. I contatori sono per
   processo: non sottrarre valori di istanze diverse e non rilanciare il
   workflow di deploy per lo smoke. Dal checkout dello stesso SHA, usando
   l'autenticazione già prevista dallo smoke senza leggere/esportare i valori
   delle variabili Render:

   ```bash
   python scripts/wait_first_autopilot_cycle.py
   OBSERVATION_DEPLOY=true python scripts/retry_deploy_smoke.py scripts/smoke_arena_surface.sh
   ```

   Criterio di successo: `event_loop_max_lag_ms < 1000` durante il primo ciclo
   e smoke Arena verde al tentativo `1/3`, senza avvisi. Il wrapper in modalità
   osservazione restituisce 0 anche al fallimento finale: verificare il log,
   non solo l'exit code. Se il criterio fallisce, conservare i log e riportare
   la fase responsabile.

### Trigger verificati

`neo-render-deploy.yml` ha esclusivamente `push` (branch `main`, con filtro dei
percorsi) e `workflow_dispatch` (manuale). Non ha `workflow_run`, `schedule`,
`pull_request_target`, `repository_dispatch` o altri trigger. `[skip ci]` nel
messaggio del commit squash salta il deploy su quel push e lascia disponibile
il successivo avvio manuale. Non blocca eventuali workflow schedulati separati.
Riferimento: [GitHub Docs — Skipping workflow runs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).

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
