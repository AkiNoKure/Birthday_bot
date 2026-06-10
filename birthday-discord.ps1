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
# Vérification du .env
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

# --- Log ---
function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $entry = "[$timestamp] $Message"
    Add-Content -LiteralPath $LogFile -Value $entry -Encoding UTF8
    Write-Host $entry
}

# --- Rotation des logs (garde les 500 dernières lignes) ---
function Invoke-LogRotation {
    param([int]$MaxLines = 500)
    if (-not (Test-Path -LiteralPath $LogFile)) { return }
    $lines = Get-Content -LiteralPath $LogFile -Encoding UTF8
    if ($lines.Count -gt $MaxLines) {
        $lines | Select-Object -Last $MaxLines | Set-Content -LiteralPath $LogFile -Encoding UTF8
    }
}

# --- Normalisation du texte ---
function Normalize-Text {
    param(
        [AllowNull()]
        [string]$Text
    )
    if ($null -eq $Text) { return '' }
    $value = $Text.Trim().ToLowerInvariant()
    $replacements = @{
        'é' = 'e'; 'è' = 'e'; 'ê' = 'e'; 'ë' = 'e'
        'à' = 'a'; 'â' = 'a'; 'ä' = 'a'
        'î' = 'i'; 'ï' = 'i'
        'ô' = 'o'; 'ö' = 'o'
        'ù' = 'u'; 'û' = 'u'; 'ü' = 'u'
        'ç' = 'c'; 'œ' = 'oe'; "'" = "'"
    }
    foreach ($key in $replacements.Keys) {
        $value = $value.Replace($key, $replacements[$key])
    }
    return $value
}

# --- Conversion mois ---
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
    switch ($MonthNumber) {
        1  { return 'janvier' }    2  { return 'février' }   3  { return 'mars' }
        4  { return 'avril' }      5  { return 'mai' }        6  { return 'juin' }
        7  { return 'juillet' }    8  { return 'août' }       9  { return 'septembre' }
        10 { return 'octobre' }    11 { return 'novembre' }   12 { return 'décembre' }
    }
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

# --- Nom affiché ---
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
        }
        else {
            $displayName = $prenom
            if (-not [string]::IsNullOrWhiteSpace($nom) -and $nom -ne 'x') {
                $displayName += " $nom"
            }
        }
    }
    elseif (-not [string]::IsNullOrWhiteSpace($nom) -and $nom -ne 'x' -and [string]::IsNullOrWhiteSpace($displayName)) {
        $displayName = $nom
    }

    if ([string]::IsNullOrWhiteSpace($displayName)) { $displayName = 'Personne inconnue' }
    return $displayName
}

# --- Label de groupe ---
function Get-GroupLabel {
    param([string]$Groupe)
    switch ($Groupe.Trim().ToLowerInvariant()) {
        'famille' { return ':family: Famille' }
        'amis'    { return ':busts_in_silhouette: Amis' }
        default   { return ":pushpin: $Groupe" }
    }
}

# --- Calcul de l'âge ---
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

# --- Envoi Discord avec retry (3 tentatives, 10s d'attente) ---
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
        }
        catch {
            if ($attempt -lt $maxRetries) {
                Write-Log "AVERTISSEMENT : Tentative $attempt/$maxRetries échouée (Discord). Nouvel essai dans ${retryDelay}s... ($_)"
                Start-Sleep -Seconds $retryDelay
            }
            else {
                throw "ERREUR : Echec de l'envoi Discord apres $maxRetries tentatives : $_"
            }
        }
    }
}

###############################################################################
# Date du jour
###############################################################################
try {
    $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById($TimeZoneId)
}
catch {
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
# Démarrage du log
###############################################################################
Write-Log "--- Exécution du birthday bot ---"

###############################################################################
# Protection anti-doublon
###############################################################################
if (Test-Path -LiteralPath $LastRunFile) {
    $lastRun = (Get-Content -LiteralPath $LastRunFile -Encoding UTF8).Trim()
    if ($lastRun -eq $todayStr) {
        Write-Log "Déjà exécuté aujourd'hui ($todayStr). Arrêt du script."
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
    # Ligne vide ou sans groupe — ignorée silencieusement
    if ([string]::IsNullOrWhiteSpace($row.groupe)) { continue }

    $displayName = Get-DisplayName -Person $row
    $dayRaw      = "$($row.jour)".Trim()
    $monthRaw    = "$($row.mois)".Trim()
    $yearRaw     = "$($row.annee)".Trim()

    # Pas de date renseignée (x ou vide) — ignorée silencieusement
    if ([string]::IsNullOrWhiteSpace($dayRaw) -or $dayRaw -eq 'x') { continue }

    # Jour non numérique
    $dayValue = 0
    if (-not [int]::TryParse($dayRaw, [ref]$dayValue)) {
        Write-Log "AVERTISSEMENT CSV : Jour invalide '$dayRaw' pour '$displayName' — ligne ignorée."
        $warningCount++
        continue
    }

    # Mois non reconnu
    $monthValue = Get-MonthNumber -MonthName $monthRaw
    if ($null -eq $monthValue) {
        Write-Log "AVERTISSEMENT CSV : Mois non reconnu '$monthRaw' pour '$displayName' — ligne ignorée."
        $warningCount++
        continue
    }

    # Année (optionnelle)
    $yearValue = $null
    $yearInt   = 0
    if (-not [string]::IsNullOrWhiteSpace($yearRaw) -and $yearRaw -ne 'x') {
        if ([int]::TryParse($yearRaw, [ref]$yearInt) -and $yearInt -gt 1900) {
            $yearValue = $yearInt
        }
        else {
            Write-Log "AVERTISSEMENT CSV : Année invalide '$yearRaw' pour '$displayName' — année ignorée."
            $warningCount++
        }
    }

    $description = "$($row.description)".Trim()
    $groupeRaw   = "$($row.groupe)".Trim()

    # --- Anniversaire aujourd'hui ---
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

    # --- Anniversaires dans les 7 prochains jours ---
    for ($offset = 1; $offset -le 7; $offset++) {
        $futureDate = $today.AddDays($offset)
        if ($dayValue -eq $futureDate.Day -and $monthValue -eq $futureDate.Month) {
            $age = $null
            if ($null -ne $yearValue) {
                $age = Get-AgeAtDate -BirthYear $yearValue -BirthMonth $monthValue -BirthDay $dayValue -AtDate $futureDate
            }
            $birthdaysSoon.Add([pscustomobject]@{
                Name   = $displayName
                Group  = $groupeRaw
                Age    = $age
                Date   = $futureDate
                Offset = $offset
            })
            break
        }
    }
}

if ($warningCount -gt 0) {
    Write-Log "CSV : $warningCount ligne(s) avec des données incorrectes (voir avertissements ci-dessus)."
}

###############################################################################
# Embed : anniversaires du jour
###############################################################################
if ($birthdaysToday.Count -gt 0) {
    $fields = @()
    foreach ($b in $birthdaysToday) {
        $fieldName = "$(Get-GroupLabel $b.Group)  —  $($b.Name)"

        if ($null -ne $b.Age) {
            $fieldValue = "Fête ses **$($b.Age) ans** aujourd'hui ! :birthday:"
        }
        else {
            $fieldValue = "Bon anniversaire ! :birthday:"
        }

        if (-not [string]::IsNullOrWhiteSpace($b.Description) -and $b.Description -ne 'x') {
            $fieldValue += "`n*$($b.Description)*"
        }

        $fields += @{ name = $fieldName; value = $fieldValue; inline = $false }
    }

    $embed = @{
        title       = ":tada: Joyeux anniversaire !"
        description = "Aujourd'hui nous fêtons :"
        color       = 16766720
        fields      = $fields
        footer      = @{ text = "Birthday Bot" }
        timestamp   = $today.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    }

    Send-DiscordEmbed -Content '@everyone' -Embed $embed
    Write-Log "Embed anniversaire envoyé pour $($birthdaysToday.Count) personne(s) : $(($birthdaysToday | ForEach-Object { $_.Name }) -join ', ')"
}
else {
    $embed = @{
        title       = ":white_check_mark: Aucun anniversaire aujourd'hui"
        description = "Joyeux non-anniversaire à tous !"
        color       = 5763719
        footer      = @{ text = "Birthday Bot" }
        timestamp   = $today.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    }

    Send-DiscordEmbed -Embed $embed
    Write-Log "Aucun anniversaire aujourd'hui."
}

###############################################################################
# Embed : anniversaires à venir dans les 7 jours (sans ping)
###############################################################################
if ($birthdaysSoon.Count -gt 0) {
    $sorted = $birthdaysSoon | Sort-Object Offset
    $fields = @()

    foreach ($item in $sorted) {
        $dayName   = Get-DayName   -DayOfWeek   $item.Date.DayOfWeek
        $monthName = Get-MonthName -MonthNumber  $item.Date.Month

        $quand = if ($item.Offset -eq 1) {
            "Demain — $dayName $($item.Date.Day) $monthName"
        }
        else {
            "Dans $($item.Offset) jours — $dayName $($item.Date.Day) $monthName"
        }

        $fieldName  = "$(Get-GroupLabel $item.Group)  —  $($item.Name)"
        $fieldValue = $quand
        if ($null -ne $item.Age) {
            $fieldValue += "`nFêtera ses **$($item.Age) ans** :birthday:"
        }

        $fields += @{ name = $fieldName; value = $fieldValue; inline = $false }
    }

    $embed = @{
        title       = ":calendar_spiral: Anniversaires à venir — $($sorted.Count) dans les 7 prochains jours"
        color       = 5793266
        fields      = $fields
        footer      = @{ text = "Birthday Bot" }
        timestamp   = $today.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    }

    Send-DiscordEmbed -Embed $embed
    Write-Log "Récapitulatif envoyé : $($sorted.Count) anniversaire(s) à venir."
}
else {
    Write-Log "Aucun anniversaire dans les 7 prochains jours."
}

###############################################################################
# Mise à jour de la date de dernière exécution
###############################################################################
$todayStr | Set-Content -LiteralPath $LastRunFile -Encoding UTF8

Write-Log "--- Fin d'exécution ---"
