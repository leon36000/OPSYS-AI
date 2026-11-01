"""Les jeux de données exportables vers les outils BI : une liste FERMÉE, colonne par colonne.

Un jeu est une VUE de l'entrepôt dérivé de M8 (`m8_ent_*`) : jamais une table du socle, jamais un registre de
département,
jamais une requête de l'appelant. Chaque colonne déclare son type (OData), sa forme (une expression régulière pour un
identifiant ou une date, qui interdit qu'un renseignement personnel s'y glisse), si c'est du texte libre (alors masqué
par le
masqueur PII) et si elle est FINANCIÈRE (absente pour un jeton sans portée financière).

Aucune colonne ne porte une personne : l'entrepôt n'en a pas (ni technicien, ni client, ni contact).
"""

from __future__ import annotations

import dataclasses
import re

from sqlalchemy import BigInteger, Boolean, Integer, Table

from ..stockage import schema

IDENTIFIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:~-]{0,255}$")
INSTANT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9:.+\-Zz]{1,32})?$")
DECIMAL = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
CODE = re.compile(r"^[a-z0-9_]{1,40}$")
EMPREINTE = re.compile(r"^[0-9a-f]{64}$")

EDM_TEXTE = "Edm.String"
EDM_ENTIER = "Edm.Int32"
EDM_ENTIER_LONG = "Edm.Int64"
EDM_BOOLEEN = "Edm.Boolean"


@dataclasses.dataclass(frozen=True)
class Colonne:
    nom: str
    edm: str
    forme: re.Pattern[str] | None = None  # None : texte libre, masqué par le masqueur PII
    financiere: bool = False

    @property
    def texte_libre(self) -> bool:
        return self.edm == EDM_TEXTE and self.forme is None


@dataclasses.dataclass(frozen=True)
class Jeu:
    nom: str
    entite: str
    table: Table
    description: str
    colonnes: tuple[Colonne, ...]
    cles: tuple[str, ...]
    ordre: tuple[str, ...]
    lignes_financieres_par_mesure: bool = False  # les lignes des mesures « financier » exigent la portée financière

    def colonnes_visibles(self, financier: bool) -> tuple[Colonne, ...]:
        return tuple(c for c in self.colonnes if financier or not c.financiere)


def _c(nom: str, edm: str = EDM_TEXTE, forme: re.Pattern[str] | None = None, financiere: bool = False) -> Colonne:
    return Colonne(nom, edm, forme, financiere)


_JEUX = (
    Jeu(
        "mesures_courantes",
        "MesuresCourantes",
        schema.M8_ENT_MESURES_COURANTES,
        "Les mesures d'entreprise du catalogue fermé de M8, avec source, version de définition, instant du dernier "
        "fait "
        "et fenêtre de fraîcheur déclarée (le statut de fraîcheur dépend de l'heure de la lecture : à calculer).",
        (
            _c("metric_id", forme=IDENTIFIANT),
            _c("construction_id", forme=EMPREINTE),
            _c("nom"),
            _c("domaine", forme=CODE),
            _c("sens", forme=CODE),
            _c("sensibilite", forme=CODE),
            _c("proprietaire", forme=IDENTIFIANT),
            _c("unite"),
            _c("statut", forme=CODE),
            _c("valeur", forme=DECIMAL),
            _c("detail"),
            _c("source"),
            _c("version_definition", forme=EMPREINTE),
            _c("dernier_fait_le", forme=INSTANT),
            _c("fraicheur_attendue_s", EDM_ENTIER),
            _c("fraicheur_terminale", EDM_BOOLEEN),
        ),
        ("metric_id",),
        ("metric_id",),
        lignes_financieres_par_mesure=True,
    ),
    Jeu(
        "mesures_historique",
        "MesuresHistorique",
        schema.M8_ENT_MESURES_HIST,
        "L'historique des mesures, une ligne par mesure et par construction de l'entrepôt.",
        (
            _c("construction_id", forme=EMPREINTE),
            _c("metric_id", forme=IDENTIFIANT),
            _c("construit_le", forme=INSTANT),
            _c("statut", forme=CODE),
            _c("valeur", forme=DECIMAL),
            _c("version_definition", forme=EMPREINTE),
            _c("dernier_fait_le", forme=INSTANT),
        ),
        ("construction_id", "metric_id"),
        ("construit_le", "construction_id", "metric_id"),
        lignes_financieres_par_mesure=True,
    ),
    Jeu(
        "chantiers",
        "Chantiers",
        schema.M8_ENT_DIM_CHANTIER,
        "Un chantier terminé : durées, verdict de matériaux de M6, marge réelle de M5 (portée financière). Aucun "
        "technicien.",
        (
            _c("wct_id", forme=IDENTIFIANT),
            _c("construction_id", forme=EMPREINTE),
            _c("devis_id", forme=IDENTIFIANT),
            _c("termine_le", forme=INSTANT),
            _c("duree_reelle_minutes", EDM_ENTIER),
            _c("duree_estimee_minutes", EDM_ENTIER),
            _c("statut_wct", forme=CODE),
            _c("variance_statut", forme=CODE),
            _c("signal_materiaux", EDM_BOOLEEN),
            _c("verdict_marge", forme=CODE, financiere=True),
            _c("marge_reelle_cad", forme=DECIMAL, financiere=True),
        ),
        ("wct_id",),
        ("termine_le", "wct_id"),
    ),
    Jeu(
        "devis",
        "Devis",
        schema.M8_ENT_FAIT_DEVIS,
        "Un devis : envoi, acceptation, constat sans réponse de M3 ; prix total arrêté par M3 (portée financière).",
        (
            _c("devis_id", forme=IDENTIFIANT),
            _c("construction_id", forme=EMPREINTE),
            _c("lead_id", forme=IDENTIFIANT),
            _c("envoye_le", forme=INSTANT),
            _c("accepte_le", forme=INSTANT),
            _c("prix_total_cad", forme=DECIMAL, financiere=True),
            _c("sans_reponse_statut", forme=CODE),
            _c("sans_reponse_constate_le", forme=INSTANT),
        ),
        ("devis_id",),
        ("devis_id",),
    ),
    Jeu(
        "leads",
        "Leads",
        schema.M8_ENT_DIM_LEAD,
        "Un lead : arrivée, qualification, clé de mesure utm_content. Aucun contact, aucune ville, aucun service.",
        (
            _c("lead_id", forme=IDENTIFIANT),
            _c("construction_id", forme=EMPREINTE),
            _c("recu_le", forme=INSTANT),
            _c("qualifie_le", forme=INSTANT),
            _c("utm_content", forme=IDENTIFIANT),
        ),
        ("lead_id",),
        ("lead_id",),
    ),
    Jeu(
        "contenus",
        "Contenus",
        schema.M8_ENT_MART_CONTENUS,
        "Un contenu exporté par M7 et ce qu'il a amené (leads de M1, devis de M3).",
        (
            _c("contenu_id", forme=IDENTIFIANT),
            _c("construction_id", forme=EMPREINTE),
            _c("utm_content", forme=IDENTIFIANT),
            _c("canal", forme=CODE),
            _c("wct_id", forme=IDENTIFIANT),
            _c("exporte_le", forme=INSTANT),
            _c("suivi", forme=CODE),
            _c("leads", EDM_ENTIER),
            _c("devis_envoyes", EDM_ENTIER),
            _c("devis_acceptes", EDM_ENTIER),
        ),
        ("contenu_id",),
        ("contenu_id",),
    ),
    Jeu(
        "constructions",
        "Constructions",
        schema.M8_ENT_CONSTRUCTIONS,
        "Le journal des constructions de l'entrepôt : version du schéma, du catalogue, empreinte des registres "
        "sources.",
        (
            _c("rang", EDM_ENTIER),
            _c("construction_id", forme=EMPREINTE),
            _c("version_schema", EDM_ENTIER),
            _c("version_catalogue", forme=EMPREINTE),
            _c("empreinte_registres", forme=EMPREINTE),
            _c("construit_le", forme=INSTANT),
            _c("nb_mesures", EDM_ENTIER),
        ),
        ("rang",),
        ("rang",),
    ),
)
JEUX: dict[str, Jeu] = {jeu.nom: jeu for jeu in _JEUX}
PAR_ENTITE: dict[str, Jeu] = {jeu.entite: jeu for jeu in _JEUX}


def verifier_coherence() -> list[str]:
    """Écarts entre les jeux déclarés et les tables réelles : une colonne déclarée absente de la table, un type
    différent,
    une clé inconnue. Vide si tout est cohérent (un test l'exige)."""
    ecarts: list[str] = []
    for jeu in JEUX.values():
        colonnes_table = {c.name: c for c in jeu.table.columns}
        for colonne in jeu.colonnes:
            reelle = colonnes_table.get(colonne.nom)
            if reelle is None:
                ecarts.append(f"{jeu.nom}.{colonne.nom} : absente de la table {jeu.table.name}")
                continue
            if isinstance(reelle.type, BigInteger):
                attendu = EDM_ENTIER_LONG
            elif isinstance(reelle.type, Integer):
                attendu = EDM_ENTIER
            elif isinstance(reelle.type, Boolean):
                attendu = EDM_BOOLEEN
            else:
                attendu = EDM_TEXTE
            if attendu != colonne.edm:
                ecarts.append(f"{jeu.nom}.{colonne.nom} : type {colonne.edm} déclaré, {attendu} dans la table")
        for cle in (*jeu.cles, *jeu.ordre):
            if cle not in colonnes_table:
                ecarts.append(f"{jeu.nom} : colonne de clé ou d'ordre inconnue : {cle}")
    return ecarts
