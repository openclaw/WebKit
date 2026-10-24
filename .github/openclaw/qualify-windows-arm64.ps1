param(
  [Parameter(Mandatory)][string]$ArtifactDirectory,
  [Parameter(Mandatory)][string]$OutputDirectory,
  [Parameter(Mandatory)][string]$Source
)
$ErrorActionPreference = 'Stop'
if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'Arm64') {
  throw 'Qualification requires native Windows ARM64.'
}
$label = 'bun-webkit-windows-arm64'
$archive = Join-Path $ArtifactDirectory "$label.tar.gz"
$manifest = Get-Content -Raw (Join-Path $ArtifactDirectory "$label.manifest.json") | ConvertFrom-Json
$digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
if ($manifest.source -cne $Source -or $manifest.lane.label -cne $label -or
    $manifest.files."$label.tar.gz".sha256 -cne $digest -or
    $manifest.files."$label.tar.gz".size -ne (Get-Item -LiteralPath $archive).Length) {
  throw 'Windows ARM64 artifact provenance mismatch.'
}
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
& tar -xzf $archive -C $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'Archive extraction failed.' }
$jsc = Join-Path $OutputDirectory 'bun-webkit/bin/jsc.exe'
$ffi = Join-Path $OutputDirectory 'bun-webkit/bin/testFFI.exe'
foreach ($exe in @($jsc, $ffi)) {
  $bytes = [IO.File]::ReadAllBytes($exe)
  $pe = [BitConverter]::ToInt32($bytes, 0x3c)
  if ([BitConverter]::ToUInt16($bytes, $pe + 4) -ne 0xaa64) { throw "$exe is not an ARM64 PE." }
}
$probe = @'
function f(n) { let s = 0; for (let i = 0; i < n; ++i) s = (s + i * 7) % 1000003; return s; }
for (let i = 0; i < 1000; ++i) { if (f(100000) !== 545003) throw new Error("JIT result"); }
if (!(numberOfDFGCompiles(f) > 0 && numberOfDFGCompiles(f) < 1000000)) throw new Error("DFG unavailable");
print("windows-arm64-jsc-ok");
'@
$result = & $jsc -e $probe
if ($LASTEXITCODE -ne 0 -or $result -cne 'windows-arm64-jsc-ok') { throw 'Native JSC startup/JIT probe failed.' }
& $ffi
if ($LASTEXITCODE -ne 0) { throw 'Native testFFI failed.' }
$fixture = Join-Path $PSScriptRoot '../../JSTests/stress/array-buffer-accounting.js'
$modes = @(
  @{ Name = 'interpreter'; Flags = @('--useJIT=false') },
  @{ Name = 'baseline'; Flags = @('--useDFGJIT=false', '--useFTLJIT=false') },
  @{ Name = 'dfg'; Flags = @('--useFTLJIT=false', '--useConcurrentJIT=false') },
  @{ Name = 'ftl'; Flags = @('--useConcurrentJIT=false', '--thresholdForJITAfterWarmUp=10', '--thresholdForOptimizeAfterWarmUp=20', '--thresholdForFTLOptimizeAfterWarmUp=20') },
  @{ Name = 'concurrent'; Flags = @('--gcAtEnd=true', '--useConcurrentGC=true') }
)
foreach ($mode in $modes) {
  $flags = @('--useGenerationalGC=true', '--forceMiniVMMode=false') + $mode.Flags
  & $jsc @flags $fixture *> (Join-Path $OutputDirectory "accounting-$($mode.Name).log")
  if ($LASTEXITCODE -ne 0) { throw "Native ARM64 ArrayBuffer accounting failed in $($mode.Name) mode." }
}
@{ passed = $true; source = $Source; lane = $label; sha256 = $digest; architecture = 'arm64'; startup = $true; dfg = $true; ffi = $true; arraybuffer_accounting = $true; arraybuffer_modes = $modes.Count } |
  ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $OutputDirectory 'gate.json')
