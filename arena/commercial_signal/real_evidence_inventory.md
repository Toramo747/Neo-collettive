# Inventario storico evidenze reali

Snapshot storico analizzato: 100 record in `commercial_evidence_memory`.

## Record per famiglia
- spreadsheet_process: 21
- ai_tools: 19
- manual_data_entry: 15
- developer_tools: 13
- integration_api: 11
- workflow_automation: 6
- marketing_seo: 5
- cybersecurity_tools: 4
- ecommerce_tools: 4
- customer_support: 1
- analytics_tools: 1

Questi sono **record storici**, non esempi tutti validi di domanda reale: molti sono stati quarantinati come vendor/seller, disconfirm, generic problem o legacy-unverified.

Il campione di revisione `train_real_review.jsonl` contiene 24 casi selezionati e anonimizzati: 8 REAL_DEMAND proposti, 8 VENDOR_OR_SELLER, 8 NOISE.

## Caso near-gate principale
`manual_data_entry`: gap storico 70, BUY_INTENT + PAID_DEMAND e una fonte forte, ma solo 1 dominio indipendente e 1 fonte fresca. Per questo non ha raggiunto il gate (richiesti 3 domini in 21 giorni e 2 freschi in 7 giorni) e `qualified_hits` è rimasto 0.

## Limite del campione
Per customer_support e analytics_tools esiste un solo record storico ciascuno; cybersecurity_tools ed ecommerce_tools ne hanno quattro. Sono numeri troppo bassi per stimare recall/precision per famiglia in modo serio.
