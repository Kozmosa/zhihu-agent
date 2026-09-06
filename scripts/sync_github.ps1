<#
.SYNOPSIS
Inspect or publish this project to its existing GitHub default branch.
.DESCRIPTION
Without -Publish, only remote-tracking refs are fetched; files and commits stay
unchanged. With -Publish, merge remote history, push normally, and verify SHA.
Authentication must already be available to Git. No credentials are stored here.
.EXAMPLE
powershell -NoProfile -File "E:\CzCode\ZhiJing Agent\scripts\sync_github.ps1"
.EXAMPLE
powershell -NoProfile -File "E:\CzCode\ZhiJing Agent\scripts\sync_github.ps1" -Publish
#>
[CmdletBinding()]
param([switch]$Publish)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$expectedUrl = 'https://github.com/Kozmosa/zhihu-agent'

function Invoke-RepoGit {
    param([string[]]$Arguments, [int[]]$AllowedExitCodes = @(0))
    $previousPreference = $ErrorActionPreference
    try {
        # Windows PowerShell can represent native stderr as ErrorRecord objects.
        $ErrorActionPreference = 'Continue'
        $lines = @(& git -c "safe.directory=$repoPath" -C $repoPath @Arguments 2>&1 |
            ForEach-Object { "$_" })
        $exitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousPreference }
    if ($exitCode -notin $AllowedExitCodes) {
        throw "git $($Arguments -join ' ') failed ($exitCode).`n$($lines -join "`n")"
    }
    return @{ Lines = $lines; ExitCode = $exitCode }
}

function Assert-CleanWorktree {
    $status = Invoke-RepoGit -Arguments @('status', '--porcelain=v1', '--untracked-files=all')
    if ($status.Lines.Count -gt 0) {
        throw "Working tree is not clean. Commit or review these files first:`n$($status.Lines -join "`n")"
    }
}

function Assert-ExpectedOrigin {
    foreach ($direction in @('fetch', 'push')) {
        $arguments = @('remote', 'get-url', '--all')
        if ($direction -eq 'push') { $arguments += '--push' }
        $arguments += 'origin'
        $urls = (Invoke-RepoGit -Arguments $arguments).Lines
        if ($urls.Count -ne 1 -or
            ($urls[0].TrimEnd('/') -replace '\.git$', '') -ne $expectedUrl) {
            throw "origin $direction URL must be exactly $expectedUrl (optional .git suffix)."
        }
    }
}

try {
    $null = Get-Command git -ErrorAction Stop
    $topLevel = (Invoke-RepoGit -Arguments @('rev-parse', '--show-toplevel')).Lines[0]
    if ([IO.Path]::GetFullPath($topLevel) -ne [IO.Path]::GetFullPath($repoPath)) {
        throw 'The script directory must belong to the project repository root.'
    }
    Assert-ExpectedOrigin
    Assert-CleanWorktree
    $branchResult = Invoke-RepoGit -Arguments @('symbolic-ref', '--quiet', '--short', 'HEAD') -AllowedExitCodes @(0, 1)
    if ($branchResult.ExitCode -ne 0) { throw 'Detached HEAD: switch to a local branch first.' }
    $localBranch = $branchResult.Lines[0]
    $null = Invoke-RepoGit -Arguments @('rev-parse', '--verify', 'HEAD')

    $remote = Invoke-RepoGit -Arguments @('ls-remote', '--symref', 'origin')
    $refs = @($remote.Lines | Where-Object { $_ -match '^[0-9a-f]+\s+\S+$' })
    $defaultRefs = @($remote.Lines | Where-Object { $_ -match '^ref:\s+refs/heads/.+\s+HEAD$' })
    $emptyRemote = $refs.Count -eq 0 -and $defaultRefs.Count -eq 0
    if ($emptyRemote) { $targetBranch = 'main' }
    elseif ($defaultRefs.Count -eq 1) {
        $targetBranch = $defaultRefs[0] -replace '^ref:\s+refs/heads/', '' -replace '\s+HEAD$', ''
    }
    else { throw 'Nonempty remote has no unambiguous default branch; no branch will be guessed.' }
    $null = Invoke-RepoGit -Arguments @('check-ref-format', "refs/heads/$targetBranch")
    $remoteRef = "refs/remotes/origin/$targetBranch"
    $unrelated = $false
    if (-not $emptyRemote) {
        $null = Invoke-RepoGit -Arguments @('fetch', '--no-tags', 'origin', "refs/heads/${targetBranch}:$remoteRef")
        $base = Invoke-RepoGit -Arguments @('merge-base', 'HEAD', $remoteRef) -AllowedExitCodes @(0, 1)
        $unrelated = $base.ExitCode -eq 1
    }

    Write-Host "Repository: $repoPath"
    Write-Host "Source branch: $localBranch; remote target: $targetBranch"
    if ($emptyRemote) { Write-Host 'Remote is empty; publish current history as main.' }
    elseif ($unrelated) { Write-Host 'Histories have no common ancestor; merge will explicitly allow unrelated histories.' }
    else { Write-Host "Merge $remoteRef into $localBranch, preserving both histories." }
    Write-Host "Then push HEAD:refs/heads/$targetBranch without force and verify remote SHA."
    if (-not $Publish) {
        Write-Host 'Plan only. Run again with -Publish to execute the merge and push.'
        exit 0
    }

    Assert-CleanWorktree
    if (-not $emptyRemote) {
        $mergeArguments = @('merge', '--no-edit')
        if ($unrelated) { $mergeArguments += '--allow-unrelated-histories' }
        $mergeArguments += $remoteRef
        try { $merge = Invoke-RepoGit -Arguments $mergeArguments }
        catch { throw "Merge failed. No push attempted; inspect Git status and resolve any conflicts.`n$_" }
        $merge.Lines | ForEach-Object { Write-Host $_ }
    }
    Assert-CleanWorktree
    Assert-ExpectedOrigin
    $localSha = (Invoke-RepoGit -Arguments @('rev-parse', 'HEAD')).Lines[0]
    $push = Invoke-RepoGit -Arguments @('push', 'origin', "HEAD:refs/heads/$targetBranch")
    $push.Lines | ForEach-Object { Write-Host $_ }
    $verified = (Invoke-RepoGit -Arguments @('ls-remote', '--heads', 'origin', "refs/heads/$targetBranch")).Lines
    if ($verified.Count -ne 1 -or ($verified[0] -split '\s+')[0] -ne $localSha) {
        throw 'Push returned successfully, but remote SHA verification failed; inspect the remote before retrying.'
    }
    Write-Host "Verified: $expectedUrl/tree/$targetBranch at $localSha"
}
catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
