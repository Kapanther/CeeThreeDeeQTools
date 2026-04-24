$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$metadataPath = Join-Path $repoRoot "CeeThreeDeeQTools\metadata.txt"
$sourceFolder = Join-Path $repoRoot "CeeThreeDeeQTools"
$releasesFolder = Join-Path $repoRoot "Releases"

if (-not (Test-Path $metadataPath)) {
    throw "metadata.txt not found at $metadataPath"
}

if (-not (Test-Path $sourceFolder)) {
    throw "Source plugin folder not found at $sourceFolder"
}

$versionLine = Get-Content $metadataPath | Where-Object { $_ -match "^\s*version\s*=" } | Select-Object -First 1
if (-not $versionLine) {
    throw "Could not find a version entry in $metadataPath"
}

$version = ($versionLine -split "=", 2)[1].Trim()
if ([string]::IsNullOrWhiteSpace($version)) {
    throw "Version value in metadata.txt is empty"
}

if (-not (Test-Path $releasesFolder)) {
    New-Item -Path $releasesFolder -ItemType Directory | Out-Null
}

$zipName = "CeeThreeDeeQToolsV$version.zip"
$zipPath = Join-Path $releasesFolder $zipName

if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$zipArchive = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    $files = Get-ChildItem -Path $sourceFolder -Recurse -File
    foreach ($file in $files) {
        # Preserve the plugin root folder in archive while forcing ZIP-standard separators.
        $relativePath = $file.FullName.Substring($repoRoot.Length).TrimStart('\', '/')
        $entryName = $relativePath -replace '\\', '/'
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zipArchive,
            $file.FullName,
            $entryName,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
}
finally {
    $zipArchive.Dispose()
}

Write-Host "Release package created: $zipPath"
