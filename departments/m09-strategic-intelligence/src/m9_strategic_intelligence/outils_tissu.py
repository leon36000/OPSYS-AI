"""Outils M9.1 : tissu de données stratégique — captures de producteurs, couverture et état « connu à… ».

Adaptateur seul (les calculs sont dans ``capture_strategique`` et ``catalogue_producteurs``, modules purs). M9 lit un
producteur UNIQUEMENT par le port privé du socle ``lecteur_producteurs_m9`` (``opsys.lecteurs_m9`` : liste blanche de
lectures T0, admin authentifié relu en base à chaque lecture) ; il n'importe aucun département, ne lit aucune table d'un
autre
et n'accepte aucune donnée d'un producteur de la part de l'appelant. Toute capture est donc une trace de ce que le
propriétaire a répondu au serveur, au moment fourni par la console (M9 n'a pas d'horloge).

Accès : admin authentifié (console ou appareil) seulement, y compris en lecture — une capture contient la réponse d'un
autre
département (finance comprise). Un agent, une identité absente ou un rôle révoqué est refusé avant toute lecture.
L'écriture
est interne (registre ``captures_strategiques``, chaîné et vérifié à chaque usage) : T1 / N2, sans effet métier.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from opsys import contexte, identite, stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import catalogue_producteurs as cat

DEPARTEMENT = "m09-strategic-intelligence"
REGISTRE = "captures_strategiques"
MAX_PAGE_OCTETS = 4000
_HORODATAGE = {
    "type": "string",
    "description": "Instant RFC 3339 à fuseau explicite fourni par l'appelant (M9 n'a pas d'horloge) : réception.",
}


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def exiger_admin_strict() -> None:
    """Admin authentifié, console ou appareil, personne active portant encore le rôle admin ; jamais un agent ni
    l'absence
    d'identité (contrairement aux anciennes lectures M9, ouvertes aux agents : ces captures copient d'autres
    départements)."""
    appelante = contexte.identite_appelante()
    cnx = stockage.connexion_courante()
    personne = (
        identite.personne_active(cnx, appelante.personne)
        if appelante is not None
        and cnx is not None
        and appelante.role == "admin"
        and appelante.source in {"console", "appareil"}
        else None
    )
    if personne is None or "admin" not in personne.roles:
        raise _refus(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            "lecture réservée à l'admin authentifié (personne active portant encore le rôle admin)",
        )


def borner(resultat: dict, budget: int) -> dict:
    taille = len(json.dumps(resultat, ensure_ascii=False, allow_nan=False))
    if taille > budget:
        raise _refus("REJ-TISSU-BORNE", f"réponse de {taille} caractères au-delà de {budget} ; réduire la fenêtre")
    return resultat


def resume(capture: Mapping) -> dict:
    return {
        "index": capture["index"],
        "hash_maillon": capture["hash_maillon"],
        "lecture_id": capture["lecture_id"],
        "departement": capture["departement"],
        "verdict": capture["verdict"],
        "code": capture["code"],
        "complete": capture["complete"],
        "raison_incomplete": capture["raison_incomplete"],
        "recu_a": capture["recu_a"],
        "reference": capture["reference"],
        "instants_metier": capture["instants_metier"],
        "revisions": capture["revisions"],
        "pages": len(capture["pages"]),
        "arguments_sha256": capture["arguments_sha256"],
        "reponse_sha256": capture["reponse_sha256"],
    }


def construire_outils(
    *,
    lecteur: Callable[..., dict[str, Any]] | None,
    budget_sortie: int,
    captures_cible: Any = None,
) -> tuple[Outil, ...]:
    """``captures_cible`` : ``None`` adosse le registre au stockage durable ; une liste (tests) reste en mémoire."""

    def registre() -> Any:
        return captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE)

    def chaine_verifiee() -> list[dict]:
        chaine = list(registre())
        ok, raison = cs.valider_chaine(chaine)
        if not ok:
            raise _refus("REJ-CAPTURE-CHAINE-INVALIDE", f"registre des captures invalide, aucune lecture ({raison})")
        return chaine

    def capturer_producteur(lecture_id: str, arguments: dict[str, Any], horodatage: str) -> dict[str, Any]:
        exiger_admin_strict()
        lecture = cat.obtenir(lecture_id)
        finaux = cat.arguments_admis(lecture, arguments)
        if lecteur is None:
            raise _refus("REJ-CAPTURE-INDISPONIBLE", "port de lecture des producteurs non fourni à ce département")
        chaine = chaine_verifiee()
        pages: list[dict] = []
        courants = dict(finaux)
        for _ in range(cs.MAX_PAGES):
            reponse = lecteur(lecture.departement, lecture.outil, courants)
            pages.append(reponse)
            if lecture.pagination is None or cs.verdict_reponse(reponse)[0] != "ACCEPTEE":
                break
            suivants = [v for v in cs.extraire(reponse, lecture.pagination.chemin_suivant) if v is not None]
            if not suivants or suivants[0] == courants.get(lecture.pagination.arg_depart):
                break  # pas de suite, ou aucun progrès : la capture dira PARTIELLE si une suite reste déclarée
            courants = {**courants, lecture.pagination.arg_depart: suivants[0]}
        index = len(chaine)
        capture = cs.construire(
            lecture,
            finaux,
            pages,
            recu_a=horodatage,
            reference=finaux.get(lecture.reference) if lecture.reference else None,
            index=index,
            hash_precedent=chaine[-1]["hash_maillon"] if chaine else cs.HASH_INITIAL,
            dernier_recu_a=chaine[-1]["recu_a"] if chaine else None,
        )
        registre().append(capture, rang_attendu=index)
        return borner({"accepte": True, "capture": resume(capture)}, budget_sortie)

    def lister_captures(depart: int = 0, lecture_id: str | None = None, vue: str | None = None) -> dict[str, Any]:
        exiger_admin_strict()
        if lecture_id is not None:
            cat.obtenir(lecture_id)
        chaine = chaine_verifiee()
        tete = chaine[-1]["hash_maillon"] if chaine else cs.HASH_INITIAL
        if vue is not None and vue != tete:
            raise _refus("REJ-VUE-PERIMEE", "le registre a changé depuis la première page : reprendre à 0")
        retenues = [c for c in reversed(chaine) if lecture_id is None or c["lecture_id"] == lecture_id]
        if type(depart) is not int or not 0 <= depart <= len(retenues):
            raise _refus("REJ-TISSU-DEPART", "départ entier entre 0 et le total requis ; reprendre à 0")
        page: list[dict] = []
        for capture in retenues[depart:]:
            essai = [*page, resume(capture)]
            if len(json.dumps(essai, ensure_ascii=False)) > budget_sortie - 700:
                break
            page = essai
        if retenues[depart:] and not page:
            raise _refus("REJ-TISSU-BORNE", "un résumé de capture dépasse la borne")
        suivant = depart + len(page)
        return {
            "accepte": True,
            "type": "CAPTURES_STRATEGIQUES",
            "captures": page,
            "total": len(retenues),
            "depart": depart,
            "prochain_depart": suivant if suivant < len(retenues) else None,
            "vue": tete,
            "ordre": "la plus récente d'abord (rang de chaîne décroissant)",
        }

    def lire_capture(index: int, page: int = 0, depart: int = 0, longueur: int = MAX_PAGE_OCTETS) -> dict[str, Any]:
        exiger_admin_strict()
        chaine = chaine_verifiee()
        if type(index) is not int or not 0 <= index < len(chaine):
            raise _refus("REJ-TISSU-INDEX", "rang de capture inconnu")
        capture = chaine[index]
        if type(page) is not int or not 0 <= page < len(capture["pages"]):
            raise _refus("REJ-TISSU-INDEX", "page inconnue")
        if type(depart) is not int or depart < 0 or type(longueur) is not int or not 1 <= longueur <= MAX_PAGE_OCTETS:
            raise _refus("REJ-TISSU-DEPART", "départ et longueur bornés requis")
        texte = cs.canonique(capture["pages"][page])
        if depart > len(texte):
            raise _refus("REJ-TISSU-DEPART", "départ au-delà de la page")
        fin = min(len(texte), depart + longueur)
        return {
            "accepte": True,
            "type": "CAPTURE_STRATEGIQUE",
            "capture": resume(capture),
            "page": page,
            "taille_page": len(texte),
            "depart": depart,
            "contenu_json": texte[depart:fin],
            "prochain_depart": fin if fin < len(texte) else None,
            "arguments": capture["arguments"],
        }

    def couverture(
        reference: str,
        connaissance: str | None = None,
        attendues: list[str] | None = None,
        perime_apres_jours: int | None = None,
    ) -> dict[str, Any]:
        exiger_admin_strict()
        if perime_apres_jours is not None and (
            type(perime_apres_jours) is not int or not 1 <= perime_apres_jours <= 3650
        ):
            raise _refus("REJ-TISSU-ARGUMENT", "perime_apres_jours : entier de 1 à 3650, ou absent")
        chaine = chaine_verifiee()
        liste = list(attendues) if attendues is not None else [lecture.id for lecture in cat.LECTURES]
        for lecture_id in liste:
            cat.obtenir(lecture_id)
        if len(set(liste)) != len(liste):
            raise _refus("REJ-TISSU-ARGUMENT", "lectures attendues distinctes requises")
        fraicheurs = None if perime_apres_jours is None else {lecture: perime_apres_jours * 86400 for lecture in liste}
        resultat = cs.evaluer_couverture(
            chaine,
            reference=reference,
            connaissance=connaissance or reference,
            attendues=liste,
            fraicheur_attendue_s=fraicheurs,
        )
        resultat["catalogue_version"] = cat.CATALOGUE_VERSION
        resultat["tete_registre"] = chaine[-1]["hash_maillon"] if chaine else cs.HASH_INITIAL
        return borner({"accepte": True, **resultat}, budget_sortie)

    def verifier_captures() -> dict[str, Any]:
        exiger_admin_strict()
        chaine = list(registre())
        ok, raison = cs.valider_chaine(chaine)
        return {
            "accepte": True,
            "valide": ok,
            "raison": raison,
            "total": len(chaine),
            "tete": chaine[-1]["hash_maillon"] if chaine and ok else cs.HASH_INITIAL,
        }

    schema_objet = {"type": "object"}
    return (
        Outil(
            nom="m9_capturer_producteur",
            description=(
                "Lit, par le port serveur des producteurs, une lecture du catalogue M9 (M1–M8, M10) et en conserve la "
                "réponse dans un registre chaîné, avec quatre temps distincts (instant métier déclaré, référence, "
                "réception "
                "fournie, âge informatif). Refus et pages non lues sont conservés comme manques. Aucune donnée d'un "
                "producteur n'est acceptée de l'appelant ; admin authentifié seulement."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "lecture_id": {"type": "string", "minLength": 1, "maxLength": 64},
                    "arguments": schema_objet,
                    "horodatage": _HORODATAGE,
                },
                "required": ["lecture_id", "arguments", "horodatage"],
                "additionalProperties": False,
            },
            fonction=capturer_producteur,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_lister_captures",
            description=(
                "Liste par pages bornées les captures stratégiques (la plus récente d'abord), avec la vue du "
                "registre : une "
                "reprise avec une vue périmée est refusée. Admin authentifié seulement."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "depart": {"type": "integer", "minimum": 0},
                    "lecture_id": {"type": "string", "maxLength": 64},
                    "vue": {"type": "string", "maxLength": 64},
                },
                "additionalProperties": False,
            },
            fonction=lister_captures,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_lire_capture",
            description=(
                "Relit une capture et, par tranches de 4 000 caractères au plus, le JSON canonique exact d'une page "
                "de la "
                "réponse du producteur (aucune troncature : suivre prochain_depart). Admin authentifié seulement."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "minimum": 0},
                    "page": {"type": "integer", "minimum": 0},
                    "depart": {"type": "integer", "minimum": 0},
                    "longueur": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_OCTETS},
                },
                "required": ["index"],
                "additionalProperties": False,
            },
            fonction=lire_capture,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_couverture_strategique",
            description=(
                "Évalue la couverture des lectures attendues à une référence, avec ce que M9 connaissait à l'instant "
                "de "
                "connaissance : ABSENTE, REFUSEE, PARTIELLE, CONTRADICTOIRE, TEMPS_METIER_NON_DECLARE, FUTURE ou "
                "PRESENTE. "
                "L'âge est un écart signé, jamais un SLA ; la fraîcheur reste NON_EVALUEE sans attente du propriétaire."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "reference": {"type": "string", "description": "Instant RFC 3339 à fuseau explicite."},
                    "connaissance": {"type": "string", "description": "Instant RFC 3339 ; défaut : la référence."},
                    "attendues": {
                        "type": "array",
                        "items": {"type": "string", "maxLength": 64},
                        "maxItems": 64,
                        "uniqueItems": True,
                    },
                    "perime_apres_jours": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 3650,
                        "description": "Péremption demandée : sans elle, la fraîcheur reste NON_EVALUEE.",
                    },
                },
                "required": ["reference"],
                "additionalProperties": False,
            },
            fonction=couverture,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m9_verifier_captures",
            description="Vérifie la chaîne des captures (rangs, empreintes, réception monotone) sans rien écrire.",
            parametres={"type": "object", "properties": {}, "additionalProperties": False},
            fonction=verifier_captures,
            roles_appareil=frozenset({"admin"}),
        ),
    )
