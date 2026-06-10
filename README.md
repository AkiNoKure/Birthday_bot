# Birthday Bot Discord

Bot Discord qui envoie automatiquement des rappels d'anniversaires dans un salon Discord via webhook, avec un bot slash pour gérer les contacts facilement.

## Fonctionnalités

- Annonce les anniversaires du jour avec `@everyone` (embed Discord)
- Récapitulatif des anniversaires dans les 7 prochains jours (sans ping)
- Affichage de l'âge pour les contacts dont l'année de naissance est connue
- Groupe affiché (Amis / Famille) dans chaque message
- Bot Discord avec commandes slash pour ajouter/lister/supprimer des anniversaires
- Protection anti-doublon (ne s'exécute qu'une fois par jour)
- Retry automatique en cas de coupure réseau
- Fichier de logs avec rotation automatique

## Structure du projet

```
birthday-bot/
├── birthday-discord.ps1          # Script webhook (envoie les messages Discord)
├── bot.py                        # Bot Discord (commandes slash)
├── contacts_data.csv             # Fichier de données (non versionné)
├── contacts_data.example.csv     # Exemple de format CSV
├── .env                          # Configuration (non versionné)
├── .env.example                  # Modèle de configuration
├── launch-bot-silent.vbs         # Lance le bot sans fenêtre
├── launch-webhook-silent.vbs     # Lance le webhook sans fenêtre
├── register-startup.ps1          # Enregistre le bot au démarrage Windows
├── start-bot.bat                 # Lance le bot manuellement
└── requirements.txt              # Dépendances Python
```

## Installation

### Prérequis

- Windows 10/11
- PowerShell 5.1+
- Python 3.8+

### 1. Cloner le projet

```bash
git clone https://github.com/TON_USERNAME/birthday-bot.git
cd birthday-bot
```

### 2. Configurer l'environnement

Copie `.env.example` en `.env` et remplis les valeurs :

```bash
copy .env.example .env
```

```env
WEBHOOK_URL=https://discord.com/api/webhooks/...   # Webhook de ton salon Discord
DATA_FILE=C:\chemin\vers\contacts_data.csv          # Chemin absolu vers ton CSV
TIMEZONE=Romance Standard Time                       # Fuseau horaire
BOT_TOKEN=ton_token_ici                             # Token du bot Discord
```

### 3. Créer le fichier de contacts

Copie l'exemple et remplis avec tes contacts :

```bash
copy contacts_data.example.csv contacts_data.csv
```

Format du CSV (séparateur `;`) :

| Colonne | Description | Valeur si inconnue |
|---|---|---|
| groupe | `Amis` ou `Famille` | — |
| pseudo | Pseudo/surnom | `x` |
| nom | Nom de famille | `x` |
| prenom | Prénom | `x` |
| jour | Jour (numérique) | `x` |
| mois | Mois en français | `x` |
| annee | Année de naissance | `x` |
| description | Description courte | `x` |

### 4. Installer les dépendances Python

```bash
pip install -r requirements.txt
```

### 5. Créer le bot Discord

1. Va sur [discord.com/developers/applications](https://discord.com/developers/applications)
2. **New Application** → donne un nom
3. Onglet **Bot** → **Reset Token** → copie le token dans `.env`
4. Onglet **OAuth2 → URL Generator** → coche `bot` + `applications.commands`
5. Permissions : `Send Messages` + `Read Messages/View Channels`
6. Copie l'URL générée et invite le bot sur ton serveur

## Utilisation

### Lancer le webhook manuellement

```powershell
powershell -ExecutionPolicy Bypass -File "birthday-discord.ps1"
```

### Lancer le bot Discord

```bash
start-bot.bat
```

### Démarrage automatique avec Windows

Lance ce script **une seule fois** en administrateur :

```powershell
powershell -ExecutionPolicy Bypass -File "register-startup.ps1"
```

Le bot démarrera automatiquement 1 minute après chaque connexion Windows.

### Planifier le webhook quotidiennement

Utilise le Planificateur de tâches Windows pour exécuter `launch-webhook-silent.vbs` chaque matin à l'heure souhaitée.

## Commandes Discord

| Commande | Description |
|---|---|
| `/add-birthday` | Ajouter un anniversaire |
| `/list-birthdays` | Lister tous les anniversaires |
| `/delete-birthday` | Supprimer un anniversaire |

## Fichiers générés automatiquement

- `birthday-bot.log` — historique des exécutions (rotation automatique à 500 lignes)
- `last_run.txt` — date de la dernière exécution (protection anti-doublon)
