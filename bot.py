import discord
from discord import app_commands
import csv
import os
from pathlib import Path

###############################################################################
# Config
###############################################################################
SCRIPT_DIR = Path(__file__).parent

MONTHS_TO_NUM = {
    'janvier': 1, 'fevrier': 2, 'fevrier': 2, 'mars': 3, 'avril': 4,
    'mai': 5, 'juin': 6, 'juillet': 7, 'aout': 8,
    'septembre': 9, 'octobre': 10, 'novembre': 11, 'decembre': 12
}

MONTHS_DISPLAY = [
    'janvier', 'fevrier', 'mars', 'avril', 'mai', 'juin',
    'juillet', 'aout', 'septembre', 'octobre', 'novembre', 'decembre'
]

MONTH_ALIASES = {
    'février': 'fevrier', 'août': 'aout', 'décembre': 'decembre'
}

###############################################################################
# Lecture du .env
###############################################################################
def read_env():
    env = {}
    env_file = SCRIPT_DIR / '.env'
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('=', 1)
            if len(parts) == 2:
                env[parts[0].strip()] = parts[1].strip()
    return env

###############################################################################
# CSV helpers
###############################################################################
FIELDNAMES = ['groupe', 'pseudo', 'nom', 'prenom', 'jour', 'mois', 'annee', 'description']

def read_csv(data_file):
    rows = []
    with open(data_file, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            # Skip blank rows
            if not row.get('groupe', '').strip():
                continue
            rows.append(row)
    return rows

def write_csv(data_file, rows):
    with open(data_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter=';')
        writer.writeheader()
        writer.writerow({k: '' for k in FIELDNAMES})  # blank line after header

        # Group by groupe for readability
        groupes = {}
        for row in rows:
            g = row.get('groupe', 'Autre')
            groupes.setdefault(g, []).append(row)

        first = True
        for g, group_rows in groupes.items():
            if not first:
                writer.writerow({k: '' for k in FIELDNAMES})  # blank line between groups
            first = False
            for row in group_rows:
                writer.writerow({k: row.get(k, 'x') for k in FIELDNAMES})

def normalize_month(mois_input):
    """Normalise le nom du mois en minuscules sans accents."""
    m = mois_input.strip().lower()
    m = MONTH_ALIASES.get(m, m)
    return m

###############################################################################
# Bot setup
###############################################################################
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

config = read_env()
DATA_FILE = config.get('DATA_FILE')
BOT_TOKEN = config.get('BOT_TOKEN')

if not DATA_FILE or not BOT_TOKEN:
    raise ValueError("DATA_FILE et BOT_TOKEN doivent etre definis dans .env")

###############################################################################
# Autocomplete helpers
###############################################################################
async def autocomplete_groupe(interaction: discord.Interaction, current: str):
    choices = ['Amis', 'Famille']
    return [app_commands.Choice(name=c, value=c) for c in choices if current.lower() in c.lower()]

async def autocomplete_mois(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=m, value=m)
        for m in MONTHS_DISPLAY
        if current.lower() in m
    ][:10]

async def autocomplete_pseudo(interaction: discord.Interaction, current: str):
    try:
        rows = read_csv(DATA_FILE)
        pseudos = [r['pseudo'] for r in rows if r.get('pseudo') and r['pseudo'] != 'x']
        return [
            app_commands.Choice(name=p, value=p)
            for p in pseudos
            if current.lower() in p.lower()
        ][:10]
    except Exception:
        return []

###############################################################################
# /add-birthday
###############################################################################
@tree.command(name="add-birthday", description="Ajouter un anniversaire au fichier")
@app_commands.describe(
    pseudo="Pseudo ou surnom (ex: Zouille)",
    groupe="Groupe : Amis ou Famille",
    jour="Jour du mois (ex: 15)",
    mois="Mois en francais (ex: juillet)",
    annee="Annee de naissance (optionnel, ex: 2000)",
    nom="Nom de famille (optionnel)",
    prenom="Prenom (optionnel)",
    description="Description courte (optionnel)"
)
@app_commands.autocomplete(groupe=autocomplete_groupe, mois=autocomplete_mois)
async def add_birthday(
    interaction: discord.Interaction,
    pseudo: str,
    groupe: str,
    jour: int,
    mois: str,
    annee: str = 'x',
    nom: str = 'x',
    prenom: str = 'x',
    description: str = 'x'
):
    mois_norm = normalize_month(mois)

    # Validation
    if mois_norm not in MONTHS_TO_NUM:
        await interaction.response.send_message(
            f":x: Mois invalide : `{mois}`\nMois acceptes : {', '.join(MONTHS_DISPLAY)}",
            ephemeral=True
        )
        return

    if not 1 <= jour <= 31:
        await interaction.response.send_message(f":x: Jour invalide : `{jour}`", ephemeral=True)
        return

    groupe_clean = groupe.strip().capitalize()
    if groupe_clean not in ('Amis', 'Famille'):
        await interaction.response.send_message(
            ":x: Groupe invalide. Utilise `Amis` ou `Famille`.", ephemeral=True
        )
        return

    rows = read_csv(DATA_FILE)

    # Verifier doublon
    for row in rows:
        if row.get('pseudo', '').strip().lower() == pseudo.lower():
            await interaction.response.send_message(
                f":warning: `{pseudo}` existe deja. Utilise `/delete-birthday` puis `/add-birthday` pour corriger.",
                ephemeral=True
            )
            return

    new_row = {
        'groupe':      groupe_clean,
        'pseudo':      pseudo.strip(),
        'nom':         nom.strip() if nom and nom != 'x' else 'x',
        'prenom':      prenom.strip() if prenom and prenom != 'x' else 'x',
        'jour':        str(jour),
        'mois':        mois_norm,
        'annee':       annee.strip() if annee and annee != 'x' else 'x',
        'description': description.strip() if description and description != 'x' else 'x',
    }

    rows.append(new_row)
    write_csv(DATA_FILE, rows)

    age_str = f" ({annee})" if annee and annee != 'x' else ""
    await interaction.response.send_message(
        f":white_check_mark: **{pseudo}** ajoute ! Anniversaire le **{jour} {mois_norm}{age_str}** — {groupe_clean}"
    )

###############################################################################
# /list-birthdays
###############################################################################
@tree.command(name="list-birthdays", description="Afficher tous les anniversaires")
@app_commands.describe(groupe="Filtrer par groupe (optionnel)")
@app_commands.autocomplete(groupe=autocomplete_groupe)
async def list_birthdays(interaction: discord.Interaction, groupe: str = None):
    rows = read_csv(DATA_FILE)

    filtered = [r for r in rows if r.get('jour', 'x') != 'x' and r['jour'].isdigit()]
    if groupe:
        filtered = [r for r in filtered if r.get('groupe', '').lower() == groupe.lower()]

    def sort_key(r):
        month_num = MONTHS_TO_NUM.get(r.get('mois', '').lower(), 99)
        day = int(r.get('jour', 0))
        return (month_num, day)

    filtered.sort(key=sort_key)

    if not filtered:
        await interaction.response.send_message("Aucun anniversaire trouve.", ephemeral=True)
        return

    lines = []
    for r in filtered:
        pseudo = r.get('pseudo', 'x')
        prenom = r.get('prenom', 'x')
        name = pseudo if pseudo != 'x' else (prenom if prenom != 'x' else 'Inconnu')
        jour = r.get('jour', '?')
        mois = r.get('mois', '?')
        annee = r.get('annee', 'x')
        grp = r.get('groupe', '')
        emoji = ':family:' if grp.lower() == 'famille' else ':busts_in_silhouette:'
        age_str = f" ({annee})" if annee and annee != 'x' else ''
        lines.append(f"{emoji} **{name}** — {jour} {mois}{age_str}")

    titre = f"**Anniversaires{' — ' + groupe if groupe else ''}** ({len(filtered)} contact(s))\n\n"
    message = titre + "\n".join(lines)

    # Discord limite a 2000 caracteres
    if len(message) > 1900:
        message = titre + "\n".join(lines[:20]) + f"\n\n*... et {len(lines) - 20} autre(s). Filtre par groupe pour voir tout.*"

    await interaction.response.send_message(message, ephemeral=True)

###############################################################################
# /delete-birthday
###############################################################################
@tree.command(name="delete-birthday", description="Supprimer un anniversaire")
@app_commands.describe(pseudo="Pseudo du contact a supprimer")
@app_commands.autocomplete(pseudo=autocomplete_pseudo)
async def delete_birthday(interaction: discord.Interaction, pseudo: str):
    rows = read_csv(DATA_FILE)
    new_rows = [r for r in rows if r.get('pseudo', '').strip().lower() != pseudo.strip().lower()]

    if len(new_rows) == len(rows):
        await interaction.response.send_message(
            f":x: Aucun contact trouve avec le pseudo `{pseudo}`.", ephemeral=True
        )
        return

    write_csv(DATA_FILE, new_rows)
    await interaction.response.send_message(f":wastebasket: **{pseudo}** supprime du fichier.")

###############################################################################
# Events
###############################################################################
@client.event
async def on_ready():
    await tree.sync()
    print(f"Bot connecte : {client.user} — commandes synchronisees.")

###############################################################################
# Lancement
###############################################################################
client.run(BOT_TOKEN)
