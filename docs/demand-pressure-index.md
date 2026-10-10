# IPD – Pressione della Domanda (shadow-only, proposta v1)

## Obiettivo
Misurare la frequenza e l'evoluzione delle richieste **senza trasformare il volume in prova di acquisto**. La funzione pura `demand_pressure.demand_pressure_index` accetta una sola coorte di problema e produce aggregati; nessuna chiamata di rete, aggiornamento runtime, memoria, checkpoint, prezzi o gate.

**Importante:** modulo e test sono sperimentali e non collegati al ciclo di produzione. Non affermare che OXIBAY stia già calcolando l'IPD.

## Punteggio preliminare (non tarato)
- volume dei thread distinti: 35%;
- crescita delle richieste normalizzata per esposizione confrontabile: 25%;
- ricorrenza in massimo quattro settimane: 20%;
- diversità dei domini di origine: 15%;
- richieste esplicite di soluzione: 5%.

I pesi sono ipotesi: vanno calibrati su esempi verificati e in un set temporale distinto. `ipd_score` non è equivalente a fiducia statistica, intenzione d'acquisto o probabilità di monetizzazione. `evidence_status` segnala dati insufficienti. I valori vuoti di crescita producono zero *conservativo* e stato `EXPOSURE_MISSING`, **non** crescita zero osservata.

## Provenienza e indipendenza
La pipeline chiamante (non ancora implementata) deve fornire un insieme omogeneo per problema con `request_id` opaco HMAC/hex derivato dal documento/thread originale, `created_at_epoch` della pubblicazione originale, `source_screened=True`, un `demand_signal_tag` già positivo e i tre flag espliciti `vendor_offer=False`, `self_traffic=False`, `agent_origin=False`. La mancanza dei flag esclude l'evento. L'autore diventa un attore verificato solo quando è presente `actor_hmac` e `independent_requester_verified=True`; quest'ultimo richiede verifiche esterne, non è garantito dalla funzione. Nessun identificativo nominativo o testo in output. Il campo `origin_domain` deve essere un'origine validata a monte: la diversità dei domini non è un conteggio di persone.

Le ricatture dello stesso `request_id` contribuiscono una volta sola, anche se ci sono molte scansioni. I duplicati discordanti perdono credito d'indipendenza o di domanda esplicita. Un thread resta una sola richiesta osservabile, non un volume di commenti, visitatori o pagamenti. Un'identità HMAC non dimostra da sola l'indipendenza delle persone.

## Crescita
Usare `exposure_current` e `exposure_previous` come denominatori **comparabili** delle due settimane con uguale campionamento: ad esempio il numero di discussioni eleggibili esaminate, non il numero arbitrario di query. Impostare `sampling_comparable=True` solo con acquisizione comparabile e completa. Senza queste precondizioni l'andamento rimane non misurabile. Tassi con denominatore precedente zero sono `EMERGING`, senza percentuali infinite.

## Integrazione futura, non inclusa
1. Prelevare dati pubblici o privati *solo in lettura*, minimizzati e provenienti da sorgenti verificabili. Non usare `ingestion_drought` aggregato per inferire persone distinte; non contiene identità dei richiedenti. Non equiparare i 143 risultati del ciclo 3283 a 143 richieste.
2. Separare una corsia **demand discovery** che possa osservare domande autentiche anche se non hanno ancora concorrenti/prezzi; non far confluire la corsia nell'evidence store commerciale.
3. Calcolare IPD per problema e settimana su dati temporali coerenti, incluse fonti e denominatori; conservare solo output aggregati pubblici e mantenere gli input privati fuori dal repository.
4. Validare con revisori umani indipendenti, controlli anti-duplicati, confronti tra fonti, test contro query-noise e repliche prospettiche. Nessun filtro commerciale viene allentato.

## Paletti
- Costo zero; nessun provider a pagamento.
- Nessuna soglia, isteresi, etichetta commerciale, set pubblico/nascosto, memoria, segreto o Render modificati.
- Nessuna promozione automatica. IPD può suggerire cosa *esplorare*, non ciò che può essere *venduto*.
- L'IPD attuale usa segnali positivi già etichettati e non risolve da sé i falsi negativi: quella è una ricerca separata.
- La CI testa soltanto logica sintetica: senza prova sul campo il vantaggio empirico è **non dimostrato**.
