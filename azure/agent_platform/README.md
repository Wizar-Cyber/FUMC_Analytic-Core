# 10.03 | Distributed agent POC — Azure Functions

> Deployment checkpoint 2026-11-09: `satfumcfunc0e83b2486979` is Running on Linux/Python 3.11 and Azure indexed 33 functions. Easy Auth is enabled; anonymous requests receive 401 and the Entra login route returns 302. A successful authenticated request and agent run have not been verified.

This Azure Functions POC runs three Service Bus workers in parallel (academic,
financial, and wellbeing analysis), then stores the synthesis as a proposal
pending human review. The professional must approve or reject it in the SPA.
It does not send student communications, schedule appointments, award aid, or
make academic/financial decisions automatically.

## 1. POC restrictions

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
- The first authenticated panel load can initialize up to 5,000 synthetic
  records by default (`SYNTHETIC_STUDENT_COUNT`, capped at 5,000); this seed
  operation was not verified through an authenticated session. The Digital
  Twin uses Azure Tables for student profiles, SEMANA_4 snapshots, academic signals,
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
- All dashboard, operational, report, and model-feedback APIs require a
  principal whose Entra object ID is in `CASE_REVIEWER_ALLOWED_PRINCIPAL_IDS`.
  New results are stored as `pending_approval`; the SPA exposes approve/reject
  controls and records a reviewer decision before creating a follow-up.
  The Azure Bicep deployment sets `REVIEWER_AUTH_ENFORCED=true` with App Service
  Authentication; the local example defaults to `false`. Keep it false locally
  unless an authentication stub is configured. All HTTP routes use
  anonymous Functions auth so the browser needs no Function key; each handler
  independently blocks requests from users outside the configured allowlist. Configure
  App Service Authentication to require sign-in for every API route. The
  static interface in `static/` is served by this Function App from the same
  authenticated origin. App Service Authentication must protect the UI and
  every `/api` route. If auth is not configured, the API stays blocked and the
  interface cannot submit or review.
- The `syn-` check is not data-provenance verification. Use only generated
  synthetic records (up to 5,000 by default); seeding and authenticated access
  must be verified before an operational demo. An authenticated user starts
  batches of at most five; agents run sequentially per case and the UI polls until results
  are available. KPI refresh is automatic, but does not invoke the LLM.

## 2. Local configuration

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

## 3. HTTP contract

All routes below require an authenticated Entra principal whose object ID is in
the configured reviewer allowlist. `POST /api/cases` starts one durable workflow and returns an instance ID;
poll `GET /api/cases/{instanceId}` through the authenticated status route. The
API does not return the Durable Functions management URL or a function key.
`GET /api/poc/status` returns the synthetic database summary and processing
switch. `POST /api/poc/state` pauses or resumes new work and rejects a pause
while a case or batch is active. `POST /api/batches` starts a sequential batch
of at most five pending snapshots; poll `GET /api/batches/{batchId}` for status.
`GET /api/reviews` returns aggregate counts, pending proposals, and any generated
results;
`GET /api/reviews/{review_id}` returns the redacted analysis and citation
metadata. `GET /api/reports/reviews` returns the protected rows used by the SPA's
CSV export. These read APIs omit
case tokens, direct identifiers, raw prompts, reviewer IDs, approval notes,
and retrieved source content. The report endpoint is available only in the
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
completed workflow returns a redacted proposal with
`human_review_required: true` and `automated_decision: false`, actual token
counts for the three specialist calls plus the synthesizer, and an estimated
cost when rates are configured. The proposal is not an intervention; only an
authorized professional decision can create a follow-up.

The static frontend is an authenticated SPA with dashboard, student profiles,
alerts, follow-ups, analytics, faculties/programs, reports, and read-only
configuration. Every query uses the protected same-origin Functions API.
KPI/chart clicks apply student filters; alert/follow-up changes persist to
Azure Tables; report export downloads a protected CSV projection; the
dashboard refreshes every 30 seconds. Only the explicit batch action invokes
the LLM. A small “Demo · registros generados” label remains so the UI does not
misrepresent the dataset as institutional data.

## 4. Operational prerequisites and deployment status

Use [the Bicep template](infra/README.md) to provision queues
`socioeconomic-analysis`, `academic-analysis`, `wellbeing-analysis`, and `agent-results`, plus a
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
