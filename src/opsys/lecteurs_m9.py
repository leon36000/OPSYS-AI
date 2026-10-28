"""Port privé de lecture de M9 vers les producteurs M1–M8 et M10 (RACCORD COMMUN, à relire par le propriétaire du
socle).

M9 ne lit jamais le stockage d'un autre département ni n'importe son code : il appelle, par le dispatcher réel, des
outils de LECTURE que ce département expose déjà. Ce module est l'unique frontière de ce port :

* une liste blanche explicite (département, outil) — une lecture absente de la liste est refusée, même T0 ;
* l'outil doit exister, être T0/N0 et ne jamais être un outil d'écriture déclaré ;
* l'appelant est l'admin authentifié (console ou appareil), personne active portant encore le rôle admin, relu en base
  à CHAQUE lecture ; un agent, un appareil non admin ou l'absence d'identité sont refusés avant toute lecture ;
* l'appel est attribué au département M9 (jamais au producteur) et n'ajoute aucun droit : chaque outil producteur
  revérifie lui-même son accès, et ce port ne contourne aucune de ses portées.

Aucun droit machine, outil ou compte n'est élargi : la liste blanche ne contient que des outils déjà T0, et le port
n'est
fourni qu'à la fabrique d'outils de M9 (`departements.charger_outils`). La liste des producteurs est la source unique ;
le catalogue pur de M9 (`catalogue_producteurs`) la reproduit et un test impose l'égalité.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy.engine import Connection

from . import contexte as contexte_appel
from . import identite, stockage
from .outils import Autonomie, Niveau

DEPARTEMENT_M9 = "m09-strategic-intelligence"
# Le dispatcher tronque (puis range en artefact) toute sortie au-delà de sa limite : M9 doit recevoir la page entière
# que
# le producteur a bornée lui-même. Au-delà, la capture refuse ; elle ne reçoit jamais une réponse coupée en silence.
LIMITE_LECTURE = 262_144
PORT = "lecteur_producteurs_m9"

# (département -> outils de lecture T0 autorisés). Les outils qui acceptent des DONNÉES de l'appelant pour les calculer
# (calculateurs) n'y figurent pas : une lecture ne doit pas laisser M9 injecter la matière d'un producteur.
LECTURES_AUTORISEES: Mapping[str, frozenset[str]] = {
    "m01-front-office": frozenset({"m1_produire_digest"}),
    "m02-revenue-crm": frozenset({"m2_lister_leads", "m2_lister_relances"}),
    "m03-estimation": frozenset({"m3_lire_ecarts_estime_reel"}),
    "m04-field-ops": frozenset(
        {"m4_lister_interventions", "m4_lire_cedule_semaine", "m4_lire_retards_incidents", "m4_lire_meteo_intervention"}
    ),
    "m05-financecore": frozenset(
        {
            "m5_prevoir_tresorerie",
            "m5_lire_rentabilite_chantier",
            "m5_lire_comptes_a_recevoir",
            "m5_lister_comptes_a_payer",
        }
    ),
    "m06-material-control": frozenset({"m6_lire_disponibilite"}),
    "m07-marketing": frozenset({"m7_lire_performance_campagnes"}),
    "m08-analytics": frozenset({"m8_lire_vue_executive", "m8_lire_mesures_chantier"}),
    "m10-memoire": frozenset({"m10_paquet_contexte_affaire"}),
}


def _refus(erreur: str, details: str) -> dict[str, Any]:
    return {"ok": False, "erreur": erreur, "details": details}


def construire_lecteur(
    departements: Mapping[str, Any],
    cnx_factory: Callable[[], AbstractContextManager[Connection]],
) -> Callable[..., dict[str, Any]]:
    """Lecteur `(departement, outil, arguments) -> réponse du dispatcher` ; refus structurés, sans exception."""
    from .capacites import Capacites  # import tardif : capacites construit ce lecteur

    producteurs = {dep for dep in LECTURES_AUTORISEES if dep in departements}
    lecteur = (
        Capacites(
            departements,
            cnx_factory,
            filtre=producteurs,
            appelant=DEPARTEMENT_M9,
            memoire=False,
            limite_sortie=LIMITE_LECTURE,
        )
        if producteurs and DEPARTEMENT_M9 in departements
        else None
    )

    def lire(departement: str, outil: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if lecteur is None or departement not in producteurs:
            return _refus("producteur_indisponible", "le département producteur n'est pas installé")
        if outil not in LECTURES_AUTORISEES.get(departement, frozenset()):
            return _refus("lecture_non_autorisee", "lecture absente de la liste blanche des producteurs de M9")
        appelante = contexte_appel.identite_appelante()
        if (
            appelante is None
            or appelante.role != "admin"
            or appelante.source not in {"console", "appareil"}
            or contexte_appel.DEPARTEMENT_APPELANT.get() != DEPARTEMENT_M9
            or contexte_appel.departement_origine_appelante() != DEPARTEMENT_M9
        ):
            return _refus("identite_admin_requise", "la lecture des producteurs exige l'admin authentifié via M9")
        cnx = stockage.connexion_courante()
        personne = identite.personne_active(cnx, appelante.personne) if cnx is not None else None
        if personne is None or "admin" not in personne.roles:
            return _refus("identite_admin_requise", "personne active portant encore le rôle admin requise")
        entree = lecteur.index.get(outil)
        if entree is None or entree[0] is None or entree[0].id != departement:
            return _refus("producteur_indisponible", "l'outil de lecture n'est pas chargé")
        definition = entree[1]
        if definition.autonomie is not Autonomie.T0 or definition.niveau_effectif is not Niveau.N0:
            return _refus("lecture_non_autorisee", "seule une lecture T0/N0 est admise")
        if not isinstance(arguments, Mapping):
            return _refus("arguments_invalides", "arguments objet requis")
        return lecteur.appeler(outil, dict(arguments))

    return lire
