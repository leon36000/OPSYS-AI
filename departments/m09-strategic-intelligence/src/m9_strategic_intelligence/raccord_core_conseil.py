"""Point de raccord du conseil M9 au runtime natif (Core) : la séquence attendue et le vérificateur de trace.

Module pur. M9 n'appelle aucun modèle : un tour de conseil s'exécute sous l'admission de budget du socle, dans le
runtime natif. Ce module fixe CE QUE le runtime et l'orchestrateur admin doivent faire, dans quel ordre et sous
quelle identité, puis juge une TRACE d'exécution fournie par la qualification (``verifier_trace``). Il ne prouve pas
d'où vient la trace : il vérifie sa cohérence avec le contrat. Une qualification n'est ``COMPLETE`` que si la trace
contient un cycle entier observé sans écart ; sans trace, ou avec une trace partielle, le verdict est ``INCOMPLETE``.

Identité : ``m9_lire_entree_tour_conseil`` exige un admin authentifié. Les profils proposés n'ont donc AUCUN outil ;
l'orchestrateur admin lit l'entrée et la remet au tour. Tout succès d'un agent sur un outil M9 est un écart de droits
(aucun outil M9 n'est permis à l'agent dans ce flux). Accepter la lecture par l'agent serait un élargissement de
droits : décision du propriétaire, pas de ce module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from . import conseil, sessions_conseil

VERSION = "2026-10-30.2"
OUTIL_ENTREE = "m9_lire_entree_tour_conseil"
OUTIL_DEPOT = "m9_deposer_tour_conseil"
OUTIL_RECONCILIATION = "reconciliation_reservation"
CODE_REFUS_IDENTITE = "REJ-IDENTITE-APPAREIL-INVALIDE"
ACTEURS = frozenset({"admin", "agent", "runtime"})
ISSUE_ADMISE = "ADMIS"
ISSUES_DEPOT = frozenset({"ADMIS", "REFUSE"})
# Outils M9 qu'un acteur agent a le droit d'appeler avec succès dans ce flux : aucun (l'entrée passe par l'admin).
OUTILS_AGENT_PERMIS: frozenset[str] = frozenset()

SEQUENCE: tuple[dict, ...] = (
    {
        "etape": 1,
        "acteur": "admin",
        "action": "créer et activer les profils proposés par m9_proposer_profils_conseil (agents.creer, manuel, "
        "aucun outil)",
    },
    {"etape": 2, "acteur": "admin", "action": "m9_ouvrir_conseil (dossier figé, un tour en attente par rôle)"},
    {"etape": 3, "acteur": "admin", "action": "m9_lire_entree_tour_conseil (entrée reproductible du tour)"},
    {
        "etape": 4,
        "acteur": "agent",
        "action": "tour exécuté par le runtime natif du profil du rôle sous une réservation de budget, entrée remise "
        "par l'admin, aucun outil M9",
    },
    {"etape": 5, "acteur": "runtime", "action": "réservation réconciliée avec l'usage réel (statut conciliee)"},
    {"etape": 6, "acteur": "admin", "action": "m9_deposer_tour_conseil avec la réservation ; admission déterministe"},
    {"etape": 7, "acteur": "admin", "action": "m9_cloturer_conseil puis m9_lire_rapport_conseil"},
)


def agent_id(role: str) -> str:
    """Identifiant du profil natif d'un rôle (même dérivation que le dépôt)."""
    if type(role) is not str or role not in conseil.PAR_ID:
        raise ValueError("REJ-TOUR-INCONNU : rôle inconnu du conseil")
    return f"m9-{role.replace('_', '-')}"


def _regle(nom: str, statut: str, detail: str) -> dict:
    return {"regle": nom, "statut": statut, "detail": detail}


def _texte(valeur: object) -> bool:
    return type(valeur) is str and bool(valeur.strip())


def _entier(valeur: object, minimum: int) -> bool:
    return type(valeur) is int and valeur >= minimum


def _evenements(trace: object) -> list[Mapping]:
    if not isinstance(trace, Sequence) or isinstance(trace, (str, bytes)) or not trace:
        raise ValueError("REJ-TRACE-FORME : liste non vide d'événements requise")
    for index, evenement in enumerate(trace):
        if not isinstance(evenement, Mapping):
            raise ValueError(f"REJ-TRACE-FORME : événement {index} non objet")
        if evenement.get("acteur") not in ACTEURS or not _texte(evenement.get("outil")):
            raise ValueError(f"REJ-TRACE-FORME : événement {index} sans acteur admin/agent/runtime ou sans outil")
        if evenement.get("resultat") not in {"ok", "refus"}:
            raise ValueError(f"REJ-TRACE-FORME : événement {index} sans résultat ok/refus")
    return list(trace)


def _defauts_depot(depot: Mapping) -> list[str]:
    """Ce qui manque ou ne va pas dans un dépôt accepté par l'outil (jamais une exception non nommée)."""
    defauts: list[str] = []
    role = depot.get("role")
    if not _texte(depot.get("session_id")):
        defauts.append("dépôt sans session_id")
    if type(role) is not str or role not in conseil.PAR_ID:
        defauts.append("dépôt sans rôle connu du conseil")
    if depot.get("issue") not in ISSUES_DEPOT:
        defauts.append("dépôt sans issue d'admission ADMIS/REFUSE")
    reservation = depot.get("reservation")
    if not isinstance(reservation, Mapping):
        defauts.append("dépôt sans réservation")
        return defauts
    if not _texte(reservation.get("id")):
        defauts.append("réservation sans identifiant")
    if type(role) is str and role in conseil.PAR_ID and reservation.get("profil") != agent_id(role):
        defauts.append(f"réservation d'un autre profil que {agent_id(role)}")
    if reservation.get("statut") != "conciliee":
        defauts.append("réservation non conciliée")
    reels, plafond = reservation.get("tokens_reels"), reservation.get("tokens_plafond")
    if not _entier(reels, 0) or not _entier(plafond, 1):
        defauts.append("usage réel ou plafond absent, non entier ou négatif")
    elif reels > plafond:
        defauts.append("usage réel au-delà du plafond réservé")
    return defauts


def verifier_trace(trace: object, *, admin_strict: frozenset[str] | None = None) -> dict:
    """Juge une trace ordonnée ``[{acteur, outil, resultat, code?, session_id?, role?, issue?, reservation?}]``.

    Un dépôt accepté par l'outil porte ``issue`` (``ADMIS`` ou ``REFUSE`` : l'outil répond ``accepte`` même quand la
    sortie est refusée) et ``reservation`` ``{id, profil, statut, tokens_reels, tokens_plafond}``. ``admin_strict``
    est conservé pour compatibilité ; tout succès d'agent sur un outil ``m9_*`` hors ``OUTILS_AGENT_PERMIS`` (ou sur
    un outil de ``admin_strict``) est un écart.

    Règles : R1 aucun succès d'agent sur un outil M9 ; R2 chaque dépôt accepté est complet (session, rôle connu, issue,
    réservation identifiée du profil du rôle, conciliée, usage entier dans le plafond) ; R3 une réservation sert à un
    seul tour ; R4 au plus ``MAX_DEPOTS`` dépôts acceptés par (session, rôle) ; R5 un cycle entier est observé : une
    lecture d'entrée admin PUIS, plus loin dans la trace, un dépôt de MÊME session et MÊME rôle dont l'issue est
    ``ADMIS``. Verdict ``COMPLETE`` sans écart et cycle observé ; ``ECART`` si une règle est violée ; sinon
    ``INCOMPLETE``."""
    evenements = _evenements(trace)
    supplementaires = admin_strict if admin_strict is not None else frozenset()
    regles: list[dict] = []

    def interdit_a_l_agent(outil: str) -> bool:
        return (outil.startswith("m9_") and outil not in OUTILS_AGENT_PERMIS) or outil in supplementaires

    succes_agent = sorted(
        {
            e["outil"]
            for e in evenements
            if e["acteur"] == "agent" and e["resultat"] == "ok" and interdit_a_l_agent(e["outil"])
        }
    )
    refus_agent = sum(1 for e in evenements if e["acteur"] == "agent" and e["resultat"] == "refus")
    if succes_agent:
        regles.append(_regle("R1", "ECART", "un agent a réussi un outil M9 : " + ", ".join(succes_agent)))
    else:
        detail = "aucun succès d'agent sur un outil M9"
        detail += f" ; {refus_agent} refus d'agent observé(s)" if refus_agent else " ; aucun appel d'agent observé"
        regles.append(_regle("R1", "CONFORME", detail))

    depots = [
        (index, e)
        for index, e in enumerate(evenements)
        if e["outil"] == OUTIL_DEPOT and e["acteur"] == "admin" and e["resultat"] == "ok"
    ]
    defauts = sorted({defaut for _, depot in depots for defaut in _defauts_depot(depot)})
    regles.append(
        _regle(
            "R2",
            "ECART" if defauts else "CONFORME",
            "; ".join(defauts) or f"{len(depots)} dépôt(s) accepté(s), complets, sous réservation conforme",
        )
    )

    usage: dict[str, set[tuple]] = {}
    for _, depot in depots:
        reservation = depot.get("reservation")
        if isinstance(reservation, Mapping) and _texte(reservation.get("id")):
            cle = (str(depot.get("session_id")), str(depot.get("role")))
            usage.setdefault(reservation["id"], set()).add(cle)
    partagees = sorted(identifiant for identifiant, tours in usage.items() if len(tours) > 1)
    regles.append(
        _regle(
            "R3",
            "ECART" if partagees else "CONFORME",
            "réservation(s) partagée(s) entre tours : " + ", ".join(partagees)
            if partagees
            else "chaque réservation identifiée sert à un seul tour",
        )
    )

    par_tour: dict[tuple, int] = {}
    for _, depot in depots:
        cle = (str(depot.get("session_id")), str(depot.get("role")))
        par_tour[cle] = par_tour.get(cle, 0) + 1
    excedents = sorted(f"{s}/{r}" for (s, r), n in par_tour.items() if n > sessions_conseil.MAX_DEPOTS)
    regles.append(
        _regle(
            "R4",
            "ECART" if excedents else "CONFORME",
            f"plus de {sessions_conseil.MAX_DEPOTS} dépôts : " + ", ".join(excedents)
            if excedents
            else f"au plus {sessions_conseil.MAX_DEPOTS} dépôts acceptés par tour",
        )
    )

    entrees = [
        (index, e.get("session_id"), e.get("role"))
        for index, e in enumerate(evenements)
        if e["outil"] == OUTIL_ENTREE and e["acteur"] == "admin" and e["resultat"] == "ok"
    ]
    cycles = sorted(
        {
            f"{depot.get('session_id')}/{depot.get('role')}"
            for index_depot, depot in depots
            if depot.get("issue") == ISSUE_ADMISE and not _defauts_depot(depot)
            for index_entree, session, role in entrees
            if index_entree < index_depot and session == depot.get("session_id") and role == depot.get("role")
        }
    )
    regles.append(
        _regle(
            "R5",
            "CONFORME" if cycles else "NON_OBSERVE",
            "cycle(s) entier(s) observé(s) : " + ", ".join(cycles)
            if cycles
            else "aucune entrée admin suivie d'un dépôt ADMIS de même session et même rôle : qualification incomplète",
        )
    )

    if any(r["statut"] == "ECART" for r in regles):
        verdict = "ECART"
    elif cycles:
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
