targetScope = 'resourceGroup'

@description('Azure region for the Function App and Service Bus namespace.')
param location string = 'brazilsouth'

@description('Unique globally routable Azure Functions app name.')
param functionAppName string = 'FUMCanalyticscore'

@description('Unique globally routable Service Bus namespace name.')
param serviceBusNamespaceName string = 'satfumc-sb-${uniqueString(resourceGroup().id)}'

@description('Dedicated Storage account name for agent host data, deployment packages, and reviews.')
param storageAccountName string = 'fumcanalyticsre113684679'

@description('Application Insights component for Function telemetry.')
param applicationInsightsName string = 'fumcanalyticsre0088876584'

@description('Azure OpenAI account that hosts the approved model deployment.')
param aiServicesAccountName string = 'FUMCAnalitysReviewer'

@description('Key Vault that securely stores the Entra application secret.')
param keyVaultName string = 'fumcanalyticsre392393878'

@description('Administrator login for the Azure SQL operational database.')
param sqlAdminLogin string = 'satadmin'

@secure()
@description('Administrator password for the Azure SQL operational database. Supply directly at deployment time.')
param sqlAdminPassword string

@description('UPN of the Microsoft Entra admin for Azure SQL. When set together with the object id, SQL authentication is disabled (Entra-only).')
param sqlEntraAdminLogin string = ''

@description('Object id of the Microsoft Entra admin for Azure SQL.')
param sqlEntraAdminObjectId string = ''

@description('Azure SQL logical server name.')
param sqlServerName string = 'satfumc-sql-${uniqueString(resourceGroup().id)}'

@description('Operational Azure SQL database name.')
param sqlDatabaseName string = 'SATFUMCOperational'

@description('Existing Azure OpenAI model deployment name.')
param openAiDeploymentName string = 'sat-gpt5-mini'

@description('Microsoft Entra tenant containing the reviewer app registration.')
param entraTenantId string = '92d08b37-eb78-4694-96ba-64191bdb06c8'

@description('Client ID of an existing Entra app registration configured for Easy Auth.')
param entraClientId string

@secure()
@description('Client secret for the existing Entra app registration. Supply securely at deployment time; never store it in a parameter file.')
param entraClientSecret string

@description('Comma-separated Entra user object IDs allowed to review cases.')
param reviewerPrincipalIds string

var queueNames = [
  'socioeconomic-analysis'
  'academic-analysis'
  'wellbeing-analysis'
  'agent-results'
]

var cognitiveServicesOpenAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var serviceBusDataSenderRoleId = '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
var serviceBusDataReceiverRoleId = '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'
var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
var storageTableDataContributorRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'

resource functionStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      bypass: 'None'
      defaultAction: 'Allow'
    }
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: entraTenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }
}

resource sqlServer 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: sqlServerName
  location: location
  properties: {
    administratorLogin: sqlAdminLogin
    administratorLoginPassword: sqlAdminPassword
    version: '12.0'
    publicNetworkAccess: 'Enabled'
    minimalTlsVersion: '1.2'
    restrictOutboundNetworkAccess: 'Disabled'
  }
}

resource sqlDatabase 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sqlServer
  name: sqlDatabaseName
  location: location
  sku: {
    name: 'GP_S_Gen5_1'
    tier: 'GeneralPurpose'
    family: 'Gen5'
    capacity: 1
  }
  properties: {
    collation: 'SQL_Latin1_General_CP1_CI_AS'
    autoPauseDelay: 60
    minCapacity: json('0.5')
    maxSizeBytes: 2147483648
    zoneRedundant: false
    readScale: 'Disabled'
    requestedBackupStorageRedundancy: 'Local'
  }
}

resource sqlAzureServicesFirewall 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = {
  parent: sqlServer
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource sqlEntraAdmin 'Microsoft.Sql/servers/administrators@2023-08-01-preview' = if (!empty(sqlEntraAdminLogin) && !empty(sqlEntraAdminObjectId)) {
  parent: sqlServer
  name: 'ActiveDirectory'
  properties: {
    administratorType: 'ActiveDirectory'
    login: sqlEntraAdminLogin
    sid: sqlEntraAdminObjectId
    tenantId: entraTenantId
  }
}

resource sqlEntraOnly 'Microsoft.Sql/servers/azureADOnlyAuthentications@2023-08-01-preview' = if (!empty(sqlEntraAdminLogin) && !empty(sqlEntraAdminObjectId)) {
  parent: sqlServer
  name: 'Default'
  dependsOn: [
    sqlEntraAdmin
  ]
  properties: {
    azureADOnlyAuthentication: true
  }
}

resource entraClientSecretVaultSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'entra-client-secret'
  properties: {
    value: entraClientSecret
    contentType: 'text/plain'
  }
}

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${applicationInsightsName}-law'
  location: location
  properties: {
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    workspaceCapping: {
      dailyQuotaGb: 1
    }
  }
  sku: {
    name: 'PerGB2018'
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: applicationInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    IngestionMode: 'LogAnalytics'
    WorkspaceResourceId: logAnalyticsWorkspace.id
  }
}

resource aiServicesAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: aiServicesAccountName
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: toLower(aiServicesAccountName)
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

resource openAiDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aiServicesAccount
  name: openAiDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: 50
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5-mini'
      version: '2025-08-07'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

resource functionBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' existing = {
  parent: functionStorage
  name: 'default'
}

resource functionPlan 'Microsoft.Web/serverfarms@2024-11-01' = {
  name: '${functionAppName}-plan'
  location: location
  kind: 'linux'
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: {
    reserved: true
  }
}

resource serviceBusNamespace 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: serviceBusNamespaceName
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
    capacity: 0
  }
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }
}

resource serviceBusQueues 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' = [for queueName in queueNames: {
  parent: serviceBusNamespace
  name: queueName
  properties: {
    deadLetteringOnMessageExpiration: true
    defaultMessageTimeToLive: 'P1D'
    duplicateDetectionHistoryTimeWindow: 'PT10M'
    lockDuration: 'PT5M'
    maxDeliveryCount: 5
    requiresDuplicateDetection: true
  }
}]

resource reviewContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: functionBlobService
  name: 'student-case-reviews'
  properties: {
    publicAccess: 'None'
  }
}

resource functionDeploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: functionBlobService
  name: 'function-deployment-packages'
  properties: {
    publicAccess: 'None'
  }
}

var storageBlobEndpoint = 'https://${functionStorage.name}.blob.${environment().suffixes.storage}'
var functionDeploymentContainerUrl = '${storageBlobEndpoint}/${functionDeploymentContainer.name}'

resource functionApp 'Microsoft.Web/sites@2024-11-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: functionPlan.id
    httpsOnly: true
    publicNetworkAccess: 'Enabled'
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: functionDeploymentContainerUrl
          authentication: {
            type: 'SystemAssignedIdentity'
          }
        }
      }
      runtime: {
        name: 'python'
        version: '3.11'
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 1
        instanceMemoryMB: 2048
      }
    }
    siteConfig: {
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      http20Enabled: true
    }
  }
}

resource functionAppSettings 'Microsoft.Web/sites/config@2024-11-01' = {
  parent: functionApp
  name: 'appsettings'
  properties: {
    APPLICATIONINSIGHTS_CONNECTION_STRING: applicationInsights.properties.ConnectionString
    AZURE_OPENAI_API_VERSION: '2025-04-01-preview'
    AZURE_OPENAI_CHAT_DEPLOYMENT: openAiDeploymentName
    AZURE_OPENAI_ENDPOINT: aiServicesAccount.properties.endpoint
    AZURE_OPENAI_INPUT_PRICE_PER_1M_TOKENS: '0.25'
    AZURE_OPENAI_MODEL: 'gpt-5-mini'
    AZURE_OPENAI_OUTPUT_PRICE_PER_1M_TOKENS: '2.00'
    AzureWebJobsFeatureFlags: 'EnableWorkerIndexing'
    AzureWebJobsStorage__accountName: functionStorage.name
    AzureWebJobsStorage__credential: 'managedidentity'
    BLOB_STORAGE_URL: storageBlobEndpoint
    CASE_REVIEWER_ALLOWED_PRINCIPAL_IDS: reviewerPrincipalIds
    DATA_MODE: 'synthetic'
    ENTRA_CLIENT_SECRET: '@Microsoft.KeyVault(SecretUri=https://${keyVault.name}${environment().suffixes.keyvaultDns}/secrets/entra-client-secret)'
    FUNCTIONS_EXTENSION_VERSION: '~4'
    POC_ENABLED: 'true'
    REVIEWER_AUTH_ENFORCED: 'true'
    REVIEWS_CONTAINER: reviewContainer.name
    SERVICEBUS_NAMESPACE: '${serviceBusNamespace.name}.servicebus.windows.net'
    SQL_PERSISTENCE_ENABLED: 'true'
    SQL_SERVER: sqlServer.properties.fullyQualifiedDomainName
    SQL_DATABASE: sqlDatabase.name
    ServiceBusConnection__fullyQualifiedNamespace: '${serviceBusNamespace.name}.servicebus.windows.net'
    ACADEMIC_RAG_ENABLED: 'false'
    AZURE_SEARCH_ENDPOINT: ''
    AZURE_SEARCH_INDEX: ''
  }
}

resource functionAppAuth 'Microsoft.Web/sites/config@2024-11-01' = {
  parent: functionApp
  name: 'authsettingsV2'
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: entraClientId
          clientSecretSettingName: 'ENTRA_CLIENT_SECRET'
          openIdIssuer: '${environment().authentication.loginEndpoint}${entraTenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [
            entraClientId
          ]
        }
      }
    }
    login: {
      tokenStore: {
        enabled: false
      }
    }
  }
}

resource functionKeyVaultSecretsAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, keyVaultSecretsUserRoleId, functionAppName)
  scope: keyVault
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
  }
}

resource openAiUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServicesAccount.id, cognitiveServicesOpenAiUserRoleId, functionAppName)
  scope: aiServicesAccount
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAiUserRoleId)
  }
}

resource serviceBusSenderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(serviceBusNamespace.id, serviceBusDataSenderRoleId, functionAppName)
  scope: serviceBusNamespace
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', serviceBusDataSenderRoleId)
  }
}

resource serviceBusReceiverAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(serviceBusNamespace.id, serviceBusDataReceiverRoleId, functionAppName)
  scope: serviceBusNamespace
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', serviceBusDataReceiverRoleId)
  }
}

resource storageBlobOwnerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(functionStorage.id, storageBlobDataOwnerRoleId, functionAppName)
  scope: functionStorage
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwnerRoleId)
  }
}

resource durableQueueAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(functionStorage.id, storageQueueDataContributorRoleId, functionAppName)
  scope: functionStorage
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
  }
}

resource durableTableAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(functionStorage.id, storageTableDataContributorRoleId, functionAppName)
  scope: functionStorage
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageTableDataContributorRoleId)
  }
}

output functionAppName string = functionApp.name
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output aiServicesAccountName string = aiServicesAccount.name
output openAiDeploymentName string = openAiDeployment.name
output applicationInsightsName string = applicationInsights.name
output keyVaultName string = keyVault.name
output serviceBusNamespaceName string = serviceBusNamespace.name
output serviceBusNamespaceEndpoint string = '${serviceBusNamespace.name}.servicebus.windows.net'
output functionStorageAccountName string = functionStorage.name
output sqlServerName string = sqlServer.name
output sqlDatabaseName string = sqlDatabase.name
