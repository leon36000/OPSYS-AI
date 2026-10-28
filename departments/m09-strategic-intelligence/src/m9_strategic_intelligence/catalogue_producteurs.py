"""Catalogue versionné des lectures de producteurs que M9 peut capturer (M9.1).

Module pur : décrit QUOI lire chez QUI et OÙ trouver, dans la réponse, les instants métier et les révisions que le
producteur déclare. Il ne lit rien. La liste (département, outil) reproduit ``opsys.lecteurs_m9.LECTURES_AUTORISEES`` —
la
frontière réelle, côté socle — et un test impose l'égalité ; un outil absent de l'une des deux est refusé.

Principes :

* seules des lectures de l'état persistant d'un producteur y figurent. Un outil qui calcule à partir de données fournies
par
  l'appelant (calculateur) n'est jamais une lecture : M9 ne doit pas pouvoir injecter la matière d'un producteur ;
* ``libres`` nomme les seuls arguments que l'appelant peut fournir ; ``fixes`` impose les autres (ex. aucun ``role``
  déclaré par l'appelant) ;
* un chemin d'instant ou de révision est une DÉCLARATION du producteur trouvée dans sa réponse, jamais une valeur
devinée :
  une lecture sans chemin déclaré n'a pas d'instant métier connu et la couverture le dit (``TEMPS_METIER_NON_DECLARE``).
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping

CATALOGUE_VERSION = "2026-10-28.1"
_CHEMIN = re.compile(r"[A-Za-z0-9_]+(\[\*\])?(\.[A-Za-z0-9_]+(\[\*\])?)*")


@dataclasses.dataclass(frozen=True)
class Pagination:
    """Comment une lecture pagine : l'argument qui avance, et où la réponse dit s'il reste une suite."""

    arg_depart: str
    chemin_suivant: str  # absent ou nul = dernière page
    chemin_total: str | None = None


@dataclasses.dataclass(frozen=True)
class Lecture:
    id: str
    departement: str
    outil: str
    libres: frozenset[str]
    fixes: Mapping[str, object] = dataclasses.field(default_factory=dict)
    reference: str | None = None  # argument portant l'instant de référence de la lecture, s'il y en a un
    pagination: Pagination | None = None
    instants_metier: tuple[str, ...] = ()
    revisions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        chemins = [*self.instants_metier, *self.revisions]
        if self.pagination is not None:
            chemins.append(self.pagination.chemin_suivant)
            if self.pagination.chemin_total is not None:
                chemins.append(self.pagination.chemin_total)
        if not all(_CHEMIN.fullmatch(chemin) for chemin in chemins):
            raise ValueError(f"{self.id} : chemin de réponse invalide")
        if set(self.fixes) & set(self.libres):
            raise ValueError(f"{self.id} : un argument ne peut pas être à la fois fixe et libre")
        if self.pagination is not None and self.pagination.arg_depart not in self.libres:
            raise ValueError(f"{self.id} : l'argument de pagination doit être libre")
        if self.reference is not None and self.reference not in self.libres:
            raise ValueError(f"{self.id} : l'argument de référence doit être libre")


def _lecture(id_, departement, outil, libres, **kwargs):
    return Lecture(id_, departement, outil, frozenset(libres), **kwargs)


# Les chemins d'instants/révisions partent de la réponse complète du dispatcher
# ({"ok": true, "resultat": …}) ; ils ne sont déclarés que là où la forme réelle a été constatée par un test.
LECTURES: tuple[Lecture, ...] = (
    _lecture("m1.digest", "m01-front-office", "m1_produire_digest", {"date_reference"}, reference="date_reference"),
    _lecture(
        "m2.leads",
        "m02-revenue-crm",
        "m2_lister_leads",
        {"horodatage", "statut", "segment", "decalage", "limite", "recherche"},
        reference="horodatage",
        pagination=Pagination("decalage", "resultat.resultat.suivant", "resultat.resultat.total"),
        instants_metier=("resultat.resultat.leads[*].ingere_le", "resultat.resultat.leads[*].derniere_activite"),
    ),
    _lecture(
        "m2.relances",
        "m02-revenue-crm",
        "m2_lister_relances",
        {"horodatage", "regle", "permises_seulement", "decalage", "limite"},
        reference="horodatage",
    ),
    _lecture("m3.ecarts", "m03-estimation", "m3_lire_ecarts_estime_reel", {"devis_id", "depuis", "jusqua"}),
    _lecture("m4.interventions", "m04-field-ops", "m4_lister_interventions", {"statut", "curseur", "taille_page"}),
    _lecture("m4.cedule_semaine", "m04-field-ops", "m4_lire_cedule_semaine", {"debut_semaine"}),
    _lecture(
        "m4.retards_incidents",
        "m04-field-ops",
        "m4_lire_retards_incidents",
        {"horodatage_reference"},
        reference="horodatage_reference",
    ),
    _lecture("m4.meteo_intervention", "m04-field-ops", "m4_lire_meteo_intervention", {"intervention_id", "date"}),
    _lecture(
        "m5.prevision_tresorerie",
        "m05-financecore",
        "m5_prevoir_tresorerie",
        {"aujourd_hui", "horizon_semaines", "semaine", "depart"},
        reference="aujourd_hui",
    ),
    _lecture(
        "m5.rentabilite_chantier",
        "m05-financecore",
        "m5_lire_rentabilite_chantier",
        {"chantier_id", "devis_id", "limite"},
    ),
    _lecture(
        "m5.comptes_a_recevoir",
        "m05-financecore",
        "m5_lire_comptes_a_recevoir",
        {"aujourd_hui"},
        reference="aujourd_hui",
    ),
    _lecture("m5.comptes_a_payer", "m05-financecore", "m5_lister_comptes_a_payer", {"po_id", "depart", "sans_po"}),
    _lecture("m6.disponibilite", "m06-material-control", "m6_lire_disponibilite", {"materiau_ids"}),
    _lecture("m7.performance_campagnes", "m07-marketing", "m7_lire_performance_campagnes", {"debut", "fin"}),
    _lecture("m8.vue_executive", "m08-analytics", "m8_lire_vue_executive", {"aujourd_hui"}, reference="aujourd_hui"),
    _lecture("m8.mesures_chantier", "m08-analytics", "m8_lire_mesures_chantier", {"wct_id"}),
    _lecture(
        "m10.paquet_affaire",
        "m10-memoire",
        "m10_paquet_contexte_affaire",
        {"affaire_id", "horodatage"},
        reference="horodatage",
    ),
)

PAR_ID: Mapping[str, Lecture] = {lecture.id: lecture for lecture in LECTURES}
if len(PAR_ID) != len(LECTURES):  # pragma: no cover - garde de construction
    raise ValueError("identifiants de lecture en double")


def lectures_par_departement() -> dict[str, frozenset[str]]:
    """Forme comparée, par test, à ``opsys.lecteurs_m9.LECTURES_AUTORISEES``."""
    resultat: dict[str, set[str]] = {}
    for lecture in LECTURES:
        resultat.setdefault(lecture.departement, set()).add(lecture.outil)
    return {departement: frozenset(outils) for departement, outils in resultat.items()}


def obtenir(lecture_id: object) -> Lecture:
    if type(lecture_id) is not str or lecture_id not in PAR_ID:
        raise ValueError("REJ-CAPTURE-LECTURE : lecture absente du catalogue des producteurs")
    return PAR_ID[lecture_id]


def arguments_admis(lecture: Lecture, arguments: object) -> dict:
    """Arguments finaux envoyés au producteur : libres déclarés seulement, fixes imposés, jamais d'autre clé."""
    if type(arguments) is not dict:
        raise ValueError("REJ-CAPTURE-ARGUMENTS : objet requis")
    inconnus = set(arguments) - lecture.libres
    if inconnus:
        raise ValueError(f"REJ-CAPTURE-ARGUMENTS : arguments non autorisés {sorted(inconnus)}")
    return {**lecture.fixes, **arguments}
