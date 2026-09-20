# The one command, on Windows. Read it before you run it -- that is why it is
# a file in the repo and not something piped into your shell from the internet.
#
#   .\dojo.cmd          get set up, then fight a round for nothing
#   .\dojo.cmd train    fight past rounds again (no seed, no QU, no signer)
#   .\dojo.cmd rite     create a seed and an identity, for when you want a real seat
#   .\dojo.cmd fight    fight for real (needs a funded identity)
#   .\dojo.cmd dash     your cockpit, on your own machine
#
# It writes nothing outside this folder and %USERPROFILE%\.qdojo.
#
# This is the same script as ./dojo, step for step, in PowerShell. dojo.cmd
# is a shim that starts it with the execution policy bypassed for this one
# process, so nothing about your machine is changed; from a PowerShell prompt
# `.\dojo.ps1` works directly when your policy allows scripts.

Set-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not (Test-Path -LiteralPath 'packages\qdojo\pyproject.toml')) {
    [Console]::Error.WriteLine('run dojo.cmd from inside the qdojo checkout'); exit 1
}

function Say($text) { Write-Host "  $text" }
function Die($text) { [Console]::Error.WriteLine(''); [Console]::Error.WriteLine($text); exit 1 }

# A leading flag is not a subcommand: `.\dojo.cmd --rounds 5` must still start.
$Cmd = 'start'
$Rest = @($args)
if ($args.Count -gt 0 -and -not "$($args[0])".StartsWith('-')) {
    $Cmd = "$($args[0])"
    $Rest = @($args | Select-Object -Skip 1)
}
if ($Cmd -eq 'help' -or ($Rest.Count -eq 1 -and "$($Rest[0])" -in @('-h', '--help'))) {
    Get-Content -LiteralPath $MyInvocation.MyCommand.Path | Select-Object -First 10 |
        ForEach-Object { $_ -replace '^# ?', '' }
    exit 0
}

# ---------------------------------------------------------------- uv
$Uv = (Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Path
foreach ($cand in @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")) {
    if (-not $Uv -and (Test-Path -LiteralPath $cand)) { $Uv = $cand }
}
if (-not $Uv) {
    # We do not install it for you, and we do not pipe a URL into a shell on
    # your behalf. Three ways, pick one, open a new terminal, run dojo.cmd again.
    Die @'
qdojo needs uv (it manages the Python it runs on). Install it with one of:

    winget install --id=astral-sh.uv -e
    pipx install uv
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

then open a new terminal and run .\dojo.cmd again.
'@
}

Write-Host ''
Write-Host '  qdojo -- getting ready'
Say ('uv ' + (("$(& $Uv --version 2>&1)" -split ' ')[1]))
$syncOut = & $Uv sync --quiet 2>&1
if ($LASTEXITCODE -ne 0) {
    if (Test-Path -LiteralPath '.venv\Scripts\qdojo.exe') {
        Say 'could not sync (offline?) -- using the environment already here'
    } else {
        $syncOut | ForEach-Object { [Console]::Error.WriteLine("  $_") }
        Die 'uv sync failed. Fix the error above, then run .\dojo.cmd again.'
    }
}
Say 'ready'

function Run { & $Uv run qdojo @args; exit $LASTEXITCODE }

switch ($Cmd) {
    'train'   { Run train @Rest }
    'rite'    { Run bot init @Rest }
    'fight'   { Run bot run @Rest }
    'dash'    { Run bot dash @Rest }
    'prompts' { Run prompts @Rest }
    'start'   { }
    default   { Die "dojo.cmd: no such thing as '$Cmd'. Try: .\dojo.cmd --help" }
}

# ------------------------------------------------- the first-run experience
# Training needs no seed, no QU, no node and no signer, so it comes FIRST.
# A seed is a purse, and making a newcomer create one before they have seen
# a single riddle is how you lose them. The rite is where money starts, and
# even then nothing is built: qdojo signs in Python, and the only binary in
# this repo's story is the reference the crosscheck compares it against.
if (-not (Test-Path -LiteralPath "$env:USERPROFILE\.qdojo\bot\bot.json")) {
    Write-Host ''
    Write-Host '  nothing is set up yet, so we start with a fight that costs nothing.'
    Write-Host '  no seed, no account, no QU: your solver against rounds that really happened.'
    Write-Host ''
    # `python` here means whatever Python runs qdojo: bot run and train map a
    # leading python that is not on PATH to their own interpreter. Forward
    # slashes on purpose: Windows takes them, and so does a pwsh on Linux.
    & $Uv run qdojo train --solver python examples/solvers/bare.py @Rest
    Write-Host ''
    Write-Host '  that was examples\solvers\bare.py. open it -- it is thirty lines and every'
    Write-Host '  round it lost just told you the answer it should have given.'
    Write-Host ''
    Write-Host '  when you want a real seat:   .\dojo.cmd rite'
    Write-Host '  train again after an edit:   .\dojo.cmd train'
    Write-Host '  your own page and prompts:   .\dojo.cmd dash'
    Write-Host ''
    exit 0
}
Run train @Rest
