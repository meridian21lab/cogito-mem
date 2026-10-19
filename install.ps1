# Install cogito-mem on Windows and connect it to every chat client found (experimental).
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/meridian21lab/cogito-mem/main/install.ps1 | iex"
#
# Installs uv if missing; uv brings Python. COGITO_MEM_SOURCE overrides where cogito-mem comes from.
$ErrorActionPreference = "Stop"
$source = if ($env:COGITO_MEM_SOURCE) { $env:COGITO_MEM_SOURCE } else { "git+https://github.com/meridian21lab/cogito-mem" }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "cogito-mem: installing uv"
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Host "cogito-mem: installing cogito-mem from $source"
uv tool install --force --quiet --python 3.12 $source
$env:Path = "$(uv tool dir --bin);$env:Path"

cogito-mem install @args
Write-Host "cogito-mem: done. Check the install any time with: cogito-mem doctor"
