# 10.04 | Azure infrastructure for the SAT-FUMC agent POC

> **Verified 2026-11-09:** Bicep deployment `satfumc-prod` succeeded. The Function App is Running on Python 3.11 with 33 indexed functions. Azure SQL is Online and the schema below has been applied. This is infrastructure and host verification, not authenticated application E2E or SQL-backed runtime integration.

`main.bicep` provisions the Azure OpenAI account and GPT-5-mini deployment,
Flex Consumption Function App, dedicated Storage account, Key Vault, workspace-
based Application Insights, Log Analytics workspace, Azure SQL operational
server/database, and Service Bus Standard namespace in the existing Brazil South
resource group. It creates the four queues (`socioeconomic-analysis`,
`academic-analysis`, `wellbeing-analysis`, and `agent-results`), private review
and deployment-package Blob containers, and stores the Entra client secret in
Key Vault. The Function App uses a system-assigned managed identity for model,
Service Bus, Key Vault, deployment package, review Blob, Azure Tables, and
Durable Functions storage access. The operational Azure SQL database stores the
cohort snapshots, model releases, predictions, agent executions, review
proposals, human decisions, intervention state, and audit events declared in
`sql_schema.sql`. On first authenticated panel load, the app can initialize up to 5,000
synthetic student profiles and SEMANA_4 snapshots in separate tables for
students, academic signals, finance, wellbeing, and target traceability. The
target table is never queried by the agents. Academic RAG stays disabled; no
Azure AI Search service or institutional source connector is created.

Batch processing is explicit and sequential, up to five pending cases per run.
There is no timer, scheduled job, or startup inference. The authenticated reviewer
can pause new work from the UI; pausing is rejected while a case or batch is
active. Flex Consumption can scale the host down when idle, but this processing
switch does not delete Azure resources.

`budget.bicep` configures subscription-level monthly cost alerts at USD 50, 80,
and 100, plus an 80% forecast alert. **Azure budgets send notifications; they
do not cap, pause, or stop charges.** Resource charges can exceed the budget
before an alert is delivered. The $100 value is an alert threshold, not a
guaranteed maximum spend.

## 1. Prerequisites

- The target resource group must exist before deployment.
- The Entra app registration must use the target tenant. Add the authorized
  user's Entra object ID to `reviewerPrincipalIds`. Configure its Web redirect URI as
  `https://<functionAppName>.azurewebsites.net/.auth/login/aad/callback`.
- Supply the app registration client ID and client secret through a protected
  deployment channel. The secret is written to Key Vault by the deployment;
  never store it in a parameter file or source control.
- The deployer needs permission to create the listed resources and managed-identity
  role assignments, register resource providers, and create a subscription budget.

## 2. Validation, provisioning, and code publication

Build both templates before deploying:

```powershell
bicep build .\main.bicep
bicep build .\budget.bicep
```

Run a resource-group What-If for `main.bicep` and a subscription What-If for
`budget.bicep`. Review the proposed resources, prices, identity role
assignments, public endpoints, and alert contacts before deployment. The
verified provisioning created the Function App, plan, queues, Storage, Key
Vault, Application Insights, Azure OpenAI and Azure SQL in
`rg-sat-fumc-prod`. The schema in `sql_schema.sql` was applied to
`SATFUMCOperational`; it creates nine tables but does not connect the Python app
to SQL. The agent POC continues to persist synthetic state in Azure Tables/Blob.

The Functions code was published with Azure Functions Core Tools v4 and remote
build from a staged package. Its root included `host.json`, `function_app.py`,
`requirements.txt`, `sat_agents/`, `static/`, and the shared
`src/ml/feedback_loop.py` module imported at Function startup. Future publishes
must include it. Never publish `local.settings.json` or secret values. The
configured Flex runtime is Python 3.11.

After provisioning and RBAC propagation, complete an interactive Entra sign-in
with an allowlisted reviewer and verify a read-only API response before running
one bounded synthetic batch. On 2026-11-09 anonymous requests returned `401` and
the Entra login endpoint redirected with `302`; no authenticated `200` or batch
execution was verified.

This POC intentionally remains synthetic-only and human-reviewed. The app and
service endpoints are public, but protected by Entra or managed identity; Blob
containers are private and Storage shared-key access is disabled. Azure SQL is
provisioned but not used by Functions. The template does not configure VNet integration or private endpoints, a
production SLA, an institutional SIS/LMS integration, or an Azure spending
hard cap. Assess private networking and production operations before use with
real data.
