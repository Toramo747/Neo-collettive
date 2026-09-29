# Arena — Segnale commerciale

Fase 0 interna. Questa stanza **valuta soltanto** configurazioni candidate: non modifica il quality gate di produzione, `qualified_hits` o altri stati commerciali.

## Dataset

- `train_synthetic.jsonl`: dataset **sintetico** e bilanciato, creato esclusivamente per collaudare schema, validatore, evaluator e workflow. **I risultati ottenuti su questo file validano solo l'infrastruttura e non devono essere usati per decisioni commerciali o per modificare il gate.**
- `train_real_review.jsonl`: campione derivato da record reali storici di `commercial_evidence_memory` e dagli esiti del gate, ma con testo riformulato e dati identificativi rimossi. Le etichette sono proposte e richiedono approvazione umana.
- `label_review_real.md`: revisione compatta per l'approvazione delle etichette reali.

Nessun dataset contiene nomi, handle, email, IP o URL completi.

## Holdout

Proposta soltanto: conservare l'holdout nello **stesso repository privato usato per la telemetria**, ma in cartelle separate:

- `/arena-holdout/`
- `/telemetry/`

Un solo token GitHub fine-grained può accedere al repository privato, con i permessi minimi necessari. Il repository pubblico e il workflow pubblico di questa stanza non devono ricevere il token né leggere l'holdout.

## Regola Arena

Una proposta con false positive su VENDOR_OR_SELLER sopra la soglia configurata è squalificata. Tra le proposte non squalificate si confronta la recall su REAL_DEMAND. Le parità restano esplicite.

Nessun risultato Arena viene adottato automaticamente.
