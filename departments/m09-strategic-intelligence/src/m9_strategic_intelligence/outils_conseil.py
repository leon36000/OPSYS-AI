"""Outils M9.4/M9.8/M9.10 : dossier stratégique, scénarios et sessions de conseil.

Adaptateur seul (la logique est dans ``dossier_strategique``, ``scenarios``, ``conseil`` et ``sessions_conseil``,
modules
purs). Accès : admin authentifié (console ou appareil) seulement, y compris en lecture — un dossier contient des copies
de
producteurs. Aucun outil de ce fichier n'appelle un modèle, ne crée un profil d'agent, n'accorde un droit ni n'exécute
une
action : ``m9_deposer_tour_conseil`` ne reçoit que la SORTIE d'un tour déjà exécuté par le runtime natif et refuse tout
dépôt
sans réservation native réconciliée du bon profil, utilisée une seule fois.

Le modèle n'est pas appelé depuis M9 parce que le tour doit s'exécuter sous l'admission de budget du socle, avec
l'intention
validée AVANT l'effet : c'est le rôle du runtime natif (Core). Ce que M9 garantit : une entrée reproductible, un dépôt
validé
(citations mot pour mot, inférences à prémisses, demandes d'outil écartées), au plus deux dépôts par tour, aucune
recommandation sans ancrage et aucune autorité d'effet.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opsys import admission_agents, stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import conseil, dossier_strategique, scenarios, sessions_conseil
from .outils_tissu import DEPARTEMENT, MAX_PAGE_OCTETS, borner, exiger_admin_strict

REGISTRE_SESSIONS = "sessions_conseil"
REGISTRE_CAPTURES = "captures_strategiques"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _tranche(objet: object, depart: int, longueur: int) -> dict:
    if type(depart) is not int or depart < 0 or type(longueur) is not int or not 1 <= longueur <= MAX_PAGE_OCTETS:
        raise _refus("REJ-TISSU-DEPART", "départ et longueur bornés requis")
    texte = cs.canonique(objet)
    if depart > len(texte):
        raise _refus("REJ-TISSU-DEPART", "départ au-delà du contenu")
    fin = min(len(texte), depart + longueur)
    return {
        "taille": len(texte),
        "depart": depart,
        "contenu_json": texte[depart:fin],
        "prochain_depart": fin if fin < len(texte) else None,
        "sha256": cs.empreinte(objet),
    }


def construire_outils(
    *, budget_sortie: int, captures_cible: Any = None, sessions_cible: Any = None
) -> tuple[Outil, ...]:
    def captures() -> list[dict]:
        source = captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)
        chaine = list(source)
        ok, raison = cs.valider_chaine(chaine)
        if not ok:
            raise _refus("REJ-CAPTURE-CHAINE-INVALIDE", f"registre des captures invalide ({raison})")
        return chaine

    def registre_sessions() -> Any:
        return sessions_cible if sessions_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_SESSIONS)

    def sessions() -> list[dict]:
        evenements = list(registre_sessions())
        ok, raison = sessions_conseil.valider_chaine(evenements)
        if not ok:
            raise _refus("REJ-SESSION-CHAINE-INVALIDE", f"registre des sessions invalide ({raison})")
        return evenements

    def ajouter(evenements: list[dict], evenement: dict | None) -> None:
        if evenement is not None:
            registre_sessions().append(evenement, rang_attendu=len(evenements))

    def dossier(
        question: str, domaines: list[str], reference: str, connaissance: str | None, attendues: list[str] | None
    ) -> dict:
        return dossier_strategique.construire(
            captures(),
            question=question,
            domaines=domaines,
            reference=reference,
            connaissance=connaissance or reference,
            attendues=attendues,
        )

    def apercu_dossier(
        question: str,
        domaines: list[str],
        reference: str,
        connaissance: str | None = None,
        attendues: list[str] | None = None,
        depart: int = 0,
    ) -> dict[str, Any]:
        exiger_admin_strict()
        construit = dossier(question, domaines, reference, connaissance, attendues)
        adresses = sorted(construit["faits"])
        if type(depart) is not int or not 0 <= depart <= len(adresses):
            raise _refus("REJ-TISSU-DEPART", "départ entre 0 et le nombre de faits requis ; reprendre à 0")
        resume = {
            k: construit[k]
            for k in (
                "type",
                "question",
                "domaines",
                "reference",
                "connaissance",
                "dossier_id",
                "faits_non_retenus",
                "lectures_partielles",
                "temps_metier_non_declare",
            )
        }
        resume["couverture"] = {
            "complete": construit["couverture"]["complete"],
            "lectures_non_presentes": construit["couverture"]["lectures_non_presentes"],
        }
        resume["manques"] = construit["manques"]
        resume["contradictions"] = len(construit["contradictions"])
        # Le résumé (couverture, manques) grandit avec le catalogue : la page de faits prend ce qui reste du budget,
        # moins 400 caractères pour les champs de pagination et l'enveloppe.
        reste_faits = budget_sortie - len(cs.canonique(resume)) - 400
        page: dict[str, str] = {}
        for adresse in adresses[depart:]:
            essai = {**page, adresse: construit["faits"][adresse]}
            if len(cs.canonique(essai)) > reste_faits:
                break
            page = essai
        if adresses[depart:] and not page:
            raise _refus("REJ-TISSU-BORNE", "un fait dépasse la borne de sortie")
        suivant = depart + len(page)
        return borner(
            {
                "accepte": True,
                **resume,
                "total_faits": len(adresses),
                "faits": page,
                "depart": depart,
                "prochain_depart": suivant if suivant < len(adresses) else None,
            },
            budget_sortie,
        )

    def evaluer_scenarios(
        reference: str, bases: dict[str, str], chocs: list[dict[str, Any]], connaissance: str | None = None
    ) -> dict[str, Any]:
        exiger_admin_strict()
        if type(chocs) is not list or not 1 <= len(chocs) <= scenarios.MAX_CHOCS:
            raise _refus("REJ-SCENARIO-COMPARAISON", f"1 à {scenarios.MAX_CHOCS} chocs requis")
        faits = dossier("Scénarios", ["strategie"], reference, connaissance, None)["faits"]
        evalues = []
        for choc in chocs:
            if not isinstance(choc, Mapping) or set(choc) != {"choc", "parametres"}:
                raise _refus("REJ-SCENARIO-CHOC", "chaque choc est {choc, parametres}")
            evalues.append(scenarios.evaluer(choc["choc"], choc["parametres"], bases, faits))
        comparaison = scenarios.comparer(evalues, bases, faits)
        return borner({"accepte": True, "scenarios": evalues, "comparaison": comparaison}, budget_sortie)

    def proposer_profils() -> dict[str, Any]:
        exiger_admin_strict()
        # Aucun outil : l'entrée du tour exige un admin authentifié (``m9_lire_entree_tour_conseil``) ; l'agent ne
        # pourrait pas l'appeler. L'orchestrateur admin la lit et la remet au tour ; aucun droit n'est élargi.
        profils = [
            conseil.profil_agent(
                role.id,
                outils=[],
                budget_jour=3 * role.enveloppe_tokens,
                budget_mois=60 * role.enveloppe_tokens,
            )
            for role in conseil.ROLES
            if role.etape != "audit"
        ]
        return borner(
            {
                "accepte": True,
                "type": "PROFILS_CONSEIL_PROPOSES",
                "profils": profils,
                "creation": "déclarations seulement : un administrateur les crée (agents.creer) et les active",
                "entree_du_tour": "remise par l'orchestrateur admin (m9_lire_entree_tour_conseil) ; le profil "
                "n'a aucun outil",
            },
            budget_sortie,
        )

    def ouvrir_conseil(
        question: str,
        domaines: list[str],
        importance: str,
        budget_tokens: int,
        reference: str,
        horodatage: str,
        attendues: list[str] | None = None,
    ) -> dict[str, Any]:
        exiger_admin_strict()
        evenements = sessions()
        construit = dossier(question, domaines, reference, None, attendues)
        evenement, session_id = sessions_conseil.ouvrir(
            evenements, dossier=construit, importance=importance, budget_tokens=budget_tokens, recu_a=horodatage
        )
        ajouter(evenements, evenement)
        evenements = evenements + ([evenement] if evenement else [])
        projection = sessions_conseil.etat(evenements, session_id)
        return borner(
            {
                "accepte": True,
                "cree": evenement is not None,
                **_resume(projection),
                "selection": next(e for e in evenements if e.get("session_id") == session_id)["selection"],
            },
            budget_sortie,
        )

    def _resume(projection: Mapping) -> dict:
        return {
            "session_id": projection["session_id"],
            "question": projection["question"],
            "importance": projection["importance"],
            "dossier_id": projection["dossier_id"],
            "tours": [
                {
                    "role": t["role"],
                    "statut": t["statut"],
                    "depots": t["depots"],
                    "refus": [r["code"] for r in t["refus"]],
                    "reservation_id": t["reservation_id"],
                    "tokens_reels": t.get("tokens_reels"),
                    "affirmations": len(t["proposition"]["affirmations"]) if t["proposition"] else 0,
                }
                for t in projection["tours"]
            ],
            "specialistes_tranches": projection["specialistes_tranches"],
            "critique_ouvert": projection["critique_ouvert"],
            "toutes_tranchees": projection["toutes_tranchees"],
            "cloture": None
            if projection["cloture"] is None
            else {
                "issue": projection["cloture"]["issue"],
                "rapport_id": projection["cloture"]["rapport_id"],
                "raison_abstention": projection["cloture"]["raison_abstention"],
                "autorite_d_effet": False,
            },
        }

    def lire_conseil(session_id: str) -> dict[str, Any]:
        exiger_admin_strict()
        return borner({"accepte": True, **_resume(sessions_conseil.etat(sessions(), session_id))}, budget_sortie)

    def lire_entree_tour(
        session_id: str, role: str, depart: int = 0, longueur: int = MAX_PAGE_OCTETS
    ) -> dict[str, Any]:
        exiger_admin_strict()
        entree = sessions_conseil.entree_tour(sessions(), session_id, role)
        return borner(
            {"accepte": True, "role": role, "session_id": session_id, **_tranche(entree, depart, longueur)},
            budget_sortie,
        )

    def deposer_tour(
        session_id: str, role: str, sortie: dict[str, Any], reservation_id: str, horodatage: str
    ) -> dict[str, Any]:
        exiger_admin_strict()
        evenements = sessions()
        if role not in conseil.PAR_ID:
            raise _refus("REJ-TOUR-INCONNU", "rôle inconnu du conseil")
        agent_id = f"m9-{role.replace('_', '-')}"
        cnx = stockage.connexion_courante()
        try:
            reservation = admission_agents.lire_reservation(cnx, reservation_id, agent_id=agent_id)
        except (admission_agents.AdmissionRefusee, ValueError, KeyError) as exc:
            raise _refus(
                "REJ-TOUR-RESERVATION", f"réservation native du profil {agent_id} introuvable ou étrangère ({exc})"
            ) from exc
        if reservation["statut"] != "conciliee" or reservation["tokens_reels"] is None:
            raise _refus(
                "REJ-TOUR-RESERVATION",
                f"réservation {reservation['statut']} : le runtime doit la réconcilier (usage réel) avant le dépôt",
            )
        if reservation["tokens_reels"] > reservation["tokens_plafond"]:
            raise _refus(
                "REJ-TOUR-RESERVATION", "usage réel au-delà du plafond réservé : dépôt refusé, à réconcilier à la main"
            )
        for evenement in evenements:
            if (
                evenement["type"] == "TOUR"
                and evenement["reservation_id"] == reservation_id
                and (evenement["session_id"], evenement["role"]) != (session_id, role)
            ):
                raise _refus("REJ-TOUR-RESERVATION", "cette réservation a déjà servi à un autre tour : usage unique")
        evenement = sessions_conseil.deposer(
            evenements,
            session_id,
            role,
            sortie,
            reservation_id=reservation_id,
            tokens_reels=reservation["tokens_reels"],
            recu_a=horodatage,
        )
        ajouter(evenements, evenement)
        courant = evenements + ([evenement] if evenement else [])
        return borner(
            {
                "accepte": True,
                "rejoue": evenement is None,
                "issue": next(
                    e
                    for e in reversed(courant)
                    if e["type"] == "TOUR" and e["role"] == role and e["session_id"] == session_id
                )["issue"],
                **_resume(sessions_conseil.etat(courant, session_id)),
            },
            budget_sortie,
        )

    def abandonner_tour(session_id: str, role: str, raison: str, horodatage: str) -> dict[str, Any]:
        exiger_admin_strict()
        evenements = sessions()
        evenement = sessions_conseil.abandonner(evenements, session_id, role, raison, recu_a=horodatage)
        ajouter(evenements, evenement)
        courant = evenements + ([evenement] if evenement else [])
        return borner(
            {"accepte": True, "rejoue": evenement is None, **_resume(sessions_conseil.etat(courant, session_id))},
            budget_sortie,
        )

    def cloturer_conseil(session_id: str, horodatage: str) -> dict[str, Any]:
        exiger_admin_strict()
        evenements = sessions()
        evenement = sessions_conseil.cloturer(evenements, session_id, recu_a=horodatage)
        ajouter(evenements, evenement)
        courant = evenements + ([evenement] if evenement else [])
        resume = _resume(sessions_conseil.etat(courant, session_id))
        cloture = next(e for e in reversed(courant) if e["type"] == "CLOTURE" and e["session_id"] == session_id)
        return borner(
            {"accepte": True, "rejoue": evenement is None, **resume, "gouvernance": cloture["gouvernance"]},
            budget_sortie,
        )

    def lire_rapport_conseil(session_id: str, depart: int = 0, longueur: int = MAX_PAGE_OCTETS) -> dict[str, Any]:
        exiger_admin_strict()
        cloture = sessions_conseil.etat(sessions(), session_id)["cloture"]
        if cloture is None:
            raise _refus("REJ-SESSION-EN-COURS", "la session n'est pas close : aucun rapport")
        return borner(
            {
                "accepte": True,
                "session_id": session_id,
                "rapport_id": cloture["rapport_id"],
                **_tranche(cloture["rapport"], depart, longueur),
            },
            budget_sortie,
        )

    objet = {"type": "object"}
    texte = {"type": "string", "minLength": 1, "maxLength": 2048}
    ident = {"type": "string", "minLength": 1, "maxLength": 128}
    domaines = {
        "type": "array",
        "items": {"type": "string", "maxLength": 32},
        "minItems": 1,
        "maxItems": 16,
        "uniqueItems": True,
    }
    attendues = {"type": "array", "items": {"type": "string", "maxLength": 64}, "maxItems": 64, "uniqueItems": True}
    tranche = {
        "depart": {"type": "integer", "minimum": 0},
        "longueur": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_OCTETS},
    }
    admin = frozenset({"admin"})

    def outil(nom, description, proprietes, requis, fonction, *, ecriture=False):
        return Outil(
            nom=nom,
            description=description,
            parametres={"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False},
            fonction=fonction,
            autonomie=Autonomie.T1 if ecriture else Autonomie.T0,
            niveau=Niveau.N2 if ecriture else Niveau.N0,
            roles_appareil=admin,
        )

    return (
        outil(
            "m9_apercu_dossier_strategique",
            "Construit, sans rien écrire, le dossier stratégique d'une question depuis les captures connues : "
            "couverture, "
            "manques, contradictions et faits citables adressés (<lecture>#<rang>:<chemin>), par pages bornées.",
            {
                "question": texte,
                "domaines": domaines,
                "reference": _INSTANT,
                "connaissance": _INSTANT,
                "attendues": attendues,
                "depart": {"type": "integer", "minimum": 0},
            },
            ["question", "domaines", "reference"],
            apercu_dossier,
        ),
        outil(
            "m9_evaluer_scenarios",
            "Évalue des chocs du catalogue (hypothèses nommées, bases = faits citables du dossier) et les compare à la "
            "référence : sensibilités arithmétiques seulement, sans base le calcul est refusé ; finance, capacité et "
            "stock "
            "restent à calculer par leur propriétaire.",
            {
                "reference": _INSTANT,
                "connaissance": _INSTANT,
                "bases": objet,
                "chocs": {"type": "array", "items": objet, "minItems": 1, "maxItems": scenarios.MAX_CHOCS},
            },
            ["reference", "bases", "chocs"],
            evaluer_scenarios,
        ),
        outil(
            "m9_proposer_profils_conseil",
            "Rend les déclarations de profils d'agents des rôles du conseil (manuel, tours et réessais bornés, aucun "
            "outil : l'entrée du tour est remise par l'admin). Aucune création, aucun grant : un administrateur les "
            "crée et les active.",
            {},
            [],
            proposer_profils,
        ),
        outil(
            "m9_ouvrir_conseil",
            "Ouvre (idempotent) une session de conseil : dossier figé, sélection déterministe des spécialistes "
            "utiles sous "
            "budget, un tour en attente par rôle. N'appelle aucun modèle.",
            {
                "question": texte,
                "domaines": domaines,
                "importance": {"type": "string", "enum": list(conseil.IMPORTANCES)},
                "budget_tokens": {"type": "integer", "minimum": 0, "maximum": 5_000_000},
                "reference": _INSTANT,
                "horodatage": _INSTANT,
                "attendues": attendues,
            },
            ["question", "domaines", "importance", "budget_tokens", "reference", "horodatage"],
            ouvrir_conseil,
            ecriture=True,
        ),
        outil(
            "m9_lire_conseil",
            "Projection d'une session : tours, dépôts, refus, clôture.",
            {"session_id": ident},
            ["session_id"],
            lire_conseil,
        ),
        outil(
            "m9_lire_entree_tour_conseil",
            "Entrée d'un tour en attente (consigne fixe et données séparées), par tranches bornées ; refuse un tour "
            "tranché ou "
            "prématuré (critique).",
            {"session_id": ident, "role": ident, **tranche},
            ["session_id", "role"],
            lire_entree_tour,
        ),
        outil(
            "m9_deposer_tour_conseil",
            "Dépose la sortie d'un tour exécuté par le runtime natif. Exige une réservation native réconciliée du "
            "profil du "
            "rôle, à usage unique ; valide citations, inférences et recommandation ; au plus deux dépôts par tour.",
            {"session_id": ident, "role": ident, "sortie": objet, "reservation_id": ident, "horodatage": _INSTANT},
            ["session_id", "role", "sortie", "reservation_id", "horodatage"],
            deposer_tour,
            ecriture=True,
        ),
        outil(
            "m9_abandonner_tour_conseil",
            "Renonce à un tour en attente (la réservation native éventuelle reste à réconcilier là où elle vit).",
            {
                "session_id": ident,
                "role": ident,
                "raison": {"type": "string", "minLength": 1, "maxLength": 500},
                "horodatage": _INSTANT,
            },
            ["session_id", "role", "raison", "horodatage"],
            abandonner_tour,
            ecriture=True,
        ),
        outil(
            "m9_cloturer_conseil",
            "Clôture une session dont tous les tours sont tranchés : recommandation gouvernée ou abstention, rapport "
            "de décision "
            "v2 (21 sections retenues par délégation) assemblé. Aucun effet n'est autorisé.",
            {"session_id": ident, "horodatage": _INSTANT},
            ["session_id", "horodatage"],
            cloturer_conseil,
            ecriture=True,
        ),
        outil(
            "m9_lire_rapport_conseil",
            "Relit, par tranches bornées, le rapport de décision v2 d'une session close.",
            {"session_id": ident, **tranche},
            ["session_id"],
            lire_rapport_conseil,
        ),
    )
