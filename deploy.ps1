param (
    [Parameter(Mandatory=$true)]
    [string]$VpsUser,

    [Parameter(Mandatory=$true)]
    [string]$VpsIp,

    [Parameter(Mandatory=$false)]
    [string]$DestDir = "",

    [Parameter(Mandatory=$false)]
    [string]$SshKeyPath = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrEmpty($DestDir)) {
    if ($VpsUser -eq "root") {
        $DestDir = "/root/gosuslugi_bot"
    } else {
        $DestDir = "/home/$VpsUser/gosuslugi_bot"
    }
}

# Define local script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrEmpty($ScriptDir)) { $ScriptDir = Get-Location }

Write-Host "=== Gosuslugi Bot Deployment Packaging ===" -ForegroundColor Cyan
Write-Host "Local Directory: $ScriptDir"
Write-Host "Target: $VpsUser@$VpsIp : $DestDir"

# Create a temporary directory for zipping
$TempZipDir = Join-Path $env:TEMP "gosuslugi_bot_deploy_temp"
if (Test-Path $TempZipDir) {
    Remove-Item -Recurse -Force $TempZipDir
}
New-Item -ItemType Directory -Path $TempZipDir | Out-Null

# Helper function to replicate directory structure
function Force-Copy-To-Temp {
    param($DestBase, $SrcBase)
    process {
        $destFile = $_.FullName.Replace($SrcBase, $DestBase)
        $destSubDir = Split-Path -Parent $destFile
        if (!(Test-Path $destSubDir)) {
            New-Item -ItemType Directory -Path $destSubDir -Force | Out-Null
        }
        Copy-Item -Path $_.FullName -Destination $destFile -Force
    }
}

# Copy files, excluding caches, local virtual environments, database files, and local logs
Write-Host "Filtering and copying files to temp folder..." -ForegroundColor Gray
$ExcludePatterns = @("*.pyc", "__pycache__", ".venv", "venv", ".git", ".env", "*.log", "generated_sites", "deploy.ps1", "*.zip")

Get-ChildItem -Path $ScriptDir -Recurse | Where-Object {
    $relativePath = $_.FullName.Substring($ScriptDir.Length)
    $shouldExclude = $false
    foreach ($pattern in $ExcludePatterns) {
        if ($relativePath -like "*$pattern*") {
            $shouldExclude = $true
            break
        }
    }
    !$shouldExclude -and !$_.PSIsContainer
} | Force-Copy-To-Temp -DestBase $TempZipDir -SrcBase $ScriptDir

# Zip the temp folder
$ZipFile = Join-Path $ScriptDir "gosuslugi_bot.zip"
if (Test-Path $ZipFile) {
    Remove-Item $ZipFile -Force
}
Write-Host "Creating zip archive: $ZipFile" -ForegroundColor Gray
Compress-Archive -Path "$TempZipDir\*" -DestinationPath $ZipFile -Force

# Clean up temp folder
Remove-Item -Recurse -Force $TempZipDir

# Upload Zip using SCP
Write-Host "Uploading archive to VPS..." -ForegroundColor Cyan

# Prepare SSH/SCP arguments
$SshArgs = @()
$ScpArgs = @()
if ($SshKeyPath) {
    $SshArgs += "-i", $SshKeyPath
    $ScpArgs += "-i", $SshKeyPath
}
$SshArgs += "${VpsUser}@${VpsIp}"

# Create remote dir if not exists
Write-Host "Creating destination directory on remote server..." -ForegroundColor Gray
& ssh @SshArgs "mkdir -p $DestDir"

# SCP zip file
$ScpArgs += $ZipFile
$ScpArgs += "${VpsUser}@${VpsIp}:$DestDir/"
Write-Host "Running: scp [args]"
& scp @ScpArgs

# SSH to unzip and clean up
Write-Host "Extracting archive on remote server..." -ForegroundColor Cyan
& ssh @SshArgs "cd $DestDir && unzip -o gosuslugi_bot.zip && rm gosuslugi_bot.zip && [ ! -f .env ] && cp .env.example .env || true"

# Clean up local zip file
if (Test-Path $ZipFile) {
    Remove-Item $ZipFile -Force
}

Write-Host "=== Packaged & Uploaded Successfully! ===" -ForegroundColor Green
Write-Host "Next Steps on VPS:"
Write-Host "1. SSH to VPS: ssh $VpsUser@$VpsIp"
Write-Host "2. Navigate: cd $DestDir"
Write-Host "3. Edit environment configuration: nano .env"
Write-Host "4. Start services: docker compose up --build -d"
