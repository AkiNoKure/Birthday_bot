# Birthday Bot Discord

Un seul processus Python, **sans webhook** :
- commandes slash : `/add-birthday`, `/edit-birthday`, `/list-birthdays`, `/delete-birthday`, `/export-birthdays` ;
- chaque jour, le bot poste dans un salon les anniversaires du jour (`@everyone`) et ceux des 7 prochains jours.

L'annonce part à `ANNOUNCE_HOUR` (9h par défaut), une fois par jour. Si le PC était éteint, elle part au redémarrage.

## Structure

```
bot.py                  # tout le bot
requirements.txt        # discord.py
.env.example            # modèle de configuration (le vrai .env n'est jamais versionné)
contacts_data.example.csv     # exemple de CSV à importer (optionnel)
birthdays.db            # base SQLite des anniversaires (générée, non versionnée)
backups/                # sauvegardes automatiques de la base (générées, non versionnées)
register-startup.ps1    # démarrage automatique Windows (une fois)
start-bot.bat           # lancement manuel
update.bat              # git pull + relance du bot
```

## Installation

1. `git clone https://github.com/TON_USERNAME/birthday-bot.git` puis `cd birthday-bot`
2. `pip install -r requirements.txt`
3. `copy .env.example .env` puis remplis `BOT_TOKEN` et `CHANNEL_ID`
4. (optionnel) `copy contacts_data.example.csv contacts_data.csv` : si ce fichier existe au premier démarrage, il est importé dans la base. Sinon, ajoute tes contacts avec `/add-birthday`.
5. Crée le bot sur [discord.com/developers/applications](https://discord.com/developers/applications) : **Bot → Reset Token** (copie-le dans `.env`).
   **OAuth2 → URL Generator** : scopes `bot` + `applications.commands`, permissions dans le salon d'annonces :
   `View Channel`, `Send Messages`, `Embed Links`, `Mention Everyone`. Invite le bot avec l'URL générée.
6. Lance `start-bot.bat` pour tester.

## Stockage des anniversaires

Les données sont dans **`birthdays.db`** (SQLite, fichier unique, aucune dépendance).
- Chaque contact a un **identifiant unique** : deux « Mamie » peuvent coexister, et `/edit-birthday` / `/delete-birthday` proposent une liste pour choisir le bon.
- La base **refuse les données invalides** (groupe inconnu, jour hors 1-31, année absurde).
- Écritures atomiques : une coupure en pleine écriture ne corrompt rien.
- **Sauvegarde automatique** à chaque démarrage : `backups/birthdays-AAAA-MM-JJ.db`, 7 jours conservés.
- **`/export-birthdays`** t'envoie (à toi seul) un CSV lisible dans Excel, au même format que l'import (`groupe;pseudo;nom;prenom;jour;mois;annee;description;ajoute_par`, `x` = inconnu).

La base contient des données personnelles : elle n'est **jamais** dans Git (`.gitignore`). Pour déplacer le bot sur un autre PC, copie `birthdays.db` (ou importe un export CSV).

## Démarrage automatique

`powershell -ExecutionPolicy Bypass -File register-startup.ps1` (une fois, en administrateur).

## Déploiement / mise à jour via GitHub

Le dépôt ne contient aucun secret (`.env` et `contacts_data.csv` sont dans `.gitignore`).
Workflow : tu modifies le code, `git push`, puis sur le PC du bot tu lances `update.bat`
(`git pull` + `pip install` + relance de la tâche).

Fichiers générés : `birthdays.db`, `backups/`, `birthday-bot.log` (rotation auto), `last_run.txt` (anti-doublon).
