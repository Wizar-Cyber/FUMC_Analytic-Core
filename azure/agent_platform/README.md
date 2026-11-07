# Distributed agent POC

This isolated Azure Functions app runs two Service Bus workers in parallel
(socioeconomic analysis and academic RAG), then stores the recommendation as a
generated demo result. The frontend displays it as soon as the Durable batch
finishes; there is no human-approval step in this synthetic-only demo. It does
not send student communications, schedule appointments, award aid, or make
academic/financial decisions.

## POC restrictions

- Requires `DATA_MODE=synthetic` and case tokens beginning with `syn-`.
- This is a POC guard, not data-provenance verification: callers must still
  supply only generated synthetic fixtures.
- Never put names, emails, phone numbers, institutional IDs, or other direct
  identifiers in a request.
- Uses Microsoft Entra managed identity for Azure OpenAI, AI Search, Service
  Bus, and Blob Storage. Local development uses `DefaultAzureCredential`.
- The GPT-5-mini path uses Chat Completions API `2025-04-01-preview`,
  `max_completion_tokens`, and omits `temperature`. Set
  `AZURE_OPENAI_MODEL` to the actual model name. Other configured models retain
  `max_tokens` and `temperature`; set their compatible API version separately.
- Every call must return service-reported input/output token usage. The saved
  review reports per-agent and total usage plus an estimated USD amount using
  `AZURE_OPENAI_INPUT_PRICE_PER_1M_TOKENS` and
  `AZURE_OPENAI_OUTPUT_PRICE_PER_1M_TOKENS`. The estimate is not a spend cap.
- An ETag-protected Blob counter rejects more than 10,000 accepted evaluations
  for this pilot and admits only one active case at a time. The counter is
  persistent in `pilot/evaluation-counter.json`; do not reset or replace it
  during the pilot. Service Bus workers also process one message at a time.
- The first authenticated panel load initializes a 500-record demo Digital
  Twin in Azure Tables: student profiles, SEMANA_4 snapshots, academic signals,
  finance, wellbeing, target traceability, alerts, follow-ups, and aggregate
  trend points. Its catalogs follow the attached interface: seven programs,
  four faculties, and Medellín, Cali, Neiva, and Popayán. Trend points are
  labeled simulated history because only one student-level cut is generated.
  The target table is never joined into agent inputs.
- `POST /api/batches` processes at most five pending snapshots sequentially
  through the existing Durable multi-agent workflow. It runs only when an
  authenticated reviewer presses the batch button; no timer, scheduled trigger,
  or automatic reprocessing is configured. The panel can pause new work and
  refuses to pause while a case or batch is active. This switch does not delete
  Azure resources or remove any ongoing platform charges.
- Academic RAG is disabled by default. Without an authorized regulation index,
  the academic agent analyzes only supplied academic signals and explicitly
  states that no regulatory evidence was retrieved. Enable
  `ACADEMIC_RAG_ENABLED=true` only after an approved index with fields `id`,
  `title`, `source_uri`, `section`, and `content` is provisioned.
- All dashboard and operational APIs require App Service Authentication to
  supply a principal whose Entra object ID is in
  `CASE_REVIEWER_ALLOWED_PRINCIPAL_IDS`. This is access authentication, not an
  approval step for a generated demo result. Legacy `pending_approval` records
  remain readable, but new results are stored as `generated` and the UI has no
  approve/edit/reject controls.
  Set `REVIEWER_AUTH_ENFORCED=true` only after App Service Authentication has
  been configured and verified; it defaults to disabled. All HTTP routes use
  anonymous Functions auth so the browser needs no Function key; each handler
  independently blocks requests from users outside the configured allowlist. Configure
  App Service Authentication to require sign-in for every API route. The
  static interface in `static/` is served by this Function App from the same
  authenticated origin. App Service Authentication must protect the UI and
  every `/api` route. If auth is not configured, the API stays blocked and the
  interface cannot submit or review.
- The `syn-` check is not data-provenance verification. Use only the 500 seeded
  generated records. An authenticated user explicitly starts batches of at
  most five; agents run sequentially per case and the UI polls until results
  are available. KPI refresh is automatic, but does not invoke the LLM.

## Local configuration

Use Python 3.11, Azure Functions Core Tools v4, and Azurite. Copy
`local.settings.example.json` to `local.settings.json` and fill only local
resource identifiers. Do not commit the local file or credentials. Start the
app from this directory with `func start`.

Install the app dependencies in the Python environment used by Core Tools:

```powershell
python -m pip install -r .\requirements.txt
Copy-Item .\local.settings.example.json .\local.settings.json
func start
```

The local run requires reachable Azure OpenAI, Service Bus, Blob Storage, and
Azure Tables resources plus the corresponding data-plane roles. AI Search is optional until
an authorized regulation corpus and index are available. No Azure resource is
created by the app.

## HTTP contract

All routes below require an authenticated Entra principal whose object ID is in
the configured reviewer allowlist. `POST /api/cases` starts one durable workflow and returns an instance ID;
poll `GET /api/cases/{instanceId}` through the authenticated status route. The
API does not return the Durable Functions management URL or a function key.
`GET /api/poc/status` returns the synthetic database summary and processing
switch. `POST /api/poc/state` pauses or resumes new work and rejects a pause
while a case or batch is active. `POST /api/batches` starts a sequential batch
of at most five pending snapshots; poll `GET /api/batches/{batchId}` for status.
`GET /api/reviews` returns aggregate counts, generated results, and any legacy
pending review summaries;
`GET /api/reviews/{review_id}` returns the redacted analysis and citation
metadata. `GET /api/powerbi/reviews` returns a flattened, refreshable table of
LLM results and their workflow status for Power BI; connect with the Entra
account whose object ID is on the reviewer allowlist. These read APIs omit
case tokens, direct identifiers, raw prompts, reviewer IDs, approval notes,
and retrieved source content. The Power BI endpoint is available only in the
synthetic-only POC mode and does not connect to institutional student data.

The request accepts:

```json
{
  "case_id": "syn-example-001",
  "model_probability": 0.62,
  "economic": {
    "arrears_months": 2,
    "arrears_balance_cop": 350000,
    "socioeconomic_stratum": 2,
    "origin_city": "Medellin",
    "family_context": "has_dependents"
  },
  "academic_signals": [
    {"course_code": "ING101", "grade": 2.8, "attendance_pct": 72}
  ]
}
```

The response contains `instanceId` and a protected same-origin `statusUrl`. A
completed demo workflow returns a redacted generated result with
`human_review_required: false` and `automated_decision: false`, actual token
counts for all three model calls, and an estimated cost when rates are
configured. The analysis is displayed automatically but no intervention is
executed. The approval route is retained only for old pending records and
rejects newly generated results.

The static frontend is an authenticated SPA with dashboard, student profiles,
alerts, follow-ups, analytics, faculties/programs, reports, and read-only
configuration. Every query uses the protected same-origin Functions API.
KPI/chart clicks apply student filters; alert/follow-up changes persist to
Azure Tables; report export downloads the protected Power BI projection; the
dashboard refreshes every 30 seconds. Only the explicit batch action invokes
the LLM. A small “Demo · registros generados” label remains so the UI does not
misrepresent the dataset as institutional data.

## Operational prerequisites

Use [the Bicep template](infra/README.md) to provision queues
`socioeconomic-analysis`, `academic-analysis`, and `agent-results`, plus a
dedicated Storage account containing the `student-case-reviews` and deployment
package containers and Durable Functions host storage. The template grants the
Function App identity:

- Cognitive Services OpenAI User on the approved model resource.
- Search Index Data Reader on the approved AI Search service only if RAG is
  enabled after an approved index is provisioned.
- Azure Service Bus Data Sender and Receiver on the namespace.
- Storage Blob Data Owner, Storage Queue Data Contributor, and Storage Table
  Data Contributor on the dedicated Function App Storage account.

Configure App Service Authentication with Microsoft Entra ID and set
`CASE_REVIEWER_ALLOWED_PRINCIPAL_IDS` to the authorized Entra object IDs before
enabling the approval route. The UI contains no Function or model keys; require sign-in at the
App Service Authentication layer for every API route. Configure Durable
Functions Storage with the Function App identity
(`AzureWebJobsStorage__accountName`) and the required Blob, Queue, and Table
roles. Network rules, private endpoints, retention, alerting, source
integration, and cost controls remain deployment decisions; see
[the Azure architecture status](../../docs/DistributedAgentsAzure.md).
