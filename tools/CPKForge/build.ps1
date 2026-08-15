$ErrorActionPreference = 'Stop'
$legacy = $PSScriptRoot
if (-not (Test-Path (Join-Path $legacy 'CPK.cs'))) {
    $legacy = 'C:\Users\Owner\Documents\Codex\2026-07-29\jojo\work\tools\cripak-src\CriPakTools'
}
$sources = @(
    (Join-Path $PSScriptRoot 'Program.cs'),
    (Join-Path $legacy 'CPK.cs'),
    (Join-Path $legacy 'Endian.cs'),
    (Join-Path $legacy 'Tools.cs')
)
$out = Join-Path $PSScriptRoot 'CPKForge.exe'
if (Test-Path $out) { Remove-Item -LiteralPath $out }
$provider = New-Object Microsoft.CSharp.CSharpCodeProvider
$parameters = New-Object System.CodeDom.Compiler.CompilerParameters
$parameters.GenerateExecutable = $true
$parameters.GenerateInMemory = $false
$parameters.OutputAssembly = $out
$parameters.CompilerOptions = '/optimize+ /platform:x64 /target:winexe /main:CPKForge.Program'
$parameters.TreatWarningsAsErrors = $false
$parameters.ReferencedAssemblies.Add('System.dll') | Out-Null
$parameters.ReferencedAssemblies.Add('System.Core.dll') | Out-Null
$parameters.ReferencedAssemblies.Add('Microsoft.CSharp.dll') | Out-Null
$parameters.ReferencedAssemblies.Add('System.Drawing.dll') | Out-Null
$parameters.ReferencedAssemblies.Add('System.Windows.Forms.dll') | Out-Null
$parameters.EmbeddedResources.Add((Join-Path $PSScriptRoot 'data-profile.cpk')) | Out-Null
$result = $provider.CompileAssemblyFromFile($parameters, [string[]]$sources)
$hardErrors = @($result.Errors | Where-Object { -not $_.IsWarning })
if ($hardErrors.Count -gt 0) {
    $hardErrors | ForEach-Object { Write-Error $_.ToString() }
    exit 1
}
Write-Host "Built $out"
