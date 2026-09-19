# Jarvis Service

Internal analytical advisor for NEO.

## Endpoints

- GET /health
- GET /ask
- POST /ask

POST /ask body:

```json
{
  "message": "Analyze this opportunity",
  "source": "neo",
  "context": {}
}
```

## Render

Create a second Web Service from this repository.

- Root Directory: `jarvis_service`
- Runtime: Docker
- Region: same as NEO
- Environment:
  - `OPENAI_API_KEY` = your OpenAI API key
  - `JARVIS_SHARED_SECRET` = a long random secret
  - optional `JARVIS_MODEL` = `gpt-5.6-luna`

Then configure NEO:

- `JARVIS_URL=https://<jarvis-service>.onrender.com/ask`
- `JARVIS_API_KEY=<same value as JARVIS_SHARED_SECRET>`

No payment, publishing, outreach or external transaction is performed by Jarvis.
