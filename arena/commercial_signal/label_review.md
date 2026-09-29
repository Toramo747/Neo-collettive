# Segnale commerciale — revisione etichette Fase 0

Dataset train proposto: 24 casi anonimizzati, derivati dalla struttura di `commercial_evidence_memory`, dagli esiti storici del gate e dai regressori già presenti nel repository.

Distribuzione proposta:
- REAL_DEMAND: 8
- VENDOR_OR_SELLER: 8
- NOISE: 8

Le etichette sono **proposte**, non approvate. Ogni riga di `train.jsonl` contiene una motivazione breve.

Il dataset è intenzionalmente piccolo e bilanciato per verificare l'infrastruttura, non per stimare prestazioni reali. **24 casi sono insufficienti per una valutazione seria del classificatore.**

## Holdout
Non viene commesso nel repository pubblico. Proposta: conservare 8–12 casi aggiuntivi in un repository GitHub privato separato (es. `Neo-collettive-private-eval`) accessibile solo ai maintainer, oppure in storage privato cifrato. Il workflow pubblico non deve avere accesso al holdout. La valutazione holdout va eseguita separatamente e pubblica solo metriche aggregate.

## Provenienza
I testi sono parafrasi sintetiche prive di nomi, email, IP, handle e URL. Le categorie riflettono pattern osservati nello storico: buyer pain/paid intent, vendor/seller content, generic job listings, recruiting noise, query echo, competition/disconfirm.
