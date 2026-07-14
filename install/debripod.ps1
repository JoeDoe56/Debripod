$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/JoeDoe56/Debripod.git"
$Branch = "main"
$AppDirName = "debripod"
$VenvDir = ".debripod-venv"
$Port = 8083

function Say($Text) {
    Write-Host $Text
}

function Die($Text) {
    Write-Error $Text
    exit 1
}

function Has-Command($Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Refresh-Path {
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Ask-YesNo($Prompt) {
    while ($true) {
        $answer = Read-Host "$Prompt [y/n]"
        $answer = "$answer".Trim().ToLowerInvariant()

        if ($answer -eq "y" -or $answer -eq "yes") {
            return $true
        }

        if ($answer -eq "n" -or $answer -eq "no") {
            return $false
        }

        Say "Enter y or n."
    }
}

function Get-PythonCommand {
    Refresh-Path

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @("py", "-3")
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @("python")
    }

    return $null
}

function Invoke-Python {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Args
    )

    $cmd = Get-PythonCommand

    if (-not $cmd) {
        Die "Python 3.10 or newer is required. Install Python, close this terminal, open a new one, and rerun this script."
    }

    if ($cmd.Count -eq 2) {
        & $cmd[0] $cmd[1] @Args
    } else {
        & $cmd[0] @Args
    }
}

function Ensure-Winget {
    Refresh-Path

    if (Has-Command "winget") {
        return
    }

    Die "winget is missing. Install App Installer from Microsoft Store, close PowerShell, open it again, and rerun this script."
}

function Ensure-SystemDependencies {
    Ensure-Winget
    Refresh-Path

    if (-not (Has-Command "git")) {
        Say "Installing Git with winget."
        winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
        Refresh-Path
    }

    if (-not (Get-PythonCommand)) {
        Say "Installing Python 3.12 with winget."
        winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
        Refresh-Path
    }

    if (-not (Has-Command "ffmpeg") -or -not (Has-Command "ffprobe")) {
        Say "Installing ffmpeg with winget."
        winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
        Refresh-Path
    }

    if (-not (Has-Command "git")) {
        Die "Git is still missing. Close PowerShell, open it again, and rerun this script."
    }

    if (-not (Get-PythonCommand)) {
        Die "Python is still missing. Close PowerShell, open it again, and rerun this script."
    }

    if (-not (Has-Command "ffmpeg") -or -not (Has-Command "ffprobe")) {
        Die "ffmpeg or ffprobe is still missing. Close PowerShell, open it again, and rerun this script."
    }
}

function Find-DebriPodDir {
    $dirs = Get-ChildItem -LiteralPath "." -Directory -Force | Where-Object { $_.Name -ieq "debripod" }

    if ($dirs.Count -gt 0) {
        return $dirs[0].FullName
    }

    return $null
}

function Ensure-Venv {
    $venvPython = Join-Path $VenvDir "Scripts\python.exe"

    if (-not (Test-Path -LiteralPath $venvPython)) {
        Say "Creating Python virtual environment named debripod."
        Invoke-Python -m venv --prompt debripod $VenvDir
    }

    if (-not (Test-Path -LiteralPath $venvPython)) {
        Die "Virtual environment Python was not created."
    }

    $activate = Join-Path $VenvDir "Scripts\Activate.ps1"
    if (Test-Path -LiteralPath $activate) {
        . $activate
    }

    & $venvPython -m pip install --upgrade pip setuptools wheel
    return $venvPython
}

function Install-PythonDependencies($VenvPython) {
    Say "Installing DebriPod Python dependencies."

    if (Test-Path -LiteralPath "requirements.txt") {
        & $VenvPython -m pip install -r requirements.txt
    }

    & $VenvPython -m pip install -e .
}

function Check-Updates($VenvPython) {
    Say "Checking GitHub for DebriPod updates."

    try {
        git fetch origin $Branch | Out-Null
    } catch {
        Say "Could not check GitHub for updates. Starting the installed copy."
        return
    }

    $localRev = (git rev-parse HEAD).Trim()
    $remoteRev = (git rev-parse "origin/$Branch").Trim()

    if ($localRev -eq $remoteRev) {
        Say "No DebriPod updates found."
        return
    }

    $dirty = git status --porcelain --untracked-files=no
    if ($dirty) {
        Say "DebriPod has local tracked code changes."
        Say "Skipping update so nothing is overwritten."
        return
    }

    if (Ask-YesNo "Updates are available. Pull them now?") {
        git pull --ff-only origin $Branch
        Ensure-SystemDependencies
        Install-PythonDependencies $VenvPython
    } else {
        Say "Skipping update."
    }
}

function Start-App($VenvPython) {
    Say "Starting DebriPod on http://127.0.0.1:$Port"
    & $VenvPython -m debripod.app --port $Port
}

Ensure-SystemDependencies

$appDir = Find-DebriPodDir

if ($appDir) {
    Say "Found existing DebriPod folder: $appDir"
} else {
    Say "No DebriPod folder found. Cloning main into .\$AppDirName"
    git clone --branch $Branch $RepoUrl $AppDirName
    $appDir = Join-Path (Get-Location).Path $AppDirName
}

Set-Location -LiteralPath $appDir

if (-not (Test-Path -LiteralPath ".git")) {
    Die "$appDir is not a Git repository. Refusing to overwrite it."
}

$venvPython = Ensure-Venv

$depsMarker = Join-Path $VenvDir ".debripod-deps-installed"

if (-not (Test-Path -LiteralPath $depsMarker)) {
    Install-PythonDependencies $venvPython
    Get-Date | Out-File -LiteralPath $depsMarker -Encoding UTF8
} else {
    Check-Updates $venvPython
}

Start-App $venvPython
