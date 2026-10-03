# Revisione etichette — evidenze reali

Le etichette sotto sono **proposte**. Nessuna viene adottata dal gate di produzione.

## Sintesi
- REAL_DEMAND: 8
- VENDOR_OR_SELLER: 8
- NOISE: 8
- Totale: 24

## Casi da guardare per primi
1. **real-001 — REAL_DEMAND** — `manual_data_entry`: BUY_INTENT + PAID_DEMAND, fonte forte, gap storico 70. Blocco: solo 1 dominio indipendente e 1 fonte fresca; `qualified_hits=0`.
2. **real-002 / real-003 — REAL_DEMAND** — `manual_data_entry`: PAIN reale su 3 domini/3 freschi, ma nessuna fonte commercialmente forte e nessun PAID_DEMAND.
3. **real-005 — REAL_DEMAND** — `spreadsheet_process`: PAID_DEMAND/contractor, ma problem bucket troppo generico e manca BUY_INTENT/PAIN nello stesso record qualificabile.
4. **real-006 — REAL_DEMAND** — `ai_tools`: budget presente, ma problema generico e buyer intent incompleto.
5. **real-008 — REAL_DEMAND** — `integration_api`: contesto paid storico, ma tagger legacy non fidato e intenzione buyer ambigua.

## Seller/vendor
`real-009`–`real-016` provengono da record che lo storico aveva già classificato come `vendor_content` o `seller_launch`. L'etichetta proposta è quindi VENDOR_OR_SELLER.

## Noise
`real-017`–`real-024` coprono: problema troppo generico, buyer voice assente, sola competition, disconfirm e record legacy non affidabili.

## Nota sul campione
Il campione reale è piccolo e sbilanciato. Le etichette non devono essere considerate ground truth finché non vengono approvate manualmente.
