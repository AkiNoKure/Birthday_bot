"""Birthday Bot : commandes slash + annonces quotidiennes dans un seul processus."""
import csv
import io
import logging
import sqlite3
import unicodedata
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal, Optional, get_args

import discord
from discord import app_commands
from discord.ext import tasks

DIR = Path(__file__).parent

###############################################################################
# Config (.env)
###############################################################################
def read_env():
    env, path = {}, DIR / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env

ENV = read_env()
TOKEN = ENV.get("BOT_TOKEN")
CHANNEL_ID = int(ENV.get("CHANNEL_ID") or 0)  # salon des annonces
DB_FILE = DIR / "birthdays.db"
BACKUP_DIR = DIR / "backups"
LEGACY_CSV = Path(ENV.get("DATA_FILE") or DIR / "contacts_data.csv")  # importe une seule fois si present
ANNOUNCE_HOUR = int(ENV.get("ANNOUNCE_HOUR") or 9)  # heure locale du PC
LAST_RUN = DIR / "last_run.txt"

# Logs : fichier a rotation automatique (200 Ko max + 1 archive)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        RotatingFileHandler(DIR / "birthday-bot.log", maxBytes=200_000, backupCount=1, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logging.getLogger("discord").setLevel(logging.WARNING)
log = logging.getLogger("birthday")

###############################################################################
# Constantes
###############################################################################
Groupe = Literal["Amis", "Famille", "Special"]
Mois = Literal["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
               "aout", "septembre", "octobre", "novembre", "decembre"]
Jour = app_commands.Range[int, 1, 31]

GROUPES = list(get_args(Groupe))
MONTHS = list(get_args(Mois))
ACCENTS = {"fevrier": "février", "aout": "août", "decembre": "décembre"}
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
LABELS = {"famille": ":family: Famille", "amis": ":busts_in_silhouette: Amis", "special": ":sparkles: Spécial"}
CSV_FIELDS = ["groupe", "pseudo", "nom", "prenom", "jour", "mois", "annee", "description", "ajoute_par"]

###############################################################################
# Helpers
###############################################################################
def norm(text):
    """minuscules + sans accents ('Février' -> 'fevrier')."""
    text = unicodedata.normalize("NFD", text.strip().lower())
    return "".join(c for c in text if not unicodedata.combining(c))

def clean(value):
    """Texte affichable : '' si vide, NULL ou 'x' (= inconnu)."""
    value = "" if value is None else str(value).strip()
    return "" if value == "x" else value

def txt(value):
    """Texte a stocker : NULL si vide ou 'x'."""
    return clean(value) or None

def parse_year(text):
    """-> (annee | None, erreur | None). 'x' ou vide = pas d'annee."""
    text = clean(text)
    if not text:
        return None, None
    if text.isdigit() and 1900 <= int(text) <= 2100:
        return int(text), None
    return None, f":x: Année invalide : `{text}` (ex: 2000, ou `x` pour effacer)."

def show(value):
    return "x" if value is None else str(value)

def label(groupe):
    return LABELS.get(groupe.strip().lower(), f":pushpin: {groupe}")

def display_name(row):
    pseudo, prenom, nom = (clean(row.get(k)) for k in ("pseudo", "prenom", "nom"))
    full = f"{prenom} {nom}".strip()
    if pseudo:
        return f"{pseudo} ({full})" if prenom else pseudo
    return full or "Personne inconnue"

###############################################################################
# Stockage : SQLite (fichier unique, ecritures atomiques, aucune dependance)
###############################################################################
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS birthdays (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    groupe      TEXT    NOT NULL CHECK (groupe IN ({", ".join(repr(g) for g in GROUPES)})),
    pseudo      TEXT,
    nom         TEXT,
    prenom      TEXT,
    jour        INTEGER CHECK (jour  BETWEEN 1 AND 31),
    mois        INTEGER CHECK (mois  BETWEEN 1 AND 12),
    annee       INTEGER CHECK (annee BETWEEN 1900 AND 2100),
    description TEXT,
    ajoute_par  TEXT,
    cree_le     TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK ((jour IS NULL) = (mois IS NULL))
);
"""

@contextmanager
def db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = lambda cur, row: {c[0]: v for c, v in zip(cur.description, row)}
    try:
        with con:  # commit si tout va bien, rollback si exception
            yield con
    finally:
        con.close()

def insert(con, **r):
    con.execute(
        "INSERT INTO birthdays (groupe, pseudo, nom, prenom, jour, mois, annee, description, ajoute_par) "
        "VALUES (:groupe, :pseudo, :nom, :prenom, :jour, :mois, :annee, :description, :ajoute_par)", r)

def import_csv(con, path):
    """Ancien format (contacts_data.csv) -> base. Les lignes vides/separateurs sont ignorees."""
    count = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            groupe = clean(r.get("groupe")).capitalize()
            if groupe not in GROUPES:
                continue
            try:
                jour, mois = int(clean(r.get("jour"))), MONTHS.index(norm(r.get("mois") or "")) + 1
                if not 1 <= jour <= 31:
                    raise ValueError
            except ValueError:
                jour = mois = None
            annee, _ = parse_year(r.get("annee"))
            insert(con, groupe=groupe, pseudo=txt(r.get("pseudo")), nom=txt(r.get("nom")),
                   prenom=txt(r.get("prenom")), jour=jour, mois=mois, annee=annee,
                   description=txt(r.get("description")), ajoute_par=txt(r.get("ajoute_par")))
            count += 1
    return count

def init_db():
    with db() as con:
        con.executescript(SCHEMA)
        if con.execute("PRAGMA user_version").fetchone()["user_version"] == 0:  # premier demarrage
            if LEGACY_CSV.exists():
                log.info("Import de %s : %d contact(s).", LEGACY_CSV.name, import_csv(con, LEGACY_CSV))
            con.execute("PRAGMA user_version = 1")

def backup():
    """Copie de la base au demarrage (1 fichier par jour, 7 conserves)."""
    BACKUP_DIR.mkdir(exist_ok=True)
    with db() as con, closing(sqlite3.connect(BACKUP_DIR / f"birthdays-{date.today()}.db")) as out:
        con.backup(out)
    for old in sorted(BACKUP_DIR.glob("birthdays-*.db"))[:-7]:
        old.unlink()

def resolve(con, value):
    """Retrouve un contact par id (choix de l'autocomplete) ou par pseudo. -> (row, erreur)"""
    value = value.strip()
    if value.isdigit():
        rows = con.execute("SELECT * FROM birthdays WHERE id = ?", (int(value),)).fetchall()
    else:
        rows = con.execute("SELECT * FROM birthdays WHERE pseudo = ? COLLATE NOCASE", (value,)).fetchall()
    if not rows:
        return None, f":x: Aucun contact trouvé pour `{value}`."
    if len(rows) > 1:
        return None, f":warning: Plusieurs contacts s'appellent `{value}` : choisis-le dans la liste proposée."
    return rows[0], None

###############################################################################
# Annonce quotidienne
###############################################################################
def make_embed(title, color, fields, description=None):
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)
    return embed.set_footer(text="Birthday Bot")

def build_message(today, rows):
    """-> (content, embeds, nb_aujourdhui, nb_a_venir)"""
    people = {}
    for row in rows:
        if row["jour"]:
            people.setdefault((row["mois"], row["jour"]), []).append((row, row["annee"]))

    def on(offset):
        d = today + timedelta(days=offset)
        return d, [(r, d.year - y if y else None) for r, y in people.get((d.month, d.day), [])]

    # Aujourd'hui
    _, todays = on(0)
    if todays:
        fields = []
        for r, age in todays:
            desc = clean(r.get("description"))
            if r["groupe"].strip().lower() == "special":
                value = f":tada: Bon anniversaire de **{desc}** !" if desc else ":tada: Bon anniversaire !"
                if age is not None:
                    value += f" ({age} ans)"
            else:
                value = (f"Fête ses **{age} ans** aujourd'hui ! :birthday:" if age is not None
                         else "Bon anniversaire ! :birthday:")
                if desc:
                    value += f"\n*{desc}*"
            fields.append((f"{label(r['groupe'])}  -  {display_name(r)}", value))
        embeds = [make_embed(":tada: Joyeux anniversaire !", 16766720, fields, "Aujourd'hui nous fêtons :")]
        content = "@everyone"
    else:
        embeds = [make_embed(":white_check_mark: Aucun anniversaire aujourd'hui", 5763719, [],
                             "Joyeux non-anniversaire à tous !")]
        content = None

    # 7 prochains jours (dans le meme message, sans ping supplementaire)
    fields = []
    for offset in range(1, 8):
        d, upcoming = on(offset)
        for r, age in upcoming:
            quand = "Demain" if offset == 1 else f"Dans {offset} jours"
            quand += f" - {DAYS[d.weekday()]} {d.day} {ACCENTS.get(MONTHS[d.month - 1], MONTHS[d.month - 1])}"
            if r["groupe"].strip().lower() == "special":
                desc = clean(r.get("description"))
                value = f"{quand}\nAnniversaire" + (f" de **{desc}**" if desc else "")
                if age is not None:
                    value += f" ({age} ans)"
            else:
                value = quand + (f"\nFêtera ses **{age} ans** :birthday:" if age is not None else "")
            fields.append((f"{label(r['groupe'])}  -  {display_name(r)}", value))
    if fields:
        embeds.append(make_embed(
            f":calendar_spiral: Anniversaires à venir - {len(fields)} dans les 7 prochains jours", 5793266, fields))

    return content, embeds, len(todays), len(fields)

def all_rows():
    with db() as con:
        return con.execute("SELECT * FROM birthdays ORDER BY id").fetchall()

async def announce():
    today = datetime.now().date()
    # utf-8-sig : l'ancien script PowerShell ecrivait ce fichier avec un BOM
    if LAST_RUN.exists() and LAST_RUN.read_text(encoding="utf-8-sig").strip() == str(today):
        return
    content, embeds, n_today, n_soon = build_message(today, all_rows())

    channel = client.get_channel(CHANNEL_ID) or await client.fetch_channel(CHANNEL_ID)
    await channel.send(content=content, embeds=embeds, allowed_mentions=discord.AllowedMentions(everyone=True))

    LAST_RUN.write_text(str(today), encoding="utf-8")
    log.info("Annonce envoyee : %d anniversaire(s) aujourd'hui, %d a venir.", n_today, n_soon)

@tasks.loop(minutes=10)
async def daily_check():
    # Rattrapage inclus : si le PC etait eteint a l'heure prevue, l'annonce part au demarrage.
    if datetime.now().hour < ANNOUNCE_HOUR:
        return
    try:
        await announce()
    except Exception:
        log.exception("Echec de l'annonce quotidienne (nouvel essai dans 10 min)")

@daily_check.before_loop
async def _wait_ready():
    await client.wait_until_ready()

###############################################################################
# Bot
###############################################################################
class BirthdayBot(discord.Client):
    async def setup_hook(self):
        init_db()
        backup()
        await tree.sync()
        if CHANNEL_ID:
            daily_check.start()
        else:
            log.warning("CHANNEL_ID absent : annonces quotidiennes desactivees.")
        log.info("Bot demarre, commandes synchronisees.")

discord.VoiceClient.warn_nacl = False  # pas de vocal : inutile de prevenir
discord.VoiceClient.warn_dave = False

# Seul l'intent 'guilds' est necessaire aux commandes slash ; pas de cache de messages.
client = BirthdayBot(intents=discord.Intents(guilds=True), max_messages=None)
tree = app_commands.CommandTree(client)

def short(r):
    when = f" — {r['jour']} {MONTHS[r['mois'] - 1]}" if r["jour"] else ""
    return display_name(r) + when

async def ac_contact(interaction: discord.Interaction, current: str):
    try:
        with db() as con:
            rows = con.execute("SELECT * FROM birthdays ORDER BY pseudo COLLATE NOCASE").fetchall()
        return [app_commands.Choice(name=short(r)[:100], value=str(r["id"]))
                for r in rows if current.lower() in short(r).lower()][:25]
    except Exception:
        return []

async def refuse(interaction, message):
    await interaction.response.send_message(message, ephemeral=True)

@tree.command(name="add-birthday", description="Ajouter un anniversaire")
@app_commands.describe(
    pseudo="Pseudo ou surnom (ex: Zouille)",
    groupe="Amis, Famille ou Special",
    jour="Jour du mois (ex: 15)",
    mois="Mois",
    annee="Année (optionnel, ex: 2000)",
    nom="Nom de famille (optionnel)",
    prenom="Prénom (optionnel)",
    description="Amis/Famille : description courte. Special : type d'évènement (ex: mariage)",
)
async def add_birthday(interaction: discord.Interaction, pseudo: str, groupe: Groupe, jour: Jour, mois: Mois,
                       annee: str = "x", nom: str = "x", prenom: str = "x", description: str = "x"):
    year, err = parse_year(annee)
    if err:
        return await refuse(interaction, err)
    month = MONTHS.index(mois) + 1
    with db() as con:
        if con.execute("SELECT 1 FROM birthdays WHERE pseudo = ? COLLATE NOCASE AND jour = ? AND mois = ?",
                       (pseudo.strip(), jour, month)).fetchone():
            return await refuse(interaction, f":warning: `{pseudo}` existe déjà à cette date. Utilise `/edit-birthday`.")
        insert(con, groupe=groupe, pseudo=txt(pseudo), nom=txt(nom), prenom=txt(prenom), jour=jour, mois=month,
               annee=year, description=txt(description), ajoute_par=interaction.user.display_name)

    emoji = ":sparkles:" if groupe == "Special" else ":white_check_mark:"
    await interaction.response.send_message(
        f"{emoji} **{pseudo}** ajouté ! Le **{jour} {mois}{f' ({year})' if year else ''}** — {groupe} "
        f"(par {interaction.user.display_name})")

@tree.command(name="edit-birthday", description="Modifier une entrée existante")
@app_commands.describe(
    contact="Contact à modifier",
    nouveau_pseudo="Nouveau pseudo",
    groupe="Nouveau groupe",
    jour="Nouveau jour",
    mois="Nouveau mois",
    annee="Nouvelle année ('x' pour effacer)",
    nom="Nouveau nom ('x' pour effacer)",
    prenom="Nouveau prénom ('x' pour effacer)",
    description="Nouvelle description ('x' pour effacer)",
)
@app_commands.autocomplete(contact=ac_contact)
async def edit_birthday(interaction: discord.Interaction, contact: str, nouveau_pseudo: Optional[str] = None,
                        groupe: Optional[Groupe] = None, jour: Optional[Jour] = None, mois: Optional[Mois] = None,
                        annee: Optional[str] = None, nom: Optional[str] = None, prenom: Optional[str] = None,
                        description: Optional[str] = None):
    changes = {}
    for field, new in (("pseudo", nouveau_pseudo), ("nom", nom), ("prenom", prenom), ("description", description)):
        if new is not None:
            changes[field] = txt(new)
    if groupe:
        changes["groupe"] = groupe
    if jour is not None:
        changes["jour"] = jour
    if mois:
        changes["mois"] = MONTHS.index(mois) + 1
    if annee is not None:
        changes["annee"], err = parse_year(annee)
        if err:
            return await refuse(interaction, err)
    if not changes:
        return await refuse(interaction, ":information_source: Aucune modification fournie.")

    with db() as con:
        row, err = resolve(con, contact)
        if err:
            return await refuse(interaction, err)
        if (changes.get("jour", row["jour"]) is None) != (changes.get("mois", row["mois"]) is None):
            return await refuse(interaction, ":x: Ce contact n'a pas de date : renseigne `jour` **et** `mois`.")
        con.execute(f"UPDATE birthdays SET {', '.join(f + ' = ?' for f in changes)} WHERE id = ?",
                    (*changes.values(), row["id"]))

    lines = []
    for field, new in changes.items():
        fmt = (lambda v: show(MONTHS[v - 1] if v else None)) if field == "mois" else show
        lines.append("description mise à jour" if field == "description"
                     else f"{field} : `{fmt(row[field])}` → `{fmt(new)}`")
    await interaction.response.send_message(
        f":pencil: **{display_name(row)}** modifié par {interaction.user.display_name} :\n"
        + "\n".join(f"• {line}" for line in lines))

@tree.command(name="list-birthdays", description="Afficher tous les anniversaires")
@app_commands.describe(groupe="Filtrer par groupe (optionnel)")
async def list_birthdays(interaction: discord.Interaction, groupe: Optional[Groupe] = None):
    with db() as con:
        rows = con.execute("SELECT * FROM birthdays WHERE jour IS NOT NULL AND (? IS NULL OR groupe = ?) "
                           "ORDER BY mois, jour, id", (groupe, groupe)).fetchall()
    if not rows:
        return await refuse(interaction, "Aucun anniversaire trouvé.")

    lines = []
    for r in rows:
        name = clean(r["pseudo"]) or clean(r["prenom"]) or "Inconnu"
        by = clean(r["ajoute_par"])
        lines.append(f"{label(r['groupe']).split()[0]} **{name}** — {r['jour']} {MONTHS[r['mois'] - 1]}"
                     + (f" ({r['annee']})" if r["annee"] else "") + (f" *— ajouté par {by}*" if by else ""))

    message = f"**Anniversaires{' — ' + groupe if groupe else ''}** ({len(lines)} contact(s))\n"
    for n, line in enumerate(lines):
        if len(message) + len(line) > 1850:  # limite Discord : 2000 caracteres
            message += f"\n*… et {len(lines) - n} autre(s). Filtre par groupe pour tout voir.*"
            break
        message += "\n" + line
    await refuse(interaction, message)

@tree.command(name="delete-birthday", description="Supprimer un anniversaire")
@app_commands.describe(contact="Contact à supprimer")
@app_commands.autocomplete(contact=ac_contact)
async def delete_birthday(interaction: discord.Interaction, contact: str):
    with db() as con:
        row, err = resolve(con, contact)
        if err:
            return await refuse(interaction, err)
        con.execute("DELETE FROM birthdays WHERE id = ?", (row["id"],))
    await interaction.response.send_message(
        f":wastebasket: **{display_name(row)}** supprimé par {interaction.user.display_name}.")

@tree.command(name="export-birthdays", description="Recevoir tous les anniversaires en fichier CSV (visible par toi seul)")
async def export_birthdays(interaction: discord.Interaction):
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(CSV_FIELDS)
    with db() as con:
        for r in con.execute("SELECT * FROM birthdays ORDER BY groupe, id").fetchall():
            r["mois"] = MONTHS[r["mois"] - 1] if r["mois"] else None
            writer.writerow([show(r[f]) for f in CSV_FIELDS])
    file = discord.File(io.BytesIO(buf.getvalue().encode("utf-8-sig")), filename="contacts_data.csv")
    await interaction.response.send_message(file=file, ephemeral=True)

###############################################################################
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("BOT_TOKEN manquant dans .env")
    client.run(TOKEN, log_handler=None)
