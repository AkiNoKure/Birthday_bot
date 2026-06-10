#requires -Version 5.1
# Lance ce script UNE SEULE FOIS pour enregistrer le bot au demarrage de Windows.

$taskName   = "BirthdayBot"
$vbsPath    = "C:\Scripts\birthday-bot\launch-bot-silent.vbs"
$delayStart = "PT1M"   # attend 1 minute apres connexion avant de demarrer

# Supprime l'ancienne tache si elle existe
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action  = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbsPath`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$trigger.Delay = $delayStart

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "Tache '$taskName' enregistree avec succes." -ForegroundColor Green
Write-Host "Le bot Discord demarrera automatiquement 1 minute apres chaque connexion Windows."
