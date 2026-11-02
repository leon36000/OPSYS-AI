"""Réserves d'une fin de chantier dont la preuve est incomplète (P4-07, DEFINITION-PRODUIT §6).

Module pur (stdlib ; aucun import ``opsys``, aucune horloge, aucun aléa, aucun réseau ; un test le vérifie par analyse
du
code). DEFINITION-PRODUIT §6 : « s'il manque quelque chose [...] le statut devient ``completed_pending_review``, pas
``completed_verified`` ». Avant, ``m4_completer_intervention`` REFUSAIT toute preuve incomplète : l'employé qui ne
peut pas
obtenir la signature du client, ou dont une photo n'a pas pu être téléversée, ne pouvait pas terminer. Il peut
maintenant
terminer AVEC RÉSERVES : il NOMME ce qui manque (code fermé ci-dessous), la fin de chantier est enregistrée en
``completed_pending_review`` avec ces réserves, et une PERSONNE les accepte (ou les corrige) à la revue.

Ce qui n'a pas changé : une preuve FAUSSE reste refusée (une référence de photo ou de signature qui ne désigne aucun
fichier déposé et complet, une structure invalide) ; une preuve incomplète SANS réserve nommée est refusée, comme
avant ;
une réserve qui ne correspond à aucun manque réel (la liste de contrôle est complète, mais l'employé déclare qu'elle ne
l'est pas) est refusée aussi : une réserve n'est pas un passe-droit.

Chaque réserve appartient à UNE catégorie (``CATEGORIES``), la dimension de la preuve qui est incomplète. La catégorie
sert à la revue (ce qu'il faut regarder) et à la cascade (une réserve de matériel rend le coût réel provisoire) ; elle
ne
se déduit jamais du texte d'un code.
"""

from __future__ import annotations

from . import verdicts

CAT_LISTE_CONTROLE = "liste_controle"
CAT_PREUVE_PHOTO = "preuve_photo"
CAT_SIGNATURE = "signature"
CAT_MATERIEL = "materiel"
CATEGORIES = (CAT_LISTE_CONTROLE, CAT_PREUVE_PHOTO, CAT_SIGNATURE, CAT_MATERIEL)

LISTE_CONTROLE_INCOMPLETE = "liste_controle_incomplete"
PHOTOS_APRES_MANQUANTES = "photos_apres_manquantes"
PHOTO_EN_ECHEC = "photo_en_echec"
SIGNATURE_IMPOSSIBLE = "signature_impossible"
MATERIEL_ECARTE_NON_DOCUMENTE = "materiel_ecarte_non_documente"

# code -> (catégorie, libellé en français québécois)
RESERVES = {
    LISTE_CONTROLE_INCOMPLETE: (CAT_LISTE_CONTROLE, "liste de contrôle non terminée"),
    PHOTOS_APRES_MANQUANTES: (CAT_PREUVE_PHOTO, "aucune photo après chantier"),
    PHOTO_EN_ECHEC: (CAT_PREUVE_PHOTO, "photo prise, mais le téléversement a échoué"),
    SIGNATURE_IMPOSSIBLE: (CAT_SIGNATURE, "signature du client impossible à obtenir"),
    MATERIEL_ECARTE_NON_DOCUMENTE: (CAT_MATERIEL, "matériel écarté ou perdu non documenté"),
}
CODES = tuple(sorted(RESERVES))
MAX_RESERVES = len(RESERVES)

# Catégories dont une réserve rend le COÛT RÉEL provisoire après la revue : la variance de matériaux de M6 ne couvre pas
# ce que l'employé n'a pas documenté.
CATEGORIES_COUT_PROVISOIRE = (CAT_MATERIEL,)

VERSION_SCHEMA = 1
CLES_BLOC = ("version_schema", "reserves")

__all__ = [
    "CATEGORIES", "CODES", "RESERVES", "CATEGORIES_COUT_PROVISOIRE", "VERSION_SCHEMA", "CLES_BLOC", "MAX_RESERVES",
    "LISTE_CONTROLE_INCOMPLETE", "PHOTOS_APRES_MANQUANTES", "PHOTO_EN_ECHEC", "SIGNATURE_IMPOSSIBLE",
    "MATERIEL_ECARTE_NON_DOCUMENTE", "categorie", "normaliser", "bloc", "codes_du_bloc", "par_categorie",
    "cout_provisoire", "libelles",
]


def categorie(code):
    """Catégorie d'une réserve (``KeyError`` pour un code inconnu : un défaut de programmation, jamais une donnée)."""
    return RESERVES[code][0]


def normaliser(reserves):
    """``(codes triés, None)`` ou ``(None, verdict)`` : la déclaration d'un employé, validée. Une liste de codes fermés,
    sans doublon ; vide ou absente : aucune réserve. Aucun texte libre n'est jamais accepté ici."""
    if reserves is None:
        return (), None
    if not isinstance(reserves, (list, tuple)):
        return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE", detail="reserves doit être une liste de codes")
    for code in reserves:
        if not isinstance(code, str) or code not in RESERVES:
            return None, verdicts.construire_verdict(
                "REJ-ENUM-INVALIDE", detail=f"reserves : code inconnu {code!r} (attendu : {', '.join(CODES)})",
            )
    if len(set(reserves)) != len(reserves):
        return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE", detail="reserves : code en double")
    return tuple(sorted(reserves)), None


def bloc(codes):
    """Le bloc que le maillon de complétion garde (et qui entre dans son empreinte) ; ``None`` sans réserve."""
    if not codes:
        return None
    return {"version_schema": VERSION_SCHEMA, "reserves": list(codes)}


def codes_du_bloc(valeur):
    """``(codes, True)`` si le bloc lu au registre est valide (clés exactes, codes fermés, triés, sans doublon),
    ``((), False)`` sinon. ``valeur`` absent (``None``) : ``((), True)``."""
    if valeur is None:
        return (), True
    if (
        type(valeur) is not dict or set(valeur) != set(CLES_BLOC) or type(valeur["version_schema"]) is not int
        or valeur["version_schema"] != VERSION_SCHEMA or type(valeur["reserves"]) is not list or not valeur["reserves"]
    ):
        return (), False
    codes, verdict = normaliser(valeur["reserves"])
    if verdict is not None or list(codes) != valeur["reserves"]:
        return (), False
    return codes, True


def par_categorie(codes):
    """``{catégorie: [codes]}`` pour les catégories touchées, dans l'ordre fixe de ``CATEGORIES``."""
    resultat = {}
    for cat in CATEGORIES:
        dans_la_categorie = [code for code in codes if categorie(code) == cat]
        if dans_la_categorie:
            resultat[cat] = dans_la_categorie
    return resultat


def cout_provisoire(codes):
    """Vrai si une réserve de la liste rend le coût réel provisoire (catégorie de ``CATEGORIES_COUT_PROVISOIRE``)."""
    return any(categorie(code) in CATEGORIES_COUT_PROVISOIRE for code in codes)


def libelles(codes):
    """Phrase lisible des réserves, regroupées par catégorie (pour la file de revue)."""
    morceaux = []
    for cat, dans in par_categorie(codes).items():
        morceaux.append(f"{cat} ({', '.join(RESERVES[code][1] for code in dans)})")
    return " ; ".join(morceaux)
