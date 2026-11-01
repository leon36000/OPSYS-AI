"""Outils d'Athéna : tableau de direction, ce qui exige la direction, ce qui a changé depuis hier, briefing enrichi.

Adaptateur seul : les règles vivent dans les modules purs ``tableau_direction``, ``priorites_direction``,
``changements_depuis`` et ``certitude``. Ces outils LISENT les captures déjà conservées (registre chaîné et vérifié à
chaque usage) et la file du propriétaire ; seul ``m9_rafraichir_lectures_direction`` écrit (des captures : tâche interne
N2, mêmes refus que ``m9_capturer_producteur``).

Droits : admin authentifié seulement (``exiger_admin_strict``), comme tout outil ``outils_*`` ; AUCUN rôle d'appareil
n'est déclaré (``roles_appareil`` vide) : ces outils n'élargissent aucun droit de téléphone. M9 ne décide, n'approuve et
n'exécute rien ici.

Bornes : le socle tronque toute sortie à 6 000 caractères ; chaque réponse est bornée PAR LE CODE (pages, ``depart``),
jamais coupée en silence.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import (
    briefing_matin,
    changements_depuis,
    dossier_strategique,
    outils_tissu,
    priorites_direction,
    recommandation_gouvernee,
    tableau_direction,
)
from . import capture_strategique as cs
from . import catalogue_producteurs as cat
from . import certitude as ct
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_CAPTURES = "captures_strategiques"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}
_DEPART = {"type": "integer", "minimum": 0, "description": "Rang du premier élément ; reprendre à prochain_depart."}
MAX_MESSAGE_SOMMAIRE = 240
SECTIONS_DETAIL = tableau_direction.SECTIONS


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _page(elements: list, depart: int, budget: int, enveloppe: Callable[[list, int | None], dict]) -> dict:
    """Autant d'éléments que la borne en laisse tenir ; ``prochain_depart`` dit où reprendre (jamais une coupure
    muette)."""
    if type(depart) is not int or not 0 <= depart <= len(elements):
        raise _refus("REJ-TISSU-DEPART", "départ entre 0 et le total requis ; reprendre à 0")
    page: list = []
    for element in elements[depart:]:
        essai = [*page, element]
        suivant = depart + len(essai)
        if len(json.dumps(enveloppe(essai, suivant if suivant < len(elements) else None), ensure_ascii=False)) > budget:
            break
        page = essai
    if elements[depart:] and not page:
        raise _refus("REJ-TISSU-BORNE", "un élément dépasse la borne de sortie")
    suivant = depart + len(page)
    return enveloppe(page, suivant if suivant < len(elements) else None)


def construire_outils(
    *,
    budget_sortie: int,
    sources_briefing: Callable[[], tuple[list[dict], list[dict], list[dict]]],
    fenetre_alertes_jours: Callable[[], int],
    lecteur: Callable[..., dict[str, Any]] | None = None,
    captures_cible: Any = None,
) -> tuple[Outil, ...]:
    def registre() -> Any:
        return captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)

    def captures() -> list[dict]:
        chaine = list(registre())
        ok, raison = cs.valider_chaine(chaine)
        if not ok:
            raise _refus("REJ-CAPTURE-CHAINE-INVALIDE", f"registre des captures invalide ({raison})")
        return chaine

    def alertes_de_la_fenetre(maintenant: str, alertes: list[dict]) -> list[dict]:
        jour = briefing_matin._jour_de(maintenant)
        debut = jour.fromordinal(jour.toordinal() - fenetre_alertes_jours())
        resultat = []
        for alerte in alertes:
            if "horodatage_reference" not in alerte or "metric_id" not in alerte or "evenement_id" not in alerte:
                raise _refus("REJ-TABLEAU-ALERTE", "alerte reçue sans les champs du catalogue")
            if debut <= briefing_matin._jour_de(alerte["horodatage_reference"]) <= jour:
                resultat.append(alerte)
        return resultat

    def composer(maintenant: str, perime_apres_jours: int | None = None) -> dict:
        if perime_apres_jours is not None and (
            type(perime_apres_jours) is not int or not 0 <= perime_apres_jours <= 3650
        ):
            raise _refus("REJ-TABLEAU-PEREMPTION", "perime_apres_jours : entier de 0 à 3650, ou absent")
        _, alertes, _ = sources_briefing()
        return tableau_direction.composer(
            captures(),
            maintenant=maintenant,
            alertes_m8=alertes_de_la_fenetre(maintenant, alertes),
            perime_apres_jours=perime_apres_jours,
        )

    def resume_section(section: dict) -> dict:
        return {
            "id": section["id"],
            "titre": section["titre"],
            "certitude": section["certitude"],
            "certain": section["certain"],
            "message": section["message"][:MAX_MESSAGE_SOMMAIRE],
        }

    # ---------------------------------------------------------------------------------------- tableau
    def tableau(
        maintenant: str, section: str | None = None, depart: int = 0, perime_apres_jours: int | None = None
    ) -> dict[str, Any]:
        exiger_admin_strict()
        vue = composer(maintenant, perime_apres_jours)
        if section is None:
            return borner(
                {
                    "accepte": True,
                    "type": "TABLEAU_DIRECTION_SOMMAIRE",
                    "maintenant": maintenant,
                    "tableau_id": vue["tableau_id"],
                    "sections": [resume_section(vue["sections"][s]) for s in tableau_direction.SECTIONS],
                    "declarations_attendues": vue["declarations_attendues"][:6],
                    "lire_le_detail": "m9_tableau_direction avec section=<id> (puis depart)",
                    "limites": vue["limites"],
                },
                budget_sortie,
            )
        if section not in SECTIONS_DETAIL:
            raise _refus("REJ-TABLEAU-SECTION", f"section parmi {list(SECTIONS_DETAIL)}")
        bloc = vue["sections"][section]
        lignes = bloc["lignes"]

        def enveloppe(page: list, suivant: int | None) -> dict:
            return {
                "accepte": True,
                "type": "TABLEAU_DIRECTION_SECTION",
                "maintenant": maintenant,
                "tableau_id": vue["tableau_id"],
                "section": {**{k: v for k, v in bloc.items() if k != "lignes"}, "lignes": page},
                "total_lignes": len(lignes),
                "depart": depart,
                "prochain_depart": suivant,
            }

        return _page(lignes, depart, budget_sortie, enveloppe)

    # ---------------------------------------------------------------------------------------- exige la direction
    def exige_la_direction(maintenant: str, depart: int = 0) -> dict[str, Any]:
        exiger_admin_strict()
        decisions, _, _ = sources_briefing()
        classement = priorites_direction.hierarchiser(decisions, maintenant=maintenant)
        declarations = composer(maintenant)["declarations_attendues"]
        elements = classement["elements"]

        def enveloppe(page: list, suivant: int | None) -> dict:
            return {
                "accepte": True,
                "type": "EXIGE_LA_DIRECTION",
                "maintenant": maintenant,
                "regle": classement["regle"],
                "total": classement["total"],
                "par_niveau": classement["par_niveau"],
                "elements": page,
                "depart": depart,
                "prochain_depart": suivant,
                "declarations_attendues": declarations[:6],
                "limites": classement["limites"],
            }

        return _page(elements, depart, budget_sortie, enveloppe)

    # ---------------------------------------------------------------------------------------- changements
    def changements(
        maintenant: str, depuis: str | None = None, duree_s: int = changements_depuis.DUREE_DEFAUT_S, depart: int = 0
    ) -> dict[str, Any]:
        exiger_admin_strict()
        resultat = changements_depuis.comparer(captures(), maintenant=maintenant, depuis=depuis, duree_s=duree_s)
        lignes = resultat["changements"]

        def enveloppe(page: list, suivant: int | None) -> dict:
            return {
                "accepte": True,
                **{k: v for k, v in resultat.items() if k not in ("changements", "limites")},
                "changements": page,
                "depart": depart,
                "prochain_depart": suivant,
                "limites": resultat["limites"],
            }

        return _page(lignes, depart, budget_sortie, enveloppe)

    def verifier_recu(recu: dict) -> dict[str, Any]:
        exiger_admin_strict()
        return {"accepte": True, **changements_depuis.verifier_recu(captures(), recu)}

    # ---------------------------------------------------------------------------------------- briefing enrichi
    def briefing_direction(maintenant: str) -> dict[str, Any]:
        exiger_admin_strict()
        decisions, alertes, faits = sources_briefing()
        vue = composer(maintenant)
        classement = priorites_direction.hierarchiser(decisions, maintenant=maintenant)
        delta = changements_depuis.comparer(captures(), maintenant=maintenant)
        classique = briefing_matin._preparer(maintenant, decisions, alertes, faits, fenetre_alertes_jours())
        premiers = [
            {k: e[k] for k in ("rang", "id", "departement", "niveau", "age_texte")} for e in classement["elements"][:5]
        ]
        changees = [
            c["lecture_id"]
            for c in delta["changements"]
            if c["nature"] not in ("MEME_ETAT", "AUCUN_CHANGEMENT_DE_FAIT")
        ]
        return borner(
            {
                "accepte": True,
                "type": "BRIEFING_DIRECTION",
                "maintenant": maintenant,
                "sante": resume_section(vue["sections"]["sante"]),
                "sections": [resume_section(vue["sections"][s]) for s in tableau_direction.SECTIONS if s != "sante"],
                "exige_la_direction": {
                    "total": classement["total"],
                    "par_niveau": classement["par_niveau"],
                    "premiers": premiers,
                    "regle": classement["regle"],
                    "lire_la_suite": "m9_exige_la_direction",
                },
                "declarations_attendues": vue["declarations_attendues"][:4],
                "changements_depuis_hier": {
                    "depuis": delta["depuis"],
                    "lectures_changees": delta["lectures_changees"],
                    "lectures": changees[:10],
                    "recu": delta["recu"]["empreinte"],
                    "lire_le_detail": "m9_changements_depuis",
                },
                "briefing_du_matin": {
                    "decisions_en_attente": len(classique["listes"]["decisions_en_attente"]),
                    "alertes_m8": len(classique["listes"]["alertes_m8"]),
                    "faits_veille": len(classique["listes"]["faits_veille"]),
                    "manques": len(classique["manques"]),
                    "lire_le_detail": "m9_produire_briefing_matin",
                },
                "tableau_id": vue["tableau_id"],
                "limites": vue["limites"][:1] + ["Détail : m9_tableau_direction."],
            },
            budget_sortie,
        )

    # ---------------------------------------------------------------------------------------- rafraîchissement
    def rafraichir(
        maintenant: str,
        jour: str | None = None,
        debut_semaine: str | None = None,
        prevision: dict | None = None,
    ) -> dict[str, Any]:
        exiger_admin_strict()
        instant = cs.instant(maintenant)
        if instant is None:
            raise _refus("REJ-CAPTURE-TEMPS", "instant de réception avec fuseau explicite requis")
        jour_utilise = jour if jour is not None else briefing_matin._jour_de(maintenant).isoformat()
        plan = tableau_direction.plan_de_lectures(
            maintenant, jour_utilise, debut_semaine=debut_semaine, prevision=prevision
        )
        resultats = []
        for demande in plan:
            capture = outils_tissu.capturer_lecture(
                lecteur, registre(), captures, demande["lecture_id"], demande["arguments"], maintenant
            )
            resultats.append(
                {
                    "lecture_id": capture["lecture_id"],
                    "index": capture["index"],
                    "verdict": capture["verdict"],
                    "code": capture["code"],
                    "complete": capture["complete"],
                    "raison_incomplete": (capture["raison_incomplete"] or "")[:200] or None,
                }
            )
        non_demandees = [] if debut_semaine is not None else ["m4.capacite_equipe : debut_semaine non fourni"]
        return borner(
            {
                "accepte": True,
                "type": "RAFRAICHISSEMENT_LECTURES_DIRECTION",
                "maintenant": maintenant,
                "jour": jour_utilise,
                "lectures": resultats,
                "non_demandees": non_demandees,
                "catalogue_version": cat.CATALOGUE_VERSION,
                "regle": "Un refus ou une page non lue est conservé comme manque ; rien n'est rempli par défaut.",
            },
            budget_sortie,
        )

    # ---------------------------------------------------------------------------------------- recommandation
    def controler_recommandation(recommandation: dict, connaissance: str, recus: list | None = None) -> dict[str, Any]:
        """Contrôle (sans rien écrire) une recommandation face aux faits que M9 connaissait à `connaissance`."""
        exiger_admin_strict()
        if cs.instant(connaissance) is None:
            raise _refus("REJ-CAPTURE-TEMPS", "instant de connaissance avec fuseau explicite requis")
        recus = recus if recus is not None else []
        if type(recus) is not list or len(recus) > 16 or not all(isinstance(r, dict) for r in recus):
            raise _refus("REJ-RECO-FORME", "recus : 16 reçus objets au plus")
        chaine = captures()
        dossier = dossier_strategique.construire(
            chaine, question="contrôle d'une recommandation", domaines=["strategie"], reference=connaissance,
            connaissance=connaissance, max_faits=10**6,
        )  # fmt: skip
        utilises = {(u["index"], u["hash_maillon"]) for u in dossier["captures_utilisees"]}
        utiles = [c for c in cs.connues_a(chaine, connaissance) if (c["index"], c["hash_maillon"]) in utilises]
        certitudes = ct.certitude_des_faits(utiles)
        from opsys import recu_calcul_pont

        par_empreinte = {r.get("empreinte"): r for r in recus if isinstance(r.get("empreinte"), str)}
        resultat = recommandation_gouvernee.controler(
            recommandation, faits=dossier["faits"], certitudes=certitudes, recus=par_empreinte,
            verifier_recu=recu_calcul_pont.verifier,
        )  # fmt: skip
        return borner({"accepte": True, **resultat, "connaissance": connaissance}, budget_sortie)

    def outil(nom, description, proprietes, requis, fonction, *, ecriture=False):
        return Outil(
            nom=nom,
            description=description,
            parametres={"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False},
            fonction=fonction,
            autonomie=Autonomie.T1 if ecriture else Autonomie.T0,
            niveau=Niveau.N2 if ecriture else Niveau.N0,
            roles_appareil=frozenset(),
        )

    return (
        outil(
            "m9_briefing_direction",
            "Briefing de direction enrichi, en lecture seule : santé de l'entreprise (ou « indéterminée : bornes à "
            "fixer "
            "par la direction »), une ligne par section (pipeline, prévision par intervalle, trésorerie, échéances, "
            "capacité, risques de chantier, alertes), ce qui exige la direction classé par niveau et par âge, ce "
            "que la "
            "direction doit déclarer, ce qui a changé depuis hier (avec reçu). Chaque ligne dit son statut de "
            "certitude : "
            "seul ETABLI est certain.",
            {"maintenant": _INSTANT},
            ["maintenant"],
            briefing_direction,
        ),
        outil(
            "m9_tableau_direction",
            "Tableau de direction par section (sante, pipeline, previsions, tresorerie, echeances, sources_fiscales, "
            "capacite, chantiers, alertes_m8), tel que M9 le connaissait à `maintenant` : chaque valeur avec "
            "l'adresse de "
            "son fait, son âge et son statut (ETABLI, ESSAI_NON_APPROUVE, INDETERMINE, PERIME, "
            "PREVISION_PAR_INTERVALLE…). "
            "Sans `section`, le sommaire. Aucun chiffre calculé ici.",
            {
                "maintenant": _INSTANT,
                "section": {"type": "string", "enum": list(SECTIONS_DETAIL)},
                "depart": _DEPART,
                "perime_apres_jours": {"type": "integer", "minimum": 0, "maximum": 3650},
            },
            ["maintenant"],
            tableau,
        ),
        outil(
            "m9_exige_la_direction",
            "Classe de façon déterministe et explicable ce qui attend la direction : niveau d'approbation le plus "
            "élevé "
            "d'abord, puis l'attente la plus ancienne, puis l'identifiant ; une demande sans niveau déclaré est "
            "comptée à "
            "part. Rend la règle, les groupes par niveau (nombre, plus ancienne attente) et ce que seule la "
            "direction peut "
            "déclarer. M9 n'approuve rien.",
            {"maintenant": _INSTANT, "depart": _DEPART},
            ["maintenant"],
            exige_la_direction,
        ),
        outil(
            "m9_changements_depuis",
            "Ce qui a changé entre ce que M9 savait hier (ou à `depuis`) et ce qu'il sait à `maintenant` : état de "
            "chaque "
            "lecture, faits modifiés, nouveaux ou disparus avec leur statut avant et après. Rend un REÇU vérifiable "
            "par "
            "m9_verifier_recu_changements. Aucun chiffre calculé.",
            {
                "maintenant": _INSTANT,
                "depuis": _INSTANT,
                "duree_s": {"type": "integer", "minimum": 60, "maximum": 90 * 86400},
                "depart": _DEPART,
            },
            ["maintenant"],
            changements,
        ),
        outil(
            "m9_verifier_recu_changements",
            "Refait la comparaison de l'intervalle d'un reçu de changements depuis la chaîne de captures et dit si "
            "le reçu "
            "est encore vrai (reçu retouché ou chaîne différente : invalide).",
            {"recu": {"type": "object"}},
            ["recu"],
            verifier_recu,
        ),
        outil(
            "m9_controler_recommandation",
            "Contrôle, sans rien écrire, une recommandation structurée (hypothèses, options, chiffres, risques, "
            "données "
            "manquantes) : chaque chiffre doit venir d'un fait capturé (valeur mot pour mot), d'un reçu intact du "
            "moteur de "
            "calcul de M5 ou d'une hypothèse déclarée par la direction ; un essai, un périmé ou une prévision n'est "
            "jamais "
            "présenté comme établi ; une donnée bloquante manquante interdit de recommander ; la mention « À valider "
            "auprès d'un comptable (CPA) / professionnel qualifié » est exigée quand elle s'applique. M9 ne décide "
            "jamais.",
            {
                "recommandation": {"type": "object"},
                "connaissance": _INSTANT,
                "recus": {"type": "array", "items": {"type": "object"}, "maxItems": 16},
            },
            ["recommandation", "connaissance"],
            controler_recommandation,
        ),
        outil(
            "m9_rafraichir_lectures_direction",
            "Capture, par le port privé de lecture, les lectures du tableau de direction (santé M8, pipeline et "
            "prévision "
            "M2, trésorerie, échéances et revue fiscale M5, retards M4, faits analytiques M10 ; la capacité M4 "
            "seulement si "
            "debut_semaine est fourni). Un refus du producteur est conservé comme manque. Tâche interne : aucun effet "
            "hors du registre des captures.",
            {
                "maintenant": _INSTANT,
                "jour": {"type": "string", "description": "Jour civil AAAA-MM-JJ ; défaut : le jour de `maintenant`."},
                "debut_semaine": {"type": "string", "description": "Lundi AAAA-MM-JJ de la semaine de capacité."},
                "prevision": {
                    "type": "object",
                    "description": "Choix de méthode de la prévision M2 (jamais un seuil).",
                },
            },
            ["maintenant"],
            rafraichir,
            ecriture=True,
        ),
    )
