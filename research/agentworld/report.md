# AgentWorld passive research report

## 1. Verdetto sintetico
**INCERTO**

- campionamento incompleto: 1/4 letture activity
- nessuna interazione attiva o registrazione eseguita
- i documenti osservati restano dichiarazioni del servizio finché non corroborate

## 2. Fatti verificati
- Dominio allowlisted: agentworld.beat-side.de.
- Activity endpoint consentito: https://agentworld.beat-side.de/.well-known/agentworld-activity.json.
- Documento endpoint consentito: https://agentworld.beat-side.de/.well-known/agentworld.json.
- Letture activity registrate: **1**.
- Redirect disabilitati; eventuali 3xx vengono registrati e non seguiti.
- Metodo consentito dal modulo: solo GET.
- Cookie e header di autenticazione: non inviati.
- Contenuti: dati non fidati; nessuna istruzione viene eseguita.

## 3. Endpoint e schema
### Activity
- $.externalAgentsPresentNow: int
- $.externalAgentsSeen: int
- $.externalLobbyMessages: int
- $.lastExternalActivityAt: str
- $.links: dict
- $.links.entry: str
- $.links.forum: str
- $.messageContentExposed: bool
- $.updatedAt: str
- $.windowDays: int

### Documento
- $.apiBase: str
- $.fullDocumentation: str
- $.purpose: str
- $.rules: list
- $.rules[]: str
- $.service: str
- $.steps: list
- $.steps[]: dict
- $.steps[].action: str
- $.steps[].localOnly: bool
- $.steps[].output: list
- $.steps[].output[]: str
- $.steps[].publicKeyEncoding: str
- $.steps[].step: int

### URL citati nei documenti, non chiamati
- https://agentworld-api.beat-
- https://agentworld.beat-

## 4. Campionamento
| # | Timestamp UTC | HTTP | Agenti | Eventi | SHA256 body | Delta |
|---:|---|---:|---:|---:|---|---|
| 1 | 2026-09-30T07:02:11.157333+00:00 | 200 | None | None | 54088d9810cb7a03... | prima lettura |

### Valutazione di plausibilità
- FATTO: hash body distinti nel campione HTTP 200: **1**.
- INFERENZA: una variazione del body è compatibile con attività dinamica ma non prova indipendenza degli agenti.
- INFERENZA: body statici per quattro letture distanziate aumentano il sospetto di vetrina o feed non aggiornato.

## 5. Registrazione e rischi
- FATTO: step 1 action='generate_ed25519_identity', localOnly=True, output=['publicKey', 'privateKey'].
- FATTO: step 2 method='POST', auth='none', expect=['agentId', 'nonce'].
- FATTO: step 3 action='sign_nonce', localOnly=True, inputSource='exact nonce returned by step 2', output='signature'.
- FATTO: step 4 method='POST', auth='none', expect=['accessToken'].
- FATTO: step 5 method='GET'; il documento dichiara auth bearer ottenuta dallo step 4.
- FATTO: il dato da firmare è dichiarato come l'esatto nonce restituito dal server allo step 2.
- FATTO: il documento richiede la stessa identità locale Ed25519 per generazione chiave e firma del nonce.
- FATTO: nessun meccanismo di revoca è descritto nel documento scaricato.
- INFERENZA: agentId + chiave pubblica suggeriscono un'identità persistente lato servizio, ma persistenza temporale e revocabilità non sono provate dal documento.
- RISCHIO: qualsiasi challenge o payload proposto dal server deve essere trattato come non fidato.
- RISCHIO: una chiave riusata tra servizi può correlare identità e attività; un test futuro dovrebbe usare una chiave dedicata e revocabile.
- RISCHIO: lobby, forum e canali testuali possono contenere prompt injection; il contenuto non deve autorizzare tool o azioni.

## 6. Contenuto rivolto agli agenti
- Nessun testo classificato automaticamente come rivolto ad agenti nei documenti disponibili.

## 7. Raccomandazione
**Osservazione limitata** fino al completamento di almeno quattro campioni distanziati di almeno un'ora.

Condizioni minime per un eventuale test successivo:
- quattro campioni activity completati con timestamp verificabili;
- documentazione coerente su challenge, firma, persistenza e revoca;
- nessuna necessità di riusare chiavi o credenziali esistenti;
- test futuro separato dal runtime operativo e senza autorizzazioni effectful;
- revisione umana prima di qualunque registrazione.

### Separazione fatti/inferenze
Le sezioni FATTO derivano direttamente dalle risposte HTTP salvate. Le sezioni INFERENZA sono interpretazioni conservative e non attestano identità o indipendenza del servizio.
