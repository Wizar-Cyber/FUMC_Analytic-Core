targetScope = 'subscription'

@description('Monthly subscription spending alert amount in USD.')
param budgetAmount int = 100

@description('Email address that receives monthly budget notifications.')
param contactEmail string

@description('Budget end date in UTC.')
param endDate string = '2027-10-31T23:59:59Z'

resource monthlyBudget 'Microsoft.Consumption/budgets@2023-05-01' = {
  name: 'FUMC-SAT-POC-monthly-100USD'
  properties: {
    category: 'Cost'
    amount: budgetAmount
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: '2026-11-01T00:00:00Z'
      endDate: endDate
    }
    notifications: {
      Actual50Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 50
        thresholdType: 'Actual'
        contactEmails: [
          contactEmail
        ]
      }
      Actual80Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: [
          contactEmail
        ]
      }
      Actual100Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: [
          contactEmail
        ]
      }
      Forecast80Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 80
        thresholdType: 'Forecasted'
        contactEmails: [
          contactEmail
        ]
      }
    }
  }
}
