targetScope = 'resourceGroup'

@description('Nombre del Workspace de Azure Machine Learning')
param workspaceName string = 'FUMCAnalitysReviewer'

@description('Ubicación de los recursos')
param location string = 'brazilsouth'

@description('Nombre de la cuenta de almacenamiento')
param storageAccountName string = 'fumcanalitysre1136846796'

@description('Nombre del Key Vault')
param keyVaultName string = 'fumcanalitysre3923938785'

@description('Nombre de Application Insights')
param appInsightsName string = 'fumcanalitysre0088876584'

// 1. Storage Account
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    encryption: {
      services: {
        blob: {
          enabled: true
        }
        file: {
          enabled: true
        }
      }
      keySource: 'Microsoft.Storage'
    }
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    publicNetworkAccess: 'Enabled'
  }
}

// 2. Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      name: 'standard'
      family: 'A'
    }
    accessPolicies: []
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

// 3. Application Insights
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// 4. Azure Machine Learning Workspace
resource amlWorkspace 'Microsoft.MachineLearningServices/workspaces@2023-08-01-preview' = {
  name: workspaceName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    friendlyName: 'FUMC Analytics Reviewer'
    description: 'Sistema de Alerta Temprana de Desercion Estudiantil - FUMC'
    storageAccount: storageAccount.id
    keyVault: keyVault.id
    applicationInsights: appInsights.id
    publicNetworkAccess: 'Enabled'
    v1LegacyMode: false
  }
}

// 5. Presupuesto Mensual de 100 USD
resource monthlyBudget 'Microsoft.Consumption/budgets@2021-10-01' = {
  name: 'Presupuesto-Mensual-FUMC-100USD'
  properties: {
    timeGrain: 'Monthly'
    amount: 100
    category: 'Cost'
    timePeriod: {
      startDate: '2026-11-01T00:00:00Z'
    }
    notifications: {
      Notification80Percent: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 80
        contactEmails: [
          'reverse05@outlook.es'
        ]
        thresholdType: 'Actual'
      }
      Notification100Percent: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        contactEmails: [
          'reverse05@outlook.es'
        ]
        thresholdType: 'Actual'
      }
    }
  }
}

output workspaceId string = amlWorkspace.properties.workspaceId
output workspaceResourceId string = amlWorkspace.id
