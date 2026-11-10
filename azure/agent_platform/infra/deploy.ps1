param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroupName,

    [Parameter()]
    [string]$Location = 'brazilsouth',

    [Parameter()]
    [string]$TemplateFile = (Join-Path $PSScriptRoot 'main.bicep'),

    [Parameter()]
    [string]$ParametersFile = (Join-Path $PSScriptRoot 'main.parameters.example.json'),

    [Parameter()]
    [string]$SqlAdminLogin = 'satadmin'
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI (az) is required. Install it and sign in with `az login` before deployment.'
}

$null = az account show --output none 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'No Azure session is active. Run `az login` and select a subscription before running this deploy script.'
}

$securePassword = Read-Host 'Enter the Azure SQL admin password'

az group create --name $ResourceGroupName --location $Location | Out-Null
az deployment group create `
    --resource-group $ResourceGroupName `
    --template-file $TemplateFile `
    --parameters @$ParametersFile `
    sqlAdminLogin=$SqlAdminLogin `
    sqlAdminPassword=$securePassword | Out-Null

Write-Host "Deployment complete for resource group '$ResourceGroupName'."
Write-Host 'Use the deployment outputs to configure the Function App and the SQL connection strings.'
