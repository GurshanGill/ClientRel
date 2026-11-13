# ClientRel

ClientRel is a local CRM workspace for CSV ingestion, contact search, deal metrics, and natural-language analytics. Python serves the dashboard and API, Redis Streams distributes import work, and MongoDB stores contacts and import progress.

## Run the connected workspace

1. Start Docker Desktop or another Docker engine with Compose support.
2. Copy `.env.example` to `.env`. Set `OPENAI_API_KEY` to enable AI queries. CSV ingestion and browsing work with an empty key.
3. Run `docker compose up --build` in this directory.
4. Open [ClientRel on localhost](http://localhost:8000). Go to **Imports** and upload `sample-contacts.csv`.
5. After the import completes, open **AI Query** and try “Count contacts by stage.” The results include the MongoDB pipeline that ran.

The web service binds to localhost. The stack is intended for single-user local use and has no user accounts. MongoDB and Redis use Compose volumes. Run `docker compose down` to stop the stack while preserving data.

## Preview with sample data

Run `CLIENTREL_DEMO=1 python3 app.py` and open [ClientRel on localhost](http://localhost:8000). Demo mode uses Python’s standard library and includes searchable fictional contacts. Imports and AI execution are available in connected mode.

## CSV format

Use UTF-8 with the header `name,email,company,industry,region,stage,value`. Stages are `New`, `Qualified`, `Proposal`, `Won`, and `Lost`. Deal values are nonnegative numbers displayed in USD. The per-file limit is 256 MiB. Each upload appends a new set of records. Retrying a queued chunk is idempotent. Valid chunks from an interrupted or malformed upload can already have been imported, so check import history before uploading the file again.

## How it works

- The API streams CSV input and publishes chunks of 500 rows. Three worker replicas share a Redis consumer group. Workers recover stale pending entries with `XAUTOCLAIM`, upsert records with stable IDs, record accepted and rejected counts, and acknowledge completed chunks.
- The AI receives the question and field schema. The rule engine validates the returned query plan and builds the MongoDB stages itself. Supported operations include equality filters, numeric comparisons, lists, counts, total and average deal value, and grouping. Queries run on the contacts collection with a four-second database execution limit and return up to 100 rows.
- Redis and MongoDB connections use local Compose service names. Running the entire stack requires Docker. The AI feature also requires network access to OpenAI.
