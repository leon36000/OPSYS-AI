"""Catalogue FERMÉ des refus des packs sectoriels (`REJ-PACK-*`) et l'erreur typée.

Un code hors de ce catalogue est une faute de programmation (`ValueError`), jamais un refus inventé à la volée. Le
détail dit quoi corriger ; `chemin` nomme le champ ou le fichier fautif. `docs/architecture/PACKS-SECTORIELS.md`
(« Refus ») suit cette liste ; `tests/test_packs_sectoriels.py` l'épingle.
"""

from __future__ import annotations

CODES_PACK: tuple[str, ...] = (
    # -- trouver et lire
    "REJ-PACK-INTROUVABLE",          # le dossier du pack (ou son manifeste) n'existe pas
    "REJ-PACK-ID-INVALIDE",          # identifiant mal formé, ou différent du nom du dossier
    "REJ-PACK-ILLISIBLE",            # YAML illisible, trop gros, clé en double, alias, racine qui n'est pas un objet
    "REJ-PACK-FICHIER-INVALIDE",     # fichier déclaré absent/hors du pack/lien symbolique, ou fichier non déclaré
    # -- schéma
    "REJ-PACK-SCHEMA",               # `schema` absent ou d'une autre version
    "REJ-PACK-CLE-INCONNUE",         # clé hors du schéma fermé
    "REJ-PACK-CHAMP-INVALIDE",       # type, longueur, format ou valeur hors du schéma
    "REJ-PACK-DOUBLON",              # code, terme, identifiant ou département déclaré deux fois
    "REJ-PACK-TERMES-ABSENTS",       # un pack sectoriel sans liste de termes (la garde n'aurait rien à garder)
    "REJ-PACK-GENERIQUE-NON-VIDE",   # un pack non sectoriel qui porte du contenu de secteur
    "REJ-PACK-BAREME-INVENTE",       # un barème « à fournir par l'entreprise » qui porte une valeur
    # -- intégrité
    "REJ-PACK-EMPREINTE-ABSENTE",    # pas de fichier d'empreinte
    "REJ-PACK-EMPREINTE",            # empreinte illisible ou différente du contenu : le pack a été modifié
    # -- résolution depuis le profil d'entreprise
    "REJ-PACK-PROFIL-INVALIDE",      # `entreprise.yaml` illisible ou clé `pack` mal formée
    "REJ-PACK-NON-INSTALLE",         # le profil nomme un pack qui n'est pas installé
    # -- rendu
    "REJ-PACK-JETON-INCONNU",        # `{{jeton}}` hors du vocabulaire du pack, ou mal formé
    "REJ-PACK-DEPARTEMENT-INCONNU",  # code de département hors M1–M10
    # -- propositions de profil (le pack propose, le propriétaire adopte)
    "REJ-PACK-PROPOSITION-INVALIDE",        # une proposition que le validateur du profil refuserait
    "REJ-PACK-PROPOSITION-VALIDEE",         # un élément proposé dont le statut n'est pas `a_valider`
    "REJ-PACK-ADOPTION-ELEMENT-INCONNU",    # élément hors de la liste fermée, ou que le pack ne propose pas
    "REJ-PACK-ADOPTION-PACK-INACTIF",       # le pack n'est pas celui que le profil a choisi
    "REJ-PACK-ADOPTION-ECRASE",             # le profil porte déjà une valeur différente : le propriétaire prime
    "REJ-PACK-ADOPTION-SANS-SIGNATURE",     # adoption sans personne qui signe
)
_CODES = frozenset(CODES_PACK)


class RefusPack(ValueError):
    """Refus typé d'un pack : `code` du catalogue, `chemin` du champ ou du fichier fautif, `detail` lisible."""

    def __init__(self, code: str, detail: str, chemin: str = "") -> None:
        if code not in _CODES:
            raise ValueError(f"code de pack hors catalogue : {code!r}")
        self.code, self.detail, self.chemin = code, detail, chemin
        super().__init__(f"{code} : {chemin + ' : ' if chemin else ''}{detail}")

    def publique(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail, "chemin": self.chemin}
