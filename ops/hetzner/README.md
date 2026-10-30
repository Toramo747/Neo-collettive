# Trasloco di NEO da Render a un VPS Hetzner

Guida per Andrea. Spesa prevista: **~4,5 €/mese** per il server (CX22/CX23: 2 vCPU, 4 GB RAM,
40 GB disco, IVA inclusa) più **~10 €/anno** per il dominio. Tutto sotto i 10 €/mese.
Niente si paga da questo repository: ogni pagamento lo fai tu, dal tuo account.

Cosa cambia rispetto a Render, in breve:

| Su Render | Sul VPS |
|---|---|
| Servizio web Docker, spegnimenti/sospensioni della piattaforma | Lo stesso Dockerfile dentro `docker compose`, sempre acceso, riavvio automatico |
| Checkpoint `NEO_STATE_JSON` scritto come variabile d'ambiente via API Render | Stesso codice: scrive su **envstore**, un piccolo servizio locale che parla come l'API Render e salva su disco (`/srv/neo/state`) |
| Chunk grandi nel repo GitHub privato | Invariato |
| HTTPS automatico di Render | **Caddy** con certificati Let's Encrypt automatici |
| Deploy hook Render chiamato dai workflow | Stesso meccanismo: `https://state.<dominio>/deploy/<hook>?ref=<sha>` |
| `jarvis-23lu.onrender.com` | Container `jarvis` sullo stesso server, `https://jarvis.<dominio>` |
| Variabili d'ambiente nel pannello | File `/srv/neo/.env` (chmod 600) |

Il codice è stato toccato in due punti soli: `RENDER_API_BASE` e `NEO_PUBLIC_BASE_URL` sono
ora leggibili dall'ambiente (prima erano costanti). Tutto il resto è in `ops/hetzner/`.

---

## 1. Account e pagamento (10 minuti)

1. **Hetzner**: https://accounts.hetzner.com/register — serve un documento per la verifica
   dell'identità (succede di norma al primo ordine, a volte chiedono una foto del documento).
2. **Metodo di pagamento**: in *Hetzner Accounts → Pagamento* scegli **SEPA (addebito diretto)**
   inserendo l'IBAN della Postepay Evolution, oppure **PayPal** (collegando la Postepay a PayPal).
   Entrambi evitano il blocco "carta prepagata" che hai avuto su Render. Le carte sono accettate
   ma con le prepagate possono rifiutare: usa SEPA o PayPal.
3. **Dominio**: comprane uno dove accettano PayPal (Cloudflare Registrar a prezzo di costo,
   oppure Porkbun). Dimmi il nome scelto: lo uso nel passo 5.

## 2. Il server (5 minuti)

1. Cloud Console → *New project* → *Add server*.
2. Località: **Falkenstein** o **Norimberga** (Germania, più vicini e più economici).
3. Immagine: **Ubuntu 24.04**. Tipo: **Shared vCPU → CX22** (o CX23, il più piccolo disponibile).
4. Networking: lascia IPv4 **e** IPv6. Chiave SSH: carica la tua chiave pubblica (consigliato) o
   fatti mandare la password root via mail.
5. Nome: `neo`. Crea. Annota l'**IP pubblico**.

## 3. DNS (2 minuti, poi aspetta la propagazione)

Nel pannello del dominio crea tre record **A** verso l'IP del server (e AAAA verso l'IPv6 se vuoi):

```
<dominio>            A   <ip>
jarvis.<dominio>     A   <ip>
state.<dominio>      A   <ip>
```

Senza proxy arancione se usi Cloudflare (DNS only): Caddy deve vedere la porta 80 per il certificato.

## 4. Esporta tutto da Render PRIMA di chiudere l'account (10 minuti, dal tuo PC)

Il pannello di un servizio sospeso resta leggibile e l'API continua a rispondere.

1. Render → *Account settings → API keys* → crea una chiave (o usa quella già nei secret GitHub
   `RENDER_API_KEY`). Non incollarla mai in chat.
2. Sul tuo PC, nella cartella del repo:

   ```bash
   export RENDER_API_KEY=rnd_xxx
   python3 ops/hetzner/export_render_env.py srv-dampj8bm8hqs73ac0an0 ./render-export
   python3 ops/hetzner/export_render_env.py <id-servizio-jarvis> ./render-export-jarvis
   ```

   Produce `render.env` (configurazione + segreti) e `render-state.env` (checkpoint e stato
   persistito). Stampa solo i nomi delle chiavi e le dimensioni, mai i valori.
3. Controlla che in `render-state.env` ci sia **NEO_STATE_JSON** e che in `render.env` ci siano
   **NEO_RECEIPT_SIGNING_KEY**, **NEO_HEARTBEAT_TOKEN**, **NEO_ADMIN_TOKEN**, le chiavi CDP/x402 e
   **NEO_STATE_GITHUB_TOKEN / NEO_STATE_GITHUB_REPO**. Se manca la chiave di firma, le ricevute
   future avrebbero un DID diverso: fermati e dimmelo.
4. Tieni una copia dei due file in un posto sicuro (non nel repo, non in chat).

## 5. Installazione sul server (15 minuti)

```bash
ssh root@<ip>
bash <(curl -fsSL https://raw.githubusercontent.com/Toramo747/neo-collettive/main/ops/hetzner/install.sh)
```

Lo script installa Docker, apre solo SSH/80/443 nel firewall, clona il repo in `/srv/neo/repo`,
crea `/srv/neo/.env` dal template con `ENVSTORE_TOKEN` e `ENVSTORE_DEPLOY_HOOK` già generati,
e registra il backup notturno dello stato (`/srv/neo/backups`, 14 giorni).

Finché la cartella `ops/hetzner` non è su `main`, usa il branch: `BRANCH=feat/hetzner-migration bash install.sh`.

Poi, sempre sul server:

```bash
# 1. dominio, email, URL pubblico
nano /srv/neo/.env            # NEO_DOMAIN, ACME_EMAIL, NEO_PUBLIC_BASE_URL

# 2. segreti copiati da Render (dal tuo PC)
scp render-export/render.env root@<ip>:/root/
scp render-export/render-state.env root@<ip>:/root/
scp render-export-jarvis/render.env root@<ip>:/root/jarvis.env
cat /root/render.env >> /srv/neo/.env && rm /root/render.env
mv /root/jarvis.env /srv/neo/jarvis.env && chmod 600 /srv/neo/jarvis.env

# 3. checkpoint e stato persistito nello store
bash /srv/neo/repo/ops/hetzner/import_state.sh /root/render-state.env && rm /root/render-state.env

# 4. avvio
systemctl start neo
cd /srv/neo/repo/ops/hetzner && docker compose logs -f neo
```

Verifica: `https://<dominio>/health` deve rispondere `{"status":"ok","version":"0.99.69",...}`
e `https://<dominio>/x402` deve mostrare `paid_since_launch` con gli stessi totali di prima
(è il segno che il checkpoint è stato ripreso). Se `paid_since_launch` è vuoto, il checkpoint non
è stato importato: fermati, non far girare l'autopilota a lungo, e controlla il passo 3.

## 6. Dopo l'avvio: URL nuovo ovunque (lo faccio io, tu approvi)

1. Nel repo: `ops/hetzner/rename_origin.sh <dominio>` (prova) poi `--apply`: sostituisce
   `neo-collettive.onrender.com` in ~200 file (workflow, schemi, `server.json`, documentazione).
   Lo faccio in un branch e ti mostro il diff.
2. Secret GitHub da aggiornare (li cambi tu in *Settings → Secrets*):
   `RENDER_DEPLOY_HOOK` = `https://state.<dominio>/deploy/<ENVSTORE_DEPLOY_HOOK>`,
   `RENDER_API_KEY` = valore di `ENVSTORE_TOKEN`; e nei workflow `RENDER_SERVICE_ID` diventa `neo`
   con `RENDER_API_BASE=https://state.<dominio>/v1` (lo metto io nel diff).
3. Registri esterni, nell'ordine: validatore CDP e Bazaar (si riallineano al primo settle
   sull'URL nuovo), **x402scan** (nuova registrazione dall'origine), registro MCP
   (`publish-mcp-registry.yml` con `server.json` aggiornato), modulo Circle Agent Marketplace
   (se ancora in revisione, aggiornare l'URL), poi un post su Commons con il nuovo indirizzo
   (testo da approvare, come sempre).
4. **DID e ricevute**: le offerte firmate e il `did:web` sono legati all'host. Le ricevute già
   emesse citano `did:web:neo-collettive.onrender.com`, che non è più raggiungibile; quelle nuove
   useranno `did:web:<dominio>`. Con il dominio tuo questo non succede più.

## 7. Manutenzione

- Deploy manuale: `/srv/neo/repo/ops/hetzner/deploy.sh` (o `deploy.sh <sha>`); il workflow
  `neo-render-deploy.yml` continua a funzionare tramite il deploy hook.
- Log: `cd /srv/neo/repo/ops/hetzner && docker compose logs --tail 200 neo`.
- Stato: `/srv/neo/state/vars/` (un file per chiave), backup in `/srv/neo/backups/`.
- Aggiornare envstore o Caddy: `docker compose up -d --build envstore caddy`.
- Sicurezza di base inclusa: ufw, fail2ban, unattended-upgrades. Accesso SSH solo con chiave se
  l'hai caricata al passo 2.

## Cosa può ancora andare storto

- **Verifica identità Hetzner** lenta (ore, a volte un giorno): ordina il server appena hai l'account.
- **Porta 25** chiusa di default su Hetzner: irrilevante, NEO non manda mail.
- **Prima richiesta HTTPS** dopo l'avvio può metterci 30-60 s (Caddy chiede il certificato).
- Il checkpoint ha un limite di 100 kB come prima (`NEO_STATE_ENV_MAX_BYTES`): envstore accetta
  fino a 16 MB, quindi il limite resta quello del codice, non dello store.
