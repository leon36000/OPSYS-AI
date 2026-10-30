"""Point de raccord du conseil M9 au runtime natif (Core) : la séquence attendue et le vérificateur de trace.

Module pur. M9 n'appelle aucun modèle : un tour de conseil s'exécute sous l'admission de budget du socle, dans le
runtime natif. Ce module fixe CE QUE le runtime et l'orchestrateur admin doivent faire, dans quel ordre et sous
quelle identité, puis juge une TRACE d'exécution fournie par la qualification (``verifier_trace``). Il ne prouve pas
d'où vient la trace : il vérifie sa cohérence avec le contrat. Une qualification n'est ``COMPLETE`` que si la trace
contient un cycle entier observé sans écart ; sans trace, ou avec une trace partielle, le verdict est ``INCOMPLETE``.

Écart connu, à constater et non à corriger ici : les profils proposés (``m9_proposer_profils_conseil``) listent l'outil
``m9_lire_entree_tour_conseil``, qui exige un admin authentifié (``exiger_admin_strict``). Un agent natif appelant cet
outil est donc attendu REFUSÉ (``REJ-IDENTITE-APPAREIL-INVALIDE``) ; l'entrée doit alors être remise au tour par
l'orchestrateur admin. Accepter la lecture par l'agent serait un élargissement de droits : décision du propriétaire,
pas de ce module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from . import conseil, sessions_conseil

VERSION = "2026-10-30.1"
OUTIL_ENTREE = "m9_lire_entree_tour_conseil"
OUTIL_DEPOT = "m9_deposer_tour_conseil"
CODE_REFUS_IDENTITE = "REJ-IDENTITE-APPAREIL-INVALIDE"
ACTEURS = frozenset({"admin", "agent"})
# Outils M9 qu'un acteur agent a le droit d'appeler avec succès dans ce flux : aucun (l'entrée passe par l'admin).
OUTILS_AGENT_PERMIS: frozenset[str] = frozenset()

SEQUENCE: tuple[dict, ...] = (
    {
        "etape": 1,
        "acteur": "admin",
        "action": "créer et activer les profils proposés par m9_proposer_profils_conseil (agents.creer, manuel)",
    },
    {"etape": 2, "acteur": "admin", "action": "m9_ouvrir_conseil (dossier figé, un tour en attente par rôle)"},
    {"etape": 3, "acteur": "admin", "action": "m9_lire_entree_tour_conseil (entrée reproductible du tour)"},
    {
        "etape": 4,
        "acteur": "agent",
        "action": "tour exécuté par le runtime natif du profil du rôle sous une réservation de budget",
    },
    {"etape": 5, "acteur": "runtime", "action": "réservation réconciliée avec l'usage réel (statut conciliee)"},
    {"etape": 6, "acteur": "admin", "action": "m9_deposer_tour_conseil avec la réservation ; admission déterministe"},
    {"etape": 7, "acteur": "admin", "action": "m9_cloturer_conseil puis m9_lire_rapport_conseil"},
)


def agent_id(role: str) -> str:
    """Identifiant du profil natif d'un rôle (même dérivation que le dépôt)."""
    if role not in conseil.PAR_ID:
        raise ValueError("REJ-TOUR-INCONNU : rôle inconnu du conseil")
    return f"m9-{role.replace('_', '-')}"


def _regle(nom: str, statut: str, detail: str) -> dict:
    return {"regle": nom, "statut": statut, "detail": detail}


def _evenements(trace: object) -> list[Mapping]:
    if not isinstance(trace, Sequence) or isinstance(trace, str) or not trace:
        raise ValueError("REJ-TRACE-FORME : liste non vide d'événements requise")
    for index, evenement in enumerate(trace):
        if not isinstance(evenement, Mapping):
            raise ValueError(f"REJ-TRACE-FORME : événement {index} non objet")
        if evenement.get("acteur") not in ACTEURS or type(evenement.get("outil")) is not str:
            raise ValueError(f"REJ-TRACE-FORME : événement {index} sans acteur admin/agent ou sans outil")
        if evenement.get("resultat") not in {"ok", "refus"}:
            raise ValueError(f"REJ-TRACE-FORME : événement {index} sans résultat ok/refus")
    return list(trace)


def verifier_trace(trace: object, *, admin_strict: frozenset[str] | None = None) -> dict:
    """Juge une trace ``[{acteur, outil, resultat, code?, session_id?, role?, reservation?}]``.

    ``reservation`` d'un dépôt : ``{id, profil, statut, tokens_reels, tokens_plafond}``. ``admin_strict`` : noms des
    outils qui exigent l'admin (tout succès d'un agent sur l'un d'eux est un ÉCART de droits).

    Règles : R1 aucun succès d'agent sur un outil admin ; R2 chaque dépôt accepté porte une réservation du profil du
    rôle, conciliée, dans son plafond ; R3 une réservation sert à un seul tour ; R4 au plus ``MAX_DEPOTS`` dépôts
    acceptés par (session, rôle) ; R5 un cycle entier est observé (lecture d'entrée admin, dépôt accepté). Verdict
    ``COMPLETE`` sans écart et cycle observé ; ``ECART`` s'il y a une règle violée ; sinon ``INCOMPLETE``."""
    evenements = _evenements(trace)
    strict = admin_strict if admin_strict is not None else frozenset({OUTIL_ENTREE, OUTIL_DEPOT})
    regles: list[dict] = []

    succes_agent = [e for e in evenements if e["acteur"] == "agent" and e["resultat"] == "ok" and e["outil"] in strict]
    refus_agent = [
        e for e in evenements if e["acteur"] == "agent" and e["resultat"] == "refus" and e["outil"] in strict
    ]
    if succes_agent:
        regles.append(
            _regle(
                "R1",
                "ECART",
                "un agent a réussi un outil admin : " + ", ".join(sorted({e["outil"] for e in succes_agent})),
            )
        )
    else:
        detail = "aucun succès d'agent sur un outil admin"
        detail += f" ; {len(refus_agent)} refus d'agent observé(s)" if refus_agent else " ; aucun appel d'agent observé"
        regles.append(_regle("R1", "CONFORME", detail))

    depots = [e for e in evenements if e["outil"] == OUTIL_DEPOT and e["acteur"] == "admin" and e["resultat"] == "ok"]
    erreurs_r2: list[str] = []
    for depot in depots:
        role = depot.get("role")
        reservation = depot.get("reservation")
        if role not in conseil.PAR_ID or not isinstance(reservation, Mapping):
            erreurs_r2.append("dépôt sans rôle connu ou sans réservation")
            continue
        if reservation.get("profil") != agent_id(role):
            erreurs_r2.append(f"réservation d'un autre profil que {agent_id(role)}")
        if reservation.get("statut") != "conciliee" or type(reservation.get("tokens_reels")) is not int:
            erreurs_r2.append("réservation non conciliée avec un usage réel entier")
        elif (
            type(reservation.get("tokens_plafond")) is not int
            or reservation["tokens_reels"] > reservation["tokens_plafond"]
        ):
            erreurs_r2.append("usage réel au-delà du plafond réservé")
    regles.append(
        _regle(
            "R2",
            "ECART" if erreurs_r2 else "CONFORME",
            "; ".join(sorted(set(erreurs_r2))) or f"{len(depots)} dépôt(s) accepté(s) sous réservation conforme",
        )
    )

    usage: dict[str, set[tuple]] = {}
    for depot in depots:
        reservation = depot.get("reservation")
        if isinstance(reservation, Mapping):
            usage.setdefault(str(reservation.get("id")), set()).add((depot.get("session_id"), depot.get("role")))
    partagees = sorted(identifiant for identifiant, tours in usage.items() if len(tours) > 1)
    regles.append(
        _regle(
            "R3",
            "ECART" if partagees else "CONFORME",
            "réservation(s) partagée(s) entre tours : " + ", ".join(partagees)
            if partagees
            else "chaque réservation sert à un seul tour",
        )
    )

    par_tour: dict[tuple, int] = {}
    for depot in depots:
        cle = (depot.get("session_id"), depot.get("role"))
        par_tour[cle] = par_tour.get(cle, 0) + 1
    excedents = sorted(f"{s}/{r}" for (s, r), n in par_tour.items() if n > sessions_conseil.MAX_DEPOTS)
    regles.append(
        _regle(
            "R4",
            "ECART" if excedents else "CONFORME",
            (f"plus de {sessions_conseil.MAX_DEPOTS} dépôts : " + ", ".join(excedents))
            if excedents
            else "au plus deux dépôts acceptés par tour",
        )
    )

    entrees = [e for e in evenements if e["outil"] == OUTIL_ENTREE and e["acteur"] == "admin" and e["resultat"] == "ok"]
    cycle = bool(entrees) and bool(depots)
    regles.append(
        _regle(
            "R5",
            "CONFORME" if cycle else "NON_OBSERVE",
            "cycle entier observé (entrée admin puis dépôt accepté)"
            if cycle
            else "aucun cycle entier : qualification incomplète",
        )
    )

    if any(r["statut"] == "ECART" for r in regles):
        verdict = "ECART"
    elif cycle:
        verdict = "COMPLETE"
    else:
        verdict = "INCOMPLETE"
    return {
        "type": "VERDICT_TRACE_RACCORD_CORE_CONSEIL",
        "version": VERSION,
        "verdict": verdict,
        "regles": regles,
        "evenements": len(evenements),
        "limites": [
            "Le vérificateur juge la cohérence d'une trace avec le contrat, pas son origine (Core natif ou non).",
            "La vérité des inférences du conseil n'est pas évaluée ici.",
        ],
    }
