<#
.SYNOPSIS
Builds a native Windows x64 auto_rx release ZIP with MinGW-w64.

.DESCRIPTION
Compiles the 17 auto_rx decoder executables, stages the Python application and
Windows receiver tools, then creates release/windows/auto_rx-windows-<version>.zip.
Required third-party tools are read from third_party/windows/bin and validated
before compilation.
#>
[CmdletBinding()]
param(
    [string]$Version,
    [string]$MakeCommand = "mingw32-make",
    [string]$Compiler = "x86_64-w64-mingw32-gcc",
    [string]$ThirdPartyBin,
    [string]$ReleaseRoot,
    [switch]$ValidateOnly,
    [switch]$StageApplicationOnly,
    [string]$SourceRoot,
    [switch]$KeepRelease
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ThirdPartyBin)) {
    $ThirdPartyBin = Join-Path $PSScriptRoot "third_party/windows/bin"
}
if ([string]::IsNullOrWhiteSpace($ReleaseRoot)) {
    $ReleaseRoot = Join-Path $PSScriptRoot "release/windows"
}
if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $SourceRoot = $PSScriptRoot
}

$DecoderPrograms = @(
    "dft_detect", "fsk_demod", "imet4iq", "mk2a1680mod", "rs41mod",
    "dfm09mod", "m10mod", "m20mod", "rs92mod", "lms6Xmod",
    "meisei100mod", "imet54mod", "mp3h1mod", "mts01mod", "iq_dec",
    "weathex301d", "rd94rd41drop"
)

$RequiredWindowsTools = @("rtl_fm.exe", "rtl_power.exe", "sox.exe")

function Get-MissingWindowsTools {
    param([string]$SourceDirectory)

    if (-not (Test-Path -LiteralPath $SourceDirectory -PathType Container)) {
        return $RequiredWindowsTools
    }

    return @($RequiredWindowsTools | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $SourceDirectory $_) -PathType Leaf)
    })
}

function Assert-WindowsTools {
    param([string]$SourceDirectory)

    $missing = Get-MissingWindowsTools -SourceDirectory $SourceDirectory
    if ($missing.Count -gt 0) {
        $list = $missing -join ", "
        throw "Missing required third-party Windows tools in '$SourceDirectory': $list. Place rtl_fm.exe, rtl_power.exe, sox.exe and their required DLLs in third_party/windows/bin before building a release."
    }
}

function Get-AutoRxVersion {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $python) {
        throw "Python is required to determine the auto_rx version. Install Python 3 or pass -Version."
    }

    $arguments = if ($python.Name -ieq "py.exe") { @("-3", "-c", "import sys; sys.path.insert(0, 'auto_rx'); import autorx; print(autorx.__version__)") } else { @("-c", "import sys; sys.path.insert(0, 'auto_rx'); import autorx; print(autorx.__version__)") }
    $detected = (& $python.Source @arguments 2>$null | Select-Object -First 1).Trim()
    if ([string]::IsNullOrWhiteSpace($detected)) {
        throw "Could not determine the auto_rx version. Pass -Version explicitly."
    }
    return $detected
}

function Copy-TrackedAutoRxApplication {
    param(
        [string]$ApplicationSourceRoot,
        [string]$DestinationDirectory
    )

    # Explicitly limit release contents to tracked runtime code and assets. In
    # particular, never infer release files by recursively copying auto_rx.
    $trackedFiles = @(& git -C $ApplicationSourceRoot ls-files -- `
        "auto_rx/auto_rx.py" `
        "auto_rx/autorx" `
        "auto_rx/utils" `
        "auto_rx/log/log_files_go_here.txt" `
        "auto_rx/requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Could not list tracked auto_rx application files in '$ApplicationSourceRoot'."
    }

    foreach ($trackedFile in $trackedFiles) {
        if (-not $trackedFile.StartsWith("auto_rx/")) {
            throw "Unexpected tracked application path '$trackedFile'."
        }

        $sourceFile = Join-Path $ApplicationSourceRoot $trackedFile
        $relativeDestination = $trackedFile.Substring("auto_rx/".Length)
        $destinationFile = Join-Path $DestinationDirectory $relativeDestination
        $destinationParent = Split-Path -Parent $destinationFile
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        Copy-Item -LiteralPath $sourceFile -Destination $destinationFile -Force
    }

    # The Windows example is the only station configuration included in a release.
    $windowsExample = Join-Path $ApplicationSourceRoot "auto_rx/station.cfg.example.windows"
    if (-not (Test-Path -LiteralPath $windowsExample -PathType Leaf)) {
        throw "Missing Windows station configuration example: $windowsExample"
    }
    Copy-Item -LiteralPath $windowsExample -Destination (Join-Path $DestinationDirectory "station.cfg.example.windows") -Force
}

function Initialize-ReleaseDirectory {
    param(
        [string]$Root,
        [string]$Name
    )

    $directory = Join-Path $Root $Name
    $archive = Join-Path $Root "$Name.zip"
    if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force }
    if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    return @{ Directory = $directory; Archive = $archive }
}

if ($StageApplicationOnly) {
    if ([string]::IsNullOrWhiteSpace($Version)) { $Version = "staging-test" }
    $stage = Initialize-ReleaseDirectory -Root $ReleaseRoot -Name "auto_rx-windows-$Version"
    $applicationDirectory = Join-Path $stage.Directory "auto_rx"
    New-Item -ItemType Directory -Path $applicationDirectory -Force | Out-Null
    Copy-TrackedAutoRxApplication -ApplicationSourceRoot $SourceRoot -DestinationDirectory $applicationDirectory
    Compress-Archive -LiteralPath $stage.Directory -DestinationPath $stage.Archive -Force
    Write-Host "Created application staging directory: $($stage.Directory)"
    Write-Host "Created application staging archive: $($stage.Archive)"
    return
}

Assert-WindowsTools -SourceDirectory $ThirdPartyBin
if ($ValidateOnly) {
    Write-Host "Validated third-party Windows tools in $ThirdPartyBin."
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    Push-Location $PSScriptRoot
    try {
        $Version = Get-AutoRxVersion
    } finally {
        Pop-Location
    }
}

$make = Get-Command $MakeCommand -ErrorAction SilentlyContinue
if (-not $make) {
    throw "Could not find '$MakeCommand'. Install MinGW-w64 make or pass -MakeCommand with the correct executable."
}
$compiler = Get-Command $Compiler -ErrorAction SilentlyContinue
if (-not $compiler) {
    throw "Could not find '$Compiler'. Install a MinGW-w64 x86_64 compiler or pass -Compiler with the correct executable."
}

Push-Location $PSScriptRoot
try {
    & $make.Source clean "CC=$($compiler.Source)" "AUTO_RX_VERSION=$Version"
    if ($LASTEXITCODE -ne 0) { throw "MinGW clean failed with exit code $LASTEXITCODE." }
    & $make.Source all "CC=$($compiler.Source)" "AUTO_RX_VERSION=$Version"
    if ($LASTEXITCODE -ne 0) { throw "MinGW build failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}

$releaseName = "auto_rx-windows-$Version"
$stage = Initialize-ReleaseDirectory -Root $ReleaseRoot -Name $releaseName
$releaseDirectory = $stage.Directory
$archivePath = $stage.Archive

$binDirectory = Join-Path $releaseDirectory "bin"
$applicationDirectory = Join-Path $releaseDirectory "auto_rx"
New-Item -ItemType Directory -Path $binDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $applicationDirectory -Force | Out-Null
Copy-TrackedAutoRxApplication -ApplicationSourceRoot $SourceRoot -DestinationDirectory $applicationDirectory
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README.md") -Destination $releaseDirectory -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "LICENSE") -Destination $releaseDirectory -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "release/windows/start-auto-rx.cmd") -Destination $releaseDirectory -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "release/windows/diagnose.cmd") -Destination $releaseDirectory -Force

foreach ($program in $DecoderPrograms) {
    $matches = @(Get-ChildItem -LiteralPath $PSScriptRoot -Recurse -File -Filter "$program.exe" | Where-Object {
        $_.FullName -notlike "*$([IO.Path]::DirectorySeparatorChar)release$([IO.Path]::DirectorySeparatorChar)*"
    })
    if ($matches.Count -ne 1) {
        throw "Expected one MinGW decoder executable named $program.exe, found $($matches.Count)."
    }
    Copy-Item -LiteralPath $matches[0].FullName -Destination $binDirectory -Force
}

Copy-Item -Path (Join-Path $ThirdPartyBin "*") -Destination $binDirectory -Recurse -Force
Compress-Archive -LiteralPath $releaseDirectory -DestinationPath $archivePath -Force
Write-Host "Created Windows release: $releaseDirectory"
Write-Host "Created Windows archive: $archivePath"

if (-not $KeepRelease) {
    Remove-Item -LiteralPath $releaseDirectory -Recurse -Force
    Write-Host "Removed staging directory; the ZIP is the release artifact. Pass -KeepRelease to retain it."
}
