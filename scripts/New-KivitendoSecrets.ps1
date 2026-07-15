[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()]
    [string]$OutputPath = "",

    [Parameter()]
    [ValidateRange(20, 256)]
    [int]$AdminPasswordLength = 32,

    [Parameter()]
    [ValidateRange(24, 256)]
    [int]$DatabasePasswordLength = 40,

    [Parameter()]
    [ValidateRange(32, 512)]
    [int]$MasterKeyLength = 64,

    [Parameter()]
    [switch]$IncludeBasicAuth,

    [Parameter()]
    [string]$BasicAuthUser = "kivitendo",

    [Parameter()]
    [ValidateRange(16, 256)]
    [int]$BasicAuthPasswordLength = 32,

    [Parameter()]
    [switch]$EncryptWithAnsibleVault,

    [Parameter()]
    [string]$VaultPasswordFile = "",

    [Parameter()]
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-CryptographicRandomString {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 4096)]
        [int]$Length,

        [Parameter()]
        [ValidateNotNullOrEmpty()]
        [string]$Alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    )

    $characters = $Alphabet.ToCharArray()
    if ($characters.Length -lt 2 -or $characters.Length -gt 256) {
        throw "Alphabet must contain between 2 and 256 characters."
    }

    # Rejection sampling avoids modulo bias when mapping random bytes to the alphabet.
    $acceptBelow = [Math]::Floor(256 / $characters.Length) * $characters.Length
    $buffer = New-Object byte[] 128
    $builder = [System.Text.StringBuilder]::new($Length)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()

    try {
        while ($builder.Length -lt $Length) {
            $rng.GetBytes($buffer)
            foreach ($value in $buffer) {
                if ($value -ge $acceptBelow) {
                    continue
                }

                [void]$builder.Append($characters[$value % $characters.Length])
                if ($builder.Length -eq $Length) {
                    break
                }
            }
        }
    }
    finally {
        $rng.Dispose()
        [Array]::Clear($buffer, 0, $buffer.Length)
    }

    return $builder.ToString()
}

function ConvertTo-YamlSingleQuotedScalar {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Value
    )

    return "'" + $Value.Replace("'", "''") + "'"
}

function Protect-SecretFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $isWindowsPlatform = $env:OS -eq "Windows_NT"
    if ($isWindowsPlatform) {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
        $userSid = $identity.User
        if ($null -eq $userSid) {
            throw "Unable to determine the current Windows user SID."
        }

        $acl = [System.Security.AccessControl.FileSecurity]::new()
        $acl.SetOwner($userSid)
        $acl.SetAccessRuleProtection($true, $false)
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $userSid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        [void]$acl.AddAccessRule($rule)
        Set-Acl -LiteralPath $Path -AclObject $acl
        return
    }

    $chmod = Get-Command chmod -ErrorAction SilentlyContinue
    if ($null -eq $chmod) {
        throw "Cannot harden secret-file permissions because chmod is unavailable."
    }

    & $chmod.Source 600 -- $Path
    if ($LASTEXITCODE -ne 0) {
        throw "chmod 600 failed for '$Path'."
    }
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $repositoryRoot = Split-Path -Parent $PSScriptRoot
    $OutputPath = Join-Path $repositoryRoot "secrets.yml"
}

if ($IncludeBasicAuth -and [string]::IsNullOrWhiteSpace($BasicAuthUser)) {
    throw "BasicAuthUser must not be empty when IncludeBasicAuth is enabled."
}

$fullOutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path -Parent $fullOutputPath
if ([string]::IsNullOrWhiteSpace($outputDirectory)) {
    throw "Unable to determine output directory for '$fullOutputPath'."
}

if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
}

if ((Test-Path -LiteralPath $fullOutputPath) -and -not $Force) {
    throw "Output file '$fullOutputPath' already exists. Use -Force to replace it intentionally."
}

$adminPassword = New-CryptographicRandomString -Length $AdminPasswordLength
$databasePassword = New-CryptographicRandomString -Length $DatabasePasswordLength
$masterKey = New-CryptographicRandomString -Length $MasterKeyLength

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("---")
$lines.Add("# Generated with scripts/New-KivitendoSecrets.ps1 using a cryptographic RNG.")
$lines.Add("# Encrypt this file with Ansible Vault before long-term storage.")
$lines.Add("")
$lines.Add("kivitendo_admin_password: $(ConvertTo-YamlSingleQuotedScalar -Value $adminPassword)")
$lines.Add("kivitendo_db_password: $(ConvertTo-YamlSingleQuotedScalar -Value $databasePassword)")
$lines.Add("kivitendo_master_key: $(ConvertTo-YamlSingleQuotedScalar -Value $masterKey)")

if ($IncludeBasicAuth) {
    $basicAuthPassword = New-CryptographicRandomString -Length $BasicAuthPasswordLength
    $lines.Add("")
    $lines.Add("basic_auth:")
    $lines.Add("  user: $(ConvertTo-YamlSingleQuotedScalar -Value $BasicAuthUser)")
    $lines.Add("  password: $(ConvertTo-YamlSingleQuotedScalar -Value $basicAuthPassword)")
}

$content = ($lines -join [Environment]::NewLine) + [Environment]::NewLine
$tempPath = Join-Path $outputDirectory (".{0}.{1}.tmp" -f ([System.IO.Path]::GetFileName($fullOutputPath)), [Guid]::NewGuid().ToString("N"))

try {
    if ($PSCmdlet.ShouldProcess($fullOutputPath, "Generate cryptographically random kivitendo secrets")) {
        [System.IO.File]::WriteAllText(
            $tempPath,
            $content,
            [System.Text.UTF8Encoding]::new($false)
        )
        Protect-SecretFile -Path $tempPath

        if (Test-Path -LiteralPath $fullOutputPath) {
            Remove-Item -LiteralPath $fullOutputPath -Force
        }

        Move-Item -LiteralPath $tempPath -Destination $fullOutputPath
        Protect-SecretFile -Path $fullOutputPath

        if ($EncryptWithAnsibleVault) {
            $ansibleVault = Get-Command ansible-vault -ErrorAction SilentlyContinue
            if ($null -eq $ansibleVault) {
                throw "EncryptWithAnsibleVault was requested, but ansible-vault is not available in PATH."
            }

            $vaultArguments = [System.Collections.Generic.List[string]]::new()
            $vaultArguments.Add("encrypt")
            if (-not [string]::IsNullOrWhiteSpace($VaultPasswordFile)) {
                $resolvedVaultPasswordFile = [System.IO.Path]::GetFullPath($VaultPasswordFile)
                if (-not (Test-Path -LiteralPath $resolvedVaultPasswordFile -PathType Leaf)) {
                    throw "Vault password file '$resolvedVaultPasswordFile' does not exist."
                }
                $vaultArguments.Add("--vault-password-file")
                $vaultArguments.Add($resolvedVaultPasswordFile)
            }
            $vaultArguments.Add($fullOutputPath)

            & $ansibleVault.Source @vaultArguments
            if ($LASTEXITCODE -ne 0) {
                throw "ansible-vault encryption failed for '$fullOutputPath'."
            }
            Protect-SecretFile -Path $fullOutputPath
        }
    }
}
finally {
    if (Test-Path -LiteralPath $tempPath) {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }

    # Best-effort cleanup of secret-bearing variables after the file has been written.
    $adminPassword = $null
    $databasePassword = $null
    $masterKey = $null
    if (Get-Variable -Name basicAuthPassword -ErrorAction SilentlyContinue) {
        $basicAuthPassword = $null
    }
    $content = $null
    $lines.Clear()
}

Write-Host "Secrets written to: $fullOutputPath"
if (-not $EncryptWithAnsibleVault) {
    Write-Host "Next step: encrypt the file with 'ansible-vault encrypt secrets.yml' before long-term storage."
}
