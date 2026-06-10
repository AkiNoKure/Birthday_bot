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
    'janvier': 1, 'fevrier': 2, 'mars': 3, 'avril': 4,
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

GROUPES_VALIDES = ['Amis', 'Famille', 'Special']

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
FIELDNAMES = ['groupe', 'pseudo', 'nom', 'prenom', 'jour', 'mois', 'annee', 'description', 'ajoute_par']

def read_csv(data_file):
    rows = []
    with open(data_file, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if not row.get('groupe', '').strip():
                continue
            rows.append(row)
    return rows

def write_csv(data_file, rows):
    with open(data_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter=';', extrasaction='ignore')
        writer.writeheader()
        writer.writerow({k: '' for k in FIELDNAMES})  # ligne vide apres header

        groupes = {}
        for row in rows:
            g = row.get('groupe', 'Autre')
            groupes.setdefault(g, []).append(row)

        first = True
        for g, group_rows in groupes.items():
            if not first:
                writer.writerow({k: '' for k in FIELDNAMES})
            first = False
            for row in group_rows:
                writer.writerow({k: row.get(k, 'x') or 'x' for k in FIELDNAMES})

def normalize_month(mois_input):
    m = mois_input.strip().lower()
    return MONTH_ALIASES.get(m, m)

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
# Autocomplete
###############################################################################
async def autocomplete_groupe(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=c, value=c)
        for c in GROUPES_VALIDES
        if current.lower() in c.lower()
    ]

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
    groupe="Groupe : Amis, Famille ou Special",
    jour="Jour du mois (ex: 15)",
    mois="Mois en francais (ex: juillet)",
    annee="Annee (optionnel, ex: 2000)",
    nom="Nom de famille (optionnel)",
    prenom="Prenom (optionnel)",
    description="Pour Amis/Famille : description courte. Pour Special : type d'evenement (ex: mariage, relation)"
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
    if groupe_clean not in GROUPES_VALIDES:
        await interaction.response.send_message(
            f":x: Groupe invalide. Utilise : {', '.join(GROUPES_VALIDES)}", ephemeral=True
        )
        return

    rows = read_csv(DATA_FILE)

    for row in rows:
        if row.get('pseudo', '').strip().lower() == pseudo.lower():
            await interaction.response.send_message(
                f":warning: `{pseudo}` existe deja. Utilise `/edit-birthday` pour modifier.",
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
        'ajoute_par':  interaction.user.display_name,
    }

    rows.append(new_row)
    write_csv(DATA_FILE, rows)

    age_str = f" ({annee})" if annee and annee != 'x' else ""
    groupe_emoji = ":sparkles:" if groupe_clean == "Special" else ":white_check_mark:"
    await interaction.response.send_message(
        f"{groupe_emoji} **{pseudo}** ajoute ! Le **{jour} {mois_norm}{age_str}** — {groupe_clean} (ajoute par {interaction.user.display_name})"
    )

###############################################################################
# /edit-birthday
###############################################################################
@tree.command(name="edit-birthday", description="Modifier une entree existante")
@app_commands.describe(
    pseudo="Pseudo du contact a modifier",
    nouveau_pseudo="Nouveau pseudo (optionnel)",
    groupe="Nouveau groupe (optionnel)",
    jour="Nouveau jour (optionnel)",
    mois="Nouveau mois (optionnel)",
    annee="Nouvelle annee (optionnel, 'x' pour effacer)",
    nom="Nouveau nom (optionnel, 'x' pour effacer)",
    prenom="Nouveau prenom (optionnel, 'x' pour effacer)",
    description="Nouvelle description (optionnel, 'x' pour effacer)"
)
@app_commands.autocomplete(pseudo=autocomplete_pseudo, groupe=autocomplete_groupe, mois=autocomplete_mois)
async def edit_birthday(
    interaction: discord.Interaction,
    pseudo: str,
    nouveau_pseudo: str = None,
    groupe: str = None,
    jour: int = None,
    mois: str = None,
    annee: str = None,
    nom: str = None,
    prenom: str = None,
    description: str = None
):
    rows = read_csv(DATA_FILE)

    target = None
    target_idx = None
    for i, row in enumerate(rows):
        if row.get('pseudo', '').strip().lower() == pseudo.strip().lower():
            target = dict(row)
            target_idx = i
            break

    if target is None:
        await interaction.response.send_message(
            f":x: Aucun contact trouve avec le pseudo `{pseudo}`.", ephemeral=True
        )
        return

    changes = []

    if nouveau_pseudo is not None:
        # Verifier que le nouveau pseudo n'existe pas deja
        for i, row in enumerate(rows):
            if i != target_idx and row.get('pseudo', '').strip().lower() == nouveau_pseudo.lower():
                await interaction.response.send_message(
                    f":x: Le pseudo `{nouveau_pseudo}` est deja utilise.", ephemeral=True
                )
                return
        changes.append(f"pseudo : `{target['pseudo']}` → `{nouveau_pseudo}`")
        target['pseudo'] = nouveau_pseudo.strip()

    if groupe is not None:
        groupe_clean = groupe.strip().capitalize()
        if groupe_clean not in GROUPES_VALIDES:
            await interaction.response.send_message(
                f":x: Groupe invalide. Utilise : {', '.join(GROUPES_VALIDES)}", ephemeral=True
            )
            return
        changes.append(f"groupe : `{target.get('groupe', 'x')}` → `{groupe_clean}`")
        target['groupe'] = groupe_clean

    if jour is not None:
        if not 1 <= jour <= 31:
            await interaction.response.send_message(":x: Jour invalide.", ephemeral=True)
            return
        changes.append(f"jour : `{target.get('jour', 'x')}` → `{jour}`")
        target['jour'] = str(jour)

    if mois is not None:
        mois_norm = normalize_month(mois)
        if mois_norm not in MONTHS_TO_NUM:
            await interaction.response.send_message(f":x: Mois invalide : `{mois}`", ephemeral=True)
            return
        changes.append(f"mois : `{target.get('mois', 'x')}` → `{mois_norm}`")
        target['mois'] = mois_norm

    if annee is not None:
        changes.append(f"annee : `{target.get('annee', 'x')}` → `{annee.strip() or 'x'}`")
        target['annee'] = annee.strip() if annee.strip() else 'x'

    if nom is not None:
        changes.append(f"nom : `{target.get('nom', 'x')}` → `{nom.strip() or 'x'}`")
        target['nom'] = nom.strip() if nom.strip() else 'x'

    if prenom is not None:
        changes.append(f"prenom : `{target.get('prenom', 'x')}` → `{prenom.strip() or 'x'}`")
        target['prenom'] = prenom.strip() if prenom.strip() else 'x'

    if description is not None:
        changes.append(f"description mise a jour")
        target['description'] = description.strip() if description.strip() else 'x'

    if not changes:
        await interaction.response.send_message(
            ":information_source: Aucune modification fournie.", ephemeral=True
        )
        return

    rows[target_idx] = target
    write_csv(DATA_FILE, rows)

    changes_text = "\n".join(f"• {c}" for c in changes)
    await interaction.response.send_message(
        f":pencil: **{pseudo}** modifie par {interaction.user.display_name} :\n{changes_text}"
    )

###############################################################################
# /list-birthdays
###############################################################################
@tree.command(name="list-birthdays", description="Afficher tous les anniversaires")
@app_commands.describe(groupe="Filtrer par groupe (optionnel)")
@app_commands.autocomplete(groupe=autocomplete_groupe)
async def list_birthdays(interaction: discord.Interaction, groupe: str = None):
    rows = read_csv(DATA_FILE)

    filtered = [r for r in rows if r.get('jour', 'x') != 'x' and r.get('jour', '').isdigit()]
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
        ajoute_par = r.get('ajoute_par', 'x')

        if grp.lower() == 'famille':
            emoji = ':family:'
        elif grp.lower() == 'special':
            emoji = ':sparkles:'
        else:
            emoji = ':busts_in_silhouette:'

        age_str = f" ({annee})" if annee and annee != 'x' else ''
        added_str = f" *— ajoute par {ajoute_par}*" if ajoute_par and ajoute_par != 'x' else ''
        lines.append(f"{emoji} **{name}** — {jour} {mois}{age_str}{added_str}")

    titre = f"**Anniversaires{' — ' + groupe if groupe else ''}** ({len(filtered)} contact(s))\n\n"
    message = titre + "\n".join(lines)

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
    await interaction.response.send_message(
        f":wastebasket: **{pseudo}** supprime par {interaction.user.display_name}."
    )

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
