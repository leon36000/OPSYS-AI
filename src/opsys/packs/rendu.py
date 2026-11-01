"""Rendre le texte EFFECTIF d'un agent : le texte du cœur, ses jetons résolus par le pack actif, et le bloc sectoriel.

Le cœur (`SOUL.md`, skills) ne nomme aucun secteur. Là où un texte avait besoin du secteur de l'entreprise, il porte
un jeton `{{qualificatif_secteur}}` ou `{{secteur}}`, résolu ici par le vocabulaire du pack actif :

    « Tu es la réceptionniste de première ligne d'une entreprise {{qualificatif_secteur}} au Québec. »
    pack sectoriel  → « … d'une entreprise de <secteur du pack> au Québec. »   (le texte d'avant, mot pour mot)
    pack générique  → « … d'une entreprise au Québec. »                         (l'espace du jeton disparaît)

Un jeton inconnu, ou une accolade double qui reste après le rendu, est un refus typé (`REJ-PACK-JETON-INCONNU`) :
jamais un `{{…}}` laissé dans un prompt.

Le bloc sectoriel est ajouté APRÈS le texte du cœur, par département, avec l'identité du pack (id, version, empreinte) :
un lecteur sait de quel pack viennent ces lignes, et un changement de pack est visible dans le prompt.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .codes import RefusPack
from .manifeste import DEPARTEMENTS, JETONS_VOCABULAIRE, Pack

_JETON = re.compile(r"( ?)\{\{([A-Za-z_]+)\}\}")


def rendre_jetons(texte: str, pack: Pack) -> str:
    """Résout les jetons de `texte` par le vocabulaire du `pack` ; l'espace avant un jeton vide disparaît avec lui."""
    def remplacer(m: re.Match[str]) -> str:
        nom = m.group(2)
        if nom not in JETONS_VOCABULAIRE:
            raise RefusPack("REJ-PACK-JETON-INCONNU",
                            f"jeton {{{{{nom}}}}} inconnu (jetons du cœur : {list(JETONS_VOCABULAIRE)})")
        valeur = pack.vocabulaire[nom]
        return f"{m.group(1)}{valeur}" if valeur else ""

    rendu = _JETON.sub(remplacer, texte)
    if "{{" in rendu or "}}" in rendu:
        raise RefusPack("REJ-PACK-JETON-INCONNU", "accolade double restante après le rendu : jeton mal formé")
    return rendu


def cle_departement(code: str) -> str:
    """`M1` → `m01`, `M10` → `m10` ; `REJ-PACK-DEPARTEMENT-INCONNU` hors M1–M10."""
    m = re.fullmatch(r"[Mm](\d{1,2})", code or "")
    cle = f"m{int(m.group(1)):02d}" if m else ""
    if cle not in DEPARTEMENTS:
        raise RefusPack("REJ-PACK-DEPARTEMENT-INCONNU", f"département {code!r} hors M1–M10")
    return cle


def _entete(pack: Pack) -> str:
    return f"## Contexte sectoriel — {pack.nom} (pack `{pack.id}` v{pack.version}, {pack.empreinte[:19]})"


def lignes_services(pack: Pack) -> list[str]:
    return [f"- `{s.code}` — {s.libelle}" + (f" (mots-clés : {', '.join(s.mots_cles)})" if s.mots_cles else "")
            for s in pack.services]


def lignes_glossaire(pack: Pack) -> list[str]:
    return [f"- **{t.terme}** : {t.definition}" for t in pack.glossaire]


def lignes_appellations(pack: Pack) -> list[str]:
    return [f"- {cle} : {valeur}" for cle, valeur in pack.appellations.items()]


def lignes_baremes(pack: Pack) -> list[str]:
    lignes = []
    for b in pack.baremes:
        if b.statut == "a_fournir_par_entreprise":
            lignes.append(f"- {b.libelle} ({b.unite}) : à fournir par l'entreprise — {b.ou_fournir} ; "
                          "aucune valeur n'est supposée")
        else:
            lignes.append(f"- {b.libelle} ({b.unite}) : {b.valeur}, exemple fictif non contractuel, jamais un prix")
    return lignes


def bloc_sectoriel(pack: Pack, code_departement: str) -> str:
    """Le bloc ajouté au prompt du département. Pack générique : une seule consigne, aucun secteur n'est supposé."""
    cle = cle_departement(code_departement)
    if pack.generique:
        return (f"{_entete(pack)}\n\nAucun secteur d'activité n'est déclaré pour cette entreprise : ne suppose aucun "
                "type de travaux, aucun produit et aucun barème. Le vocabulaire du métier vient du profil de "
                "l'entreprise et de ce que l'humain te dit ; ce qui manque, tu le demandes.")
    bloc = pack.blocs[cle]
    sections = {
        "services": ("Services de référence :", lignes_services),
        "glossaire": ("Vocabulaire du métier :", lignes_glossaire),
        "baremes": ("Barèmes et paramètres :", lignes_baremes),
        "appellations": ("Appellations :", lignes_appellations),
    }
    morceaux = [_entete(pack), f"Secteur : {pack.vocabulaire['secteur']}.\n\n{bloc.ligne}"]
    for section in bloc.inclure:
        titre, fabrique = sections[section]
        lignes = fabrique(pack)
        if lignes:
            morceaux.append(titre + "\n" + "\n".join(lignes))
    return "\n\n".join(morceaux)


def soul_effectif(soul_brut: str, pack: Pack, code_departement: str) -> str:
    """`SOUL.md` du cœur, jetons résolus, suivi du bloc sectoriel du département (sans les capacités)."""
    return f"{rendre_jetons(soul_brut.rstrip(), pack)}\n\n{bloc_sectoriel(pack, code_departement)}"


def copier_skill(source: Path, destination: Path, pack: Pack) -> None:
    """Copie un dossier de skill ; les fichiers Markdown qui portent des jetons sont rendus par le pack."""
    shutil.copytree(source, destination, dirs_exist_ok=True)
    for fichier in sorted(destination.rglob("*.md")):
        texte = fichier.read_text(encoding="utf-8")
        if "{{" in texte:
            fichier.write_text(rendre_jetons(texte, pack), encoding="utf-8")
