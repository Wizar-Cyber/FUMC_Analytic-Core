# Infrastructure for the SAT-FUMC agent POC

`main.bicep` provisions the Azure OpenAI account and GPT-5-mini deployment,
Flex Consumption Function App, dedicated Storage account, Key Vault, workspace-
based Application Insights, Log Analytics workspace, and Service Bus Standard
namespace in the existing Brazil South resource group. It creates the three
queues, private review and deployment-package Blob containers, and stores the
Entra client secret in Key Vault. The Function App uses a system-assigned
managed identity for model, Service Bus, Key Vault, deployment package, review
Blob, Azure Tables, and Durable Functions storage access. On first authenticated
panel load, the app initializes 500 synthetic student profiles and SEMANA_4
snapshots in separate tables for students, academic signals, finance, wellbeing,
and target traceability. The target table is never queried by the agents.
Academic RAG stays disabled; no Azure AI Search service or institutional source
connector is created.

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

## Prerequisites

- The target resource group must exist before deployment.
- The Entra app registration must use the target tenant. Add the authorized
  user's Entra object ID to `reviewerPrincipalIds`. Configure its Web redirect URI as
  `https://<functionAppName>.azurewebsites.net/.auth/login/aad/callback`.
- Supply the app registration client ID and client secret through a protected
  deployment channel. The secret is written to Key Vault by the deployment;
  never store it in a parameter file or source control.
- The deployer needs permission to create the listed resources and managed-identity
  role assignments, register resource providers, and create a subscription budget.

## Validation and deployment

Build both templates before deploying:

```powershell
bicep build .\main.bicep
bicep build .\budget.bicep
```

Run a resource-group What-If for `main.bicep` and a subscription What-If for
`budget.bicep`. Review the proposed resources, prices, identity role
assignments, public endpoints, and alert contacts before deployment. After
provisioning and RBAC propagation, publish the Python Function App from this
directory with Azure Functions Core Tools v4 and remote build, then verify
Entra sign-in and managed-identity access before starting one bounded synthetic
batch from the authenticated panel.

This POC intentionally remains synthetic-only and human-reviewed. The app and
service endpoints are public, but protected by Entra or managed identity; Blob
containers are private and Storage shared-key access is disabled. This
template does not configure VNet integration or private endpoints, a
production SLA, an institutional SIS/LMS integration, or an Azure spending
hard cap. Assess private networking and production operations before use with
real data.
