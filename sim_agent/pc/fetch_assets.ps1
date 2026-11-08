$ErrorActionPreference = 'Stop'
$commit = '98a70c569c4c1b6da467a20012f766ee1f8dc521'
$dest = Join-Path $PSScriptRoot 'assets/menagerie'
$fresh = -not (Test-Path $dest)
if (-not (Test-Path $dest)) {
    git clone --filter=blob:none --sparse https://github.com/google-deepmind/mujoco_menagerie.git $dest
    if ($LASTEXITCODE) { throw 'Menagerie clone failed' }
}
if ((git -C $dest remote get-url origin) -ne 'https://github.com/google-deepmind/mujoco_menagerie.git') { throw 'Unexpected asset repository' }
if (-not $fresh -and (git -C $dest status --porcelain)) { throw 'Asset checkout has local changes; refusing overwrite' }
git -C $dest sparse-checkout set franka_emika_panda
if ($LASTEXITCODE) { throw 'Sparse checkout failed' }
git -C $dest fetch origin $commit
if ($LASTEXITCODE) { throw 'Pinned fetch failed' }
git -C $dest checkout --detach $commit
if ($LASTEXITCODE) { throw 'Pinned checkout failed' }
Write-Output "Menagerie $commit; see franka_emika_panda/LICENSE"
