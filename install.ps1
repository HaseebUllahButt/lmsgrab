# One-line installer for lmsgrab on Windows. In PowerShell:
#   irm https://raw.githubusercontent.com/HaseebUllahButt/lmsgrab/main/install.ps1 | iex
#
# No pip needed — it's pure Python. This drops the code in your user folder,
# puts an `lms` command on your PATH, then walks you through setup.

function Install-Lmsgrab {
  $ErrorActionPreference = 'Stop'
  $Repo   = if ($env:LMSGRAB_REPO)   { $env:LMSGRAB_REPO }   else { 'HaseebUllahButt/lmsgrab' }
  $Branch = if ($env:LMSGRAB_BRANCH) { $env:LMSGRAB_BRANCH } else { 'main' }
  $AppDir = Join-Path $env:LOCALAPPDATA 'lmsgrab'
  $BinDir = Join-Path $AppDir 'bin'

  # --- need Python 3 -------------------------------------------------------
  # Ask each candidate for its real path. The fake `python` that opens the
  # Microsoft Store prints nothing, so it's skipped.
  function Find-Python {
    $tries = @(@('py', '-3'), @('python'), @('python3'))
    $tries += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
      Sort-Object FullName -Descending | ForEach-Object { ,@($_.FullName) }
    foreach ($t in $tries) {
      $exe = $t[0]; $rest = @($t | Select-Object -Skip 1)
      if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
      try {
        $out = & $exe @rest -c "import sys; print(sys.executable) if sys.version_info >= (3, 8) else sys.exit(1)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return ([string]($out | Select-Object -Last 1)).Trim() }
      } catch {}
    }
    return $null
  }

  $Py = Find-Python
  if (-not $Py -and (Get-Command winget -ErrorAction SilentlyContinue)) {
    $ans = Read-Host "Python 3 is needed and isn't installed. Install it now? [Y/n]"
    if ($ans -notmatch '^(n|no)$') {
      winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
      $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' +
                  [Environment]::GetEnvironmentVariable('Path', 'Machine')
      $Py = Find-Python
    }
  }
  if (-not $Py) {
    Write-Host "Python 3 is needed but I couldn't find it."
    Write-Host "Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again."
    return
  }

  # --- download ------------------------------------------------------------
  Write-Host "Downloading lmsgrab..."
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  $Tmp = Join-Path ([IO.Path]::GetTempPath()) ("lmsgrab-" + [Guid]::NewGuid())
  New-Item -ItemType Directory -Path $Tmp | Out-Null
  try {
    $Zip = Join-Path $Tmp 'src.zip'
    Invoke-WebRequest -UseBasicParsing "https://codeload.github.com/$Repo/zip/refs/heads/$Branch" -OutFile $Zip
    Expand-Archive -Path $Zip -DestinationPath $Tmp -Force
    $Src = Get-ChildItem $Tmp -Directory | Select-Object -First 1

    # --- install the package ---------------------------------------------
    New-Item -ItemType Directory -Force -Path $AppDir, $BinDir | Out-Null
    Remove-Item (Join-Path $AppDir 'lmsgrab') -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item (Join-Path $Src.FullName 'lmsgrab') $AppDir -Recurse
  } finally {
    Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue
  }

  # --- make the `lms` and `lms-mcp` commands -------------------------------
  foreach ($cmd in @(@('lms', 'lmsgrab'), @('lms-mcp', 'lmsgrab.mcp_server'))) {
    $body = "@echo off`r`nset `"PYTHONPATH=$AppDir;%PYTHONPATH%`"`r`n`"$Py`" -m $($cmd[1]) %*`r`n"
    Set-Content -Path (Join-Path $BinDir "$($cmd[0]).cmd") -Value $body -Encoding ASCII -NoNewline
  }

  # --- make sure that folder is on PATH (now and in new windows) -----------
  $UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  if (-not (($UserPath -split ';') -contains $BinDir)) {
    $new = if ($UserPath) { "$UserPath;$BinDir" } else { $BinDir }
    [Environment]::SetEnvironmentVariable('Path', $new, 'User')
  }
  if (-not (($env:Path -split ';') -contains $BinDir)) { $env:Path = "$env:Path;$BinDir" }

  Write-Host ""
  Write-Host "Installed. The 'lms' command works in any new terminal."
  Write-Host ""

  # --- go straight into setup: pick agents, log in, open one --------------
  & (Join-Path $BinDir 'lms.cmd') start
}

Install-Lmsgrab
