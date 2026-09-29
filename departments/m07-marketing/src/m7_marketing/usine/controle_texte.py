"""Contrôle en code d'un texte destiné au public (PLAN T4.17, M7.3 : « contrôle de marque et de confidentialité »).

Doctrine (AGENTS.md « le code calcule, le LLM orchestre », DEFINITION-PRODUIT §7 M7 « Blocages : promesse non
vérifiable, garantie ou prix inventés, photo de client sans autorisation, adresse ou visage ou plaque
visibles, exagération ») :

  - Un texte est composé par le code (gabarits, `gabarits.py`) ou rédigé par le modèle (`textes` de
    `m7_proposer_contenus_chantier`). Dans les deux cas il passe ICI avant d'entrer dans la file : la source
    du texte ne change rien à ce qu'il a le droit de dire. Un contenu refusé n'existe pas (aucun
    enregistrement) ; le refus NOMME chaque règle violée et ce qu'il faut retirer.
  - Les règles sont des motifs, jamais un jugement : même texte, même verdict. Un texte propre est accepté,
    un texte douteux est refusé (fail-closed) — l'agent le récrit, ou le propriétaire l'écrit à la main.

Les motifs ne sont plus écrits ici (PLAN T4.17-c) : ils vivent dans le socle (`opsys.garde_fou_texte`), avec ceux
du garde-fou de M1, en familles nommées. M7 choisit les siennes (`PROFIL_TEXTE_PUBLIC`) : adresse, coordonnées, nom
du client, identifiant interne, prix ou offre, chiffre non sourcé, garantie non validée, promesse de date,
exagération, lien, longueur. Un texte public n'a pas les mêmes règles qu'une réponse à un client (M1 : prix chiffré,
date d'exécution, engagement, aveu, avis légal) ; aucun département n'importe l'autre. Ce module garde les noms
que M7 utilisait (`controler_texte`, `ContexteControle`, `REGLE_*`), pour que rien d'autre n'ait à changer.

Limites documentées, jamais cachées :
  - Le nom du client n'est PAS dans le WCT (M4 ne le porte pas). Le contrôle reconnaît les FORMES qui
    désignent un client (civilité + nom, « la famille X », « chez X Y », « client : X », @mention) et les
    noms et identifiants qu'on lui fournit (`ContexteControle.noms_clients`, `identifiants`). Un prénom
    seul, sans civilité, dans une phrase ordinaire, n'est pas détectable : la revue du propriétaire (N3)
    reste la dernière barrière, et le texte du gabarit n'en contient jamais.
  - Un motif ne comprend pas le sens : « meilleur » est refusé même dans une phrase inoffensive. C'est le
    prix du fail-closed ; la règle est nommée, donc contournable par une phrase plus sobre.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

from opsys import garde_fou_texte as socle

# Les familles que M7 applique à un texte public, avec le plafond absolu au-delà duquel un texte est refusé sans
# être lu (aucune plateforme n'accepte un tel texte : les plafonds vont de 900 à 2 000 caractères).
TEXTE_MAX_CONTROLE = socle.TEXTE_MAX_CONTROLE

PROFIL_TEXTE_PUBLIC = socle.profil(
    "m7_texte_public",
    (
        socle.TEXTE_VIDE,
        socle.LONGUEUR,
        socle.LIEN,
        socle.ADRESSE,
        socle.COORDONNEES,
        socle.NOM_CLIENT,
        socle.IDENTIFIANT_INTERNE,
        socle.PRIX_OFFRE,
        socle.CHIFFRE_NON_SOURCE,
        socle.GARANTIE_NON_VALIDEE,
        socle.PROMESSE_DE_DATE,
        socle.EXAGERATION,
    ),
    texte_max=TEXTE_MAX_CONTROLE,
)

REGLE_TEXTE_VIDE = socle.FAMILLES[socle.TEXTE_VIDE].regle
REGLE_LONGUEUR = socle.FAMILLES[socle.LONGUEUR].regle
REGLE_LIEN = socle.FAMILLES[socle.LIEN].regle
REGLE_ADRESSE = socle.FAMILLES[socle.ADRESSE].regle
REGLE_COORDONNEES = socle.FAMILLES[socle.COORDONNEES].regle
REGLE_NOM_CLIENT = socle.FAMILLES[socle.NOM_CLIENT].regle
REGLE_IDENTIFIANT_INTERNE = socle.FAMILLES[socle.IDENTIFIANT_INTERNE].regle
REGLE_PRIX = socle.FAMILLES[socle.PRIX_OFFRE].regle
REGLE_CHIFFRE = socle.FAMILLES[socle.CHIFFRE_NON_SOURCE].regle
REGLE_GARANTIE = socle.FAMILLES[socle.GARANTIE_NON_VALIDEE].regle
REGLE_DATE = socle.FAMILLES[socle.PROMESSE_DE_DATE].regle
REGLE_EXAGERATION = socle.FAMILLES[socle.EXAGERATION].regle

# Ce que chaque règle interdit, en une phrase : montré au modèle qui rédige (`m7_lire_matiere_chantier`) et repris
# dans le refus. L'ordre est celui de l'évaluation, donc celui des violations rendues.
LIBELLES_REGLES: dict[str, str] = PROFIL_TEXTE_PUBLIC.libelles()

Violation = socle.Violation
ContexteControle = socle.Contexte
motif_de_refus = socle.motif_de_refus


def controler_texte(texte: str, contexte: ContexteControle | None = None) -> tuple[Violation, ...]:
    """Les règles que `texte` viole, dans l'ordre de `LIBELLES_REGLES` ; vide si le texte est accepté.

    Ne lève rien pour un texte étrange : un texte qui n'est pas une chaîne est le seul cas d'erreur de
    programmation (`TypeError`), tout le reste est un verdict."""
    return socle.controler(texte, PROFIL_TEXTE_PUBLIC, contexte)
