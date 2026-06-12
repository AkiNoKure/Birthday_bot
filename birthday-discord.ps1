#requires -Version 5.1

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

###############################################################################
# Chemins du script
###############################################################################
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile     = Join-Path $ScriptDir '.env'
$LogFile     = Join-Path $ScriptDir 'birthday-bot.log'
$LastRunFile = Join-Path $ScriptDir 'last_run.txt'

###############################################################################
# Verification du .env
###############################################################################
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Fichier .env introuvable : $EnvFile"
}

###############################################################################
# Lecture du .env
###############################################################################
function Read-EnvFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    $config = @{}
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.StartsWith('#')) { continue }
        $parts = $line -split '=', 2
        if ($parts.Count -ne 2) { continue }
        $key   = $parts[0].Trim()
        $value = $parts[1].Trim()
        if (-not [string]::IsNullOrWhiteSpace($key)) {
            $config[$key] = $value
        }
    }
    return $config
}

$config = Read-EnvFile -Path $EnvFile

###############################################################################
# Variables obligatoires
###############################################################################
if (-not $config.ContainsKey('WEBHOOK_URL') -or [string]::IsNullOrWhiteSpace($config['WEBHOOK_URL'])) {
    throw "Variable WEBHOOK_URL manquante dans .env"
}
if (-not $config.ContainsKey('DATA_FILE') -or [string]::IsNullOrWhiteSpace($config['DATA_FILE'])) {
    throw "Variable DATA_FILE manquante dans .env"
}

$WebhookUrl = $config['WEBHOOK_URL']
$DataFile   = $config['DATA_FILE']
$TimeZoneId = if ($config.ContainsKey('TIMEZONE') -and -not [string]::IsNullOrWhiteSpace($config['TIMEZONE'])) {
    $config['TIMEZONE']
} else {
    'Romance Standard Time'
}

if (-not (Test-Path -LiteralPath $DataFile)) {
    throw "Fichier CSV introuvable : $DataFile"
}

###############################################################################
# Fonctions utilitaires
###############################################################################

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $entry = "[$timestamp] $Message"
    Add-Content -LiteralPath $LogFile -Value $entry -Encoding UTF8
    Write-Host $entry
}

function Invoke-LogRotation {
    param([int]$MaxLines = 500)
    if (-not (Test-Path -LiteralPath $LogFile)) { return }
    $lines = Get-Content -LiteralPath $LogFile -Encoding UTF8
    if ($lines.Count -gt $MaxLines) {
        $lines | Select-Object -Last $MaxLines | Set-Content -LiteralPath $LogFile -Encoding UTF8
    }
}

function Normalize-Text {
    param([AllowNull()][string]$Text)
    if ($null -eq $Text) { return '' }
    $value = $Text.Trim().ToLowerInvariant()
    $replacements = @{
        'e' = 'e'
        'a' = 'a'
        'i' = 'i'
        'o' = 'o'
        'u' = 'u'
        'c' = 'c'
    }
    # Remplacement des caracteres accentues
    $accents = @{
        ([char]0xE9) = 'e'; ([char]0xE8) = 'e'; ([char]0xEA) = 'e'; ([char]0xEB) = 'e'
        ([char]0xE0) = 'a'; ([char]0xE2) = 'a'; ([char]0xE4) = 'a'
        ([char]0xEE) = 'i'; ([char]0xEF) = 'i'
        ([char]0xF4) = 'o'; ([char]0xF6) = 'o'
        ([char]0xF9) = 'u'; ([char]0xFB) = 'u'; ([char]0xFC) = 'u'
        ([char]0xE7) = 'c'
        ([char]0x153) = 'oe'
        ([char]0x2019) = "'"
    }
    foreach ($key in $accents.Keys) {
        $value = $value.Replace([string]$key, $accents[$key])
    }
    return $value
}

function Get-MonthNumber {
    param([Parameter(Mandatory = $true)][string]$MonthName)
    switch (Normalize-Text $MonthName) {
        'janvier'   { return 1 }
        'fevrier'   { return 2 }
        'mars'      { return 3 }
        'avril'     { return 4 }
        'mai'       { return 5 }
        'juin'      { return 6 }
        'juillet'   { return 7 }
        'aout'      { return 8 }
        'septembre' { return 9 }
        'octobre'   { return 10 }
        'novembre'  { return 11 }
        'decembre'  { return 12 }
        default     { return $null }
    }
}

function Get-MonthName {
    param([int]$MonthNumber)
    $names = @('', 'janvier', 'f' + [char]0xE9 + 'vrier', 'mars', 'avril', 'mai', 'juin',
               'juillet', 'ao' + [char]0xFB + 't', 'septembre', 'octobre', 'novembre', 'd' + [char]0xE9 + 'cembre')
    return $names[$MonthNumber]
}

function Get-DayName {
    param([System.DayOfWeek]$DayOfWeek)
    switch ($DayOfWeek) {
        'Monday'    { return 'lundi' }
        'Tuesday'   { return 'mardi' }
        'Wednesday' { return 'mercredi' }
        'Thursday'  { return 'jeudi' }
        'Friday'    { return 'vendredi' }
        'Saturday'  { return 'samedi' }
        'Sunday'    { return 'dimanche' }
    }
}

function Get-DisplayName {
    param([Parameter(Mandatory = $true)][pscustomobject]$Person)
    $pseudo = "$($Person.pseudo)".Trim()
    $nom    = "$($Person.nom)".Trim()
    $prenom = "$($Person.prenom)".Trim()
    $displayName = ''
    if (-not [string]::IsNullOrWhiteSpace($pseudo) -and $pseudo -ne 'x') {
        $displayName = $pseudo
    }
    if (-not [string]::IsNullOrWhiteSpace($prenom) -and $prenom -ne 'x') {
        if (-not [string]::IsNullOrWhiteSpace($displayName)) {
            $displayName += " ($prenom"
            if (-not [string]::IsNullOrWhiteSpace($nom) -and $nom -ne 'x') {
                $displayName += " $nom"
            }
            $displayName += ")"
        } else {
            $displayName = $prenom
            if (-not [string]::IsNullOrWhiteSpace($nom) -and $nom -ne 'x') {
                $displayName += " $nom"
            }
        }
    } elseif (-not [string]::IsNullOrWhiteSpace($nom) -and $nom -ne 'x' -and [string]::IsNullOrWhiteSpace($displayName)) {
        $displayName = $nom
    }
    if ([string]::IsNullOrWhiteSpace($displayName)) { $displayName = 'Personne inconnue' }
    return $displayName
}

function Get-GroupLabel {
    param([string]$Groupe)
    switch ($Groupe.Trim().ToLowerInvariant()) {
        'famille' { return ':family: Famille' }
        'amis'    { return ':busts_in_silhouette: Amis' }
        'special' { return ':sparkles: Sp' + [char]0xE9 + 'cial' }
        default   { return ":pushpin: $Groupe" }
    }
}

function Get-AgeAtDate {
    param(
        [int]$BirthYear,
        [int]$BirthMonth,
        [int]$BirthDay,
        [datetime]$AtDate
    )
    $age = $AtDate.Year - $BirthYear
    if ($AtDate.Month -lt $BirthMonth -or ($AtDate.Month -eq $BirthMonth -and $AtDate.Day -lt $BirthDay)) {
        $age--
    }
    return $age
}

function Send-DiscordEmbed {
    param(
        [string]$Content = '',
        [Parameter(Mandatory = $true)]
        [hashtable]$Embed
    )
    $maxRetries = 3
    $retryDelay = 10
    $payload = [ordered]@{}
    if (-not [string]::IsNullOrWhiteSpace($Content)) {
        $payload['content'] = $Content
    }
    $payload['embeds'] = @($Embed)
    $json  = $payload | ConvertTo-Json -Depth 10 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    for ($attempt = 1; $attempt -le $maxRetries; $attempt++) {
        try {
            Invoke-RestMethod `
                -Uri $WebhookUrl `
                -Method Post `
                -ContentType 'application/json; charset=utf-8' `
                -Body $bytes | Out-Null
            return
        } catch {
            if ($attempt -lt $maxRetries) {
                Write-Log "AVERTISSEMENT : Tentative $attempt/$maxRetries echouee. Nouvel essai dans ${retryDelay}s..."
                Start-Sleep -Seconds $retryDelay
            } else {
                throw "ERREUR : Echec apres $maxRetries tentatives : $_"
            }
        }
    }
}

###############################################################################
# Date du jour
###############################################################################
try {
    $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById($TimeZoneId)
} catch {
    throw "Fuseau horaire Windows invalide : $TimeZoneId"
}

$today      = [System.TimeZoneInfo]::ConvertTime((Get-Date), $tz)
$todayDay   = $today.Day
$todayMonth = $today.Month
$todayStr   = $today.ToString('yyyy-MM-dd')

###############################################################################
# Rotation des logs
###############################################################################
Invoke-LogRotation

###############################################################################
# Demarrage du log
###############################################################################
Write-Log "--- Execution du birthday bot ---"

###############################################################################
# Protection anti-doublon
###############################################################################
if (Test-Path -LiteralPath $LastRunFile) {
    $lastRun = (Get-Content -LiteralPath $LastRunFile -Encoding UTF8).Trim()
    if ($lastRun -eq $todayStr) {
        Write-Log "Deja execute aujourd'hui ($todayStr). Arret du script."
        exit 0
    }
}

###############################################################################
# Lecture du CSV
###############################################################################
$rows           = Import-Csv -LiteralPath $DataFile -Delimiter ';'
$birthdaysToday = New-Object System.Collections.Generic.List[pscustomobject]
$birthdaysSoon  = New-Object System.Collections.Generic.List[pscustomobject]
$warningCount   = 0

foreach ($row in $rows) {
    if ([string]::IsNullOrWhiteSpace($row.groupe)) { continue }

    $displayName = Get-DisplayName -Person $row
    $dayRaw      = "$($row.jour)".Trim()
    $monthRaw    = "$($row.mois)".Trim()
    $yearRaw     = "$($row.annee)".Trim()

    if ([string]::IsNullOrWhiteSpace($dayRaw) -or $dayRaw -eq 'x') { continue }

    $dayValue = 0
    if (-not [int]::TryParse($dayRaw, [ref]$dayValue)) {
        Write-Log "AVERTISSEMENT CSV : Jour invalide '$dayRaw' pour '$displayName' - ligne ignoree."
        $warningCount++
        continue
    }

    $monthValue = Get-MonthNumber -MonthName $monthRaw
    if ($null -eq $monthValue) {
        Write-Log "AVERTISSEMENT CSV : Mois non reconnu '$monthRaw' pour '$displayName' - ligne ignoree."
        $warningCount++
        continue
    }

    $yearValue = $null
    $yearInt   = 0
    if (-not [string]::IsNullOrWhiteSpace($yearRaw) -and $yearRaw -ne 'x') {
        if ([int]::TryParse($yearRaw, [ref]$yearInt) -and $yearInt -gt 1900) {
            $yearValue = $yearInt
        } else {
            Write-Log "AVERTISSEMENT CSV : Annee invalide '$yearRaw' pour '$displayName' - annee ignoree."
            $warningCount++
        }
    }

    $description = "$($row.description)".Trim()
    $groupeRaw   = "$($row.groupe)".Trim()

    if ($dayValue -eq $todayDay -and $monthValue -eq $todayMonth) {
        $age = $null
        if ($null -ne $yearValue) {
            $age = Get-AgeAtDate -BirthYear $yearValue -BirthMonth $monthValue -BirthDay $dayValue -AtDate $today
        }
        $birthdaysToday.Add([pscustomobject]@{
            Name        = $displayName
            Group       = $groupeRaw
            Age         = $age
            Description = $description
        })
    }

    for ($offset = 1; $offset -le 7; $offset++) {
        $futureDate = $today.AddDays($offset)
        if ($dayValue -eq $futureDate.Day -and $monthValue -eq $futureDate.Month) {
            $age = $null
            if ($null -ne $yearValue) {
                $age = Get-AgeAtDate -BirthYear $yearValue -BirthMonth $monthValue -BirthDay $dayValue -AtDate $futureDate
            }
            $birthdaysSoon.Add([pscustomobject]@{
                Name        = $displayName
                Group       = $groupeRaw
                Age         = $age
                Date        = $futureDate
                Offset      = $offset
                Description = $description
            })
            break
        }
    }
}

if ($warningCount -gt 0) {
    Write-Log "CSV : $warningCount ligne(s) avec des donnees incorrectes."
}

###############################################################################
# Embed : anniversaires du jour
###############################################################################
$NL = [char]10

if ($birthdaysToday.Count -gt 0) {
    $fields = @()
    foreach ($b in $birthdaysToday) {
        $fieldName = "$(Get-GroupLabel $b.Group)  -  $($b.Name)"

        if ($b.Group.ToLowerInvariant() -eq 'special') {
            if (-not [string]::IsNullOrWhiteSpace($b.Description) -and $b.Description -ne 'x') {
                $fieldValue = ":tada: Bon anniversaire de **$($b.Description)** !"
            } else {
                $fieldValue = ":tada: Bon anniversaire !"
            }
            if ($null -ne $b.Age) { $fieldValue += " ($($b.Age) ans)" }
        } else {
            if ($null -ne $b.Age) {
                $fieldValue = "F" + [char]0xEA + "te ses **$($b.Age) ans** aujourd'hui ! :birthday:"
            } else {
                $fieldValue = "Bon anniversaire ! :birthday:"
            }
            if (-not [string]::IsNullOrWhiteSpace($b.Description) -and $b.Description -ne 'x') {
                $fieldValue += "$NL*$($b.Description)*"
            }
        }

        $fields += @{ name = $fieldName; value = $fieldValue; inline = $false }
    }

    $embed = @{
        title       = ":tada: Joyeux anniversaire !"
        description = "Aujourd'hui nous f" + [char]0xEA + "tons :"
        color       = 16766720
        fields      = $fields
        footer      = @{ text = "Birthday Bot" }
        timestamp   = $today.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    }

    Send-DiscordEmbed -Content '@everyone' -Embed $embed
    Write-Log "Embed anniversaire envoye pour $($birthdaysToday.Count) personne(s) : $(($birthdaysToday | ForEach-Object { $_.Name }) -join ', ')"
} else {
    $embed = @{
        title       = ":white_check_mark: Aucun anniversaire aujourd'hui"
        description = "Joyeux non-anniversaire a tous !"
        color       = 5763719
        footer      = @{ text = "Birthday Bot" }
        timestamp   = $today.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    }
    Send-DiscordEmbed -Embed $embed
    Write-Log "Aucun anniversaire aujourd'hui."
}

###############################################################################
# Embed : anniversaires a venir dans les 7 jours (sans ping)
###############################################################################
if ($birthdaysSoon.Count -gt 0) {
    $sorted = @($birthdaysSoon | Sort-Object Offset)
    $fields = @()

    foreach ($item in $sorted) {
        $dayName   = Get-DayName   -DayOfWeek   $item.Date.DayOfWeek
        $monthName = Get-MonthName -MonthNumber  $item.Date.Month

        if ($item.Offset -eq 1) {
            $quand = "Demain - $dayName $($item.Date.Day) $monthName"
        } else {
            $quand = "Dans $($item.Offset) jours - $dayName $($item.Date.Day) $monthName"
        }

        $fieldName = "$(Get-GroupLabel $item.Group)  -  $($item.Name)"

        if ($item.Group.ToLowerInvariant() -eq 'special') {
            if (-not [string]::IsNullOrWhiteSpace($item.Description) -and $item.Description -ne 'x') {
                $fieldValue = "$quand${NL}Anniversaire de **$($item.Description)**"
            } else {
                $fieldValue = "$quand${NL}Anniversaire"
            }
            if ($null -ne $item.Age) { $fieldValue += " ($($item.Age) ans)" }
        } else {
            $fieldValue = $quand
            if ($null -ne $item.Age) {
                $fieldValue += "${NL}F" + [char]0xEA + "tera ses **$($item.Age) ans** :birthday:"
            }
        }

        $fields += @{ name = $fieldName; value = $fieldValue; inline = $false }
    }

    $embed = @{
        title       = ":calendar_spiral: Anniversaires a venir - $($sorted.Count) dans les 7 prochains jours"
        color       = 5793266
        fields      = $fields
        footer      = @{ text = "Birthday Bot" }
        timestamp   = $today.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    }

    Send-DiscordEmbed -Embed $embed
    Write-Log "Recapitulatif envoye : $($sorted.Count) anniversaire(s) a venir."
} else {
    Write-Log "Aucun anniversaire dans les 7 prochains jours."
}

###############################################################################
# Mise a jour de la date de derniere execution
###############################################################################
$todayStr | Set-Content -LiteralPath $LastRunFile -Encoding UTF8

Write-Log "--- Fin d'execution ---"
