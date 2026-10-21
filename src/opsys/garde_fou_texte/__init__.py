"""Garde-fou de texte du socle (PLAN T4.17-c) : un catalogue de familles de règles, que chaque département choisit.

Avant ce module, deux départements contrôlaient chacun leurs textes avec leurs propres motifs : M1 (réponse à un
client : prix, date, engagement, aveu) et M7 (texte public : adresse, coordonnées, nom de client, identifiant interne,
prix, chiffre non sourcé, garantie non validée, date promise, exagération, lien). Le code partagé vit dans le socle
(`docs/architecture/DEPARTEMENTS.md`) : aucun département n'importe l'autre.

Doctrine (AGENTS.md « le code calcule, le LLM orchestre ; fail-closed ») :

- **Une famille est nommée, et le refus nomme la règle.** Chaque famille a un `nom` (l'identifiant qu'un département
  cite), un code de refus stable (`regle`, un par famille) et un `libelle` : ce qu'elle interdit, en une phrase. Un
  refus dit toujours quoi retirer (`Violation.detail`).
- **Un département choisit ses familles** (`profil`). Un texte public de M7 n'a pas les mêmes règles qu'une réponse de
  M1 : « nous étudions votre budget » est permis à M1, refusé à M7. Le socle ne décide pas pour lui. Un nom de famille
  inconnu est une erreur de programmation, levée au chargement du profil, jamais un refus silencieux d'une règle.
- **Ordre fixe.** Les familles d'un profil sont lues dans l'ordre du catalogue (`FAMILLES`), quel que soit l'ordre
  où le département les a citées : même texte, même verdict, même premier refus.
- **Les règles sont des motifs, jamais un jugement.** Aucune horloge, aucun modèle, aucune entrée-sortie : un texte
  propre est accepté, un texte douteux est refusé.

Le prix et la date existent à deux niveaux, gardés distincts parce que leurs motifs ne disent pas la même chose :
`prix_montant` (réponse à un client : un montant, une fourchette) et `prix_offre` (texte public : tout prix, tarif,
rabais ou offre gratuite, même sans montant) ; `date_execution` (un moment lié à un verbe d'exécution de chantier) et
`promesse_de_date` (toute date, tout délai).

Les codes de refus sont ceux que les départements rendaient déjà (`REJ-INTERDIT-PRIX` pour `prix_montant`, `REJ-PRIX`
pour `prix_offre`, etc.) : leurs verdicts, leurs corpus et leurs tests restent inchangés.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType

from . import confidentialite, droit, engagements, promesses
from ._types import Contexte, Famille, Formes, Violation, apostrophes_droites
from .engagements import decouper_segments

__all__ = [
    "AVEU", "AVIS_LEGAL", "ADRESSE", "CHIFFRE_NON_SOURCE", "COORDONNEES", "DATE_EXECUTION", "ENGAGEMENT",
    "EXAGERATION", "FAMILLES", "GARANTIE_NON_VALIDEE", "IDENTIFIANT_INTERNE", "LIEN", "LONGUEUR", "NOM_CLIENT",
    "PROMESSE_DE_DATE", "PRIX_MONTANT", "PRIX_OFFRE", "TEXTE_MAX_CONTROLE", "TEXTE_VIDE", "Contexte", "Famille",
    "Profil", "Violation", "apostrophes_droites", "controler", "decouper_segments", "motif_de_refus",
    "premiere_violation", "profil",
]

TEXTE_VIDE = "texte_vide"
LONGUEUR = "longueur"
LIEN = "lien"
ADRESSE = "adresse"
COORDONNEES = "coordonnees"
NOM_CLIENT = "nom_client"
IDENTIFIANT_INTERNE = "identifiant_interne"
PRIX_MONTANT = "prix_montant"
PRIX_OFFRE = "prix_offre"
CHIFFRE_NON_SOURCE = "chiffre_non_source"
GARANTIE_NON_VALIDEE = "garantie_non_validee"
DATE_EXECUTION = "date_execution"
PROMESSE_DE_DATE = "promesse_de_date"
EXAGERATION = "exageration"
ENGAGEMENT = "engagement"
AVEU = "aveu"
AVIS_LEGAL = "avis_legal"

# Aucune plateforme n'accepte un tel texte (les plafonds vont de 900 à 2 000 caractères) : au-delà, un profil qui le
# demande (`texte_max`) refuse le texte sans le lire par les motifs, pour qu'un texte démesuré ne puisse pas occuper
# le processus.
TEXTE_MAX_CONTROLE = 5000


def _texte_vide(formes: Formes, _contexte: Contexte) -> str | None:
    return None if formes.texte.strip() else "le texte est vide"


def _longueur(formes: Formes, contexte: Contexte) -> str | None:
    if contexte.longueur_max is not None and len(formes.texte) > contexte.longueur_max:
        return f"{len(formes.texte)} caractères, {contexte.longueur_max} au plus"
    return None


def _indexer(familles: Iterable[Famille]) -> Mapping[str, Famille]:
    """Le catalogue indexé par nom, dans l'ordre d'évaluation. Un nom ou un code de refus en double est une erreur de
    programmation (un refus doit nommer UNE règle) : elle est levée à l'import."""
    familles = tuple(familles)
    noms = [f.nom for f in familles]
    regles = [f.regle for f in familles]
    if len(set(noms)) != len(noms) or len(set(regles)) != len(regles):
        raise ValueError("catalogue du garde-fou de texte : nom ou code de refus en double")
    return MappingProxyType({f.nom: f for f in familles})


def _familles() -> tuple[Famille, ...]:
    return (
        Famille(TEXTE_VIDE, "REJ-TEXTE-VIDE", "le texte ne peut pas être vide", _texte_vide, bloquante=True),
        Famille(LONGUEUR, "REJ-LONGUEUR", "le texte respecte la longueur maximale de la plateforme", _longueur),
        Famille(
            LIEN, "REJ-LIEN", "aucun lien dans le texte (le lien de suivi est ajouté par le code)",
            confidentialite.lien,
        ),
        Famille(
            ADRESSE, "REJ-ADRESSE", "aucune adresse (numéro civique, rue nommée, code postal, coordonnées GPS)",
            confidentialite.adresse,
        ),
        Famille(
            COORDONNEES, "REJ-COORDONNEES", "aucun courriel ni numéro de téléphone", confidentialite.coordonnees,
        ),
        Famille(
            NOM_CLIENT, "REJ-NOM-CLIENT", "aucun nom de client (civilité + nom, famille, « chez X Y », @mention)",
            confidentialite.nom_client,
        ),
        Famille(
            IDENTIFIANT_INTERNE, "REJ-IDENTIFIANT-INTERNE",
            "aucun identifiant interne (chantier, lead, devis, technicien)", confidentialite.identifiant_interne,
        ),
        Famille(
            PRIX_MONTANT, "REJ-INTERDIT-PRIX", "aucun prix, montant ni fourchette de prix dans une réponse",
            engagements.prix_montant,
        ),
        Famille(
            PRIX_OFFRE, "REJ-PRIX", "aucun prix, montant, tarif, rabais ni offre gratuite", promesses.prix_offre,
        ),
        Famille(
            CHIFFRE_NON_SOURCE, "REJ-CHIFFRE-NON-SOURCE",
            "aucun chiffre avec une unité (pieds, heures, ans, %) : les chiffres viennent d'un outil",
            promesses.chiffre_non_source,
        ),
        Famille(
            GARANTIE_NON_VALIDEE, "REJ-GARANTIE-NON-VALIDEE",
            "aucune garantie, sauf un énoncé validé par l'entreprise (profil de marque)",
            promesses.garantie_non_validee,
        ),
        Famille(
            DATE_EXECUTION, "REJ-INTERDIT-DATE", "aucune date ni délai d'exécution des travaux dans une réponse",
            engagements.date_execution,
        ),
        Famille(
            PROMESSE_DE_DATE, "REJ-PROMESSE-DE-DATE",
            "aucune date ni promesse de délai (demain, d'ici, dans N jours, avant le…)", promesses.promesse_de_date,
        ),
        Famille(
            EXAGERATION, "REJ-EXAGERATION",
            "aucune exagération non vérifiable (meilleur, numéro 1, imbattable, 100 %…)", promesses.exageration,
        ),
        Famille(
            ENGAGEMENT, "REJ-INTERDIT-ENGAGEMENT", "aucune promesse ferme (engagement, garantie, parole donnée)",
            engagements.engagement,
        ),
        Famille(AVEU, "REJ-INTERDIT-AVEU", "aucun aveu de faute ni de responsabilité", engagements.aveu),
        Famille(
            AVIS_LEGAL, "REJ-INTERDIT-AVIS-LEGAL",
            "aucun avis légal (droits, loi, recours, avocat, tribunal, contrat)", droit.avis_legal,
        ),
    )


FAMILLES: Mapping[str, Famille] = _indexer(_familles())


@dataclasses.dataclass(frozen=True)
class Profil:
    """Les familles qu'un département applique à un type de texte, dans l'ordre du catalogue.

    `texte_max` : longueur au-delà de laquelle le texte est refusé (famille `longueur`) sans être lu par les autres
    règles ; `None` pour ne pas plafonner."""

    nom: str
    familles: tuple[Famille, ...]
    texte_max: int | None = None

    def __contains__(self, nom: object) -> bool:
        return any(f.nom == nom for f in self.familles)

    def libelles(self) -> dict[str, str]:
        """`{code de refus: ce que la famille interdit}`, dans l'ordre d'évaluation."""
        return {f.regle: f.libelle for f in self.familles}


def profil(nom: str, familles: Iterable[str], *, texte_max: int | None = None) -> Profil:
    """Le profil `nom` : les familles citées, relues dans l'ordre du catalogue. Lève `ValueError` pour une famille
    inconnue ou citée deux fois, ou pour un `texte_max` sans la famille `longueur` (le refus n'aurait pas de nom)."""
    voulues = list(familles)
    inconnues = [n for n in voulues if n not in FAMILLES]
    if inconnues:
        raise ValueError(f"profil {nom!r} : famille inconnue {inconnues} (catalogue : {', '.join(FAMILLES)})")
    if len(set(voulues)) != len(voulues):
        raise ValueError(f"profil {nom!r} : une famille est citée deux fois")
    if texte_max is not None and LONGUEUR not in voulues:
        raise ValueError(f"profil {nom!r} : texte_max exige la famille {LONGUEUR!r}")
    return Profil(nom, tuple(f for n, f in FAMILLES.items() if n in voulues), texte_max)


def _violations(texte: str, profil_applique: Profil, contexte: Contexte | None) -> Iterator[Violation]:
    if not isinstance(texte, str):
        raise TypeError("le texte à contrôler doit être une chaîne")
    ctx = contexte or Contexte()
    formes = Formes(texte, ctx)
    for famille in profil_applique.familles:
        if famille.bloquante and (detail := famille.detecter(formes, ctx)) is not None:
            yield Violation(famille.nom, famille.regle, detail)
            return
    if profil_applique.texte_max is not None and len(texte) > profil_applique.texte_max:
        longueur = FAMILLES[LONGUEUR]
        yield Violation(
            longueur.nom, longueur.regle,
            f"{len(texte)} caractères, {profil_applique.texte_max} au plus pour tout texte",
        )
        return
    for famille in profil_applique.familles:
        if famille.bloquante:
            continue
        if (detail := famille.detecter(formes, ctx)) is not None:
            yield Violation(famille.nom, famille.regle, detail)


def controler(texte: str, profil_applique: Profil, contexte: Contexte | None = None) -> tuple[Violation, ...]:
    """Les règles que `texte` viole, dans l'ordre du catalogue ; vide si le texte est accepté.

    Ne lève rien pour un texte étrange : un texte qui n'est pas une chaîne est le seul cas d'erreur de programmation
    (`TypeError`), tout le reste est un verdict."""
    return tuple(_violations(texte, profil_applique, contexte))


def premiere_violation(
    texte: str, profil_applique: Profil, contexte: Contexte | None = None
) -> Violation | None:
    """La première règle violée dans l'ordre du catalogue, ou `None` : les familles suivantes ne sont pas lues."""
    return next(_violations(texte, profil_applique, contexte), None)


def motif_de_refus(violations: Iterable[Violation]) -> str:
    """Le refus, en une phrase qui nomme chaque règle violée (vide s'il n'y en a aucune)."""
    return " ; ".join(f"{v.regle} ({v.detail})" for v in violations)
