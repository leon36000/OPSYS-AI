"""La forme d'une affaire, commune au core et à M10 (PLAN T4.18-b).

Une affaire s'identifie de deux façons, jamais d'une troisième :

- un LEAD : le ``lead_id`` que M1 donne au lead qu'il qualifie (une empreinte de 64 caractères pour un lead venu d'un
  SMS, un identifiant plus court pour un lead saisi à la main) ;
- une OPPORTUNITÉ : ``<lead d'origine>~opp~<wct_id>``, que M2 ouvre pour le chantier suivant d'un client déjà connu
  (``m2_revenue_crm.outils``). M2 et M3 publient cet identifiant tel quel ; M1 n'en publie jamais.

La forme est BORNÉE et FERMÉE. Le lead compte au plus 64 caractères, le ``wct_id`` au plus 128, soit 197 pour
l'affaire entière. Seuls passent les lettres latines, les chiffres et ``._:-`` (le tilde n'existe que dans le
séparateur ``~opp~``) : ni espace, ni retour à la ligne, ni caractère de contrôle ou de sens d'écriture, ni signe qu'un
interpréteur, une adresse ou un journal prendrait pour autre chose qu'un identifiant. Un identifiant qui entre dans
un prompt, un journal ou une clé de session ne peut donc rien injecter.

Cette forme est écrite DEUX fois, mot pour mot : ici, et dans ``core/src/context-engine/opsys-contexte-paquet.ts``
(``AFFAIRE_ID`` pour un identifiant, ``AFFAIRE_LINE`` pour la ligne ``affaire_id: ...`` d'une demande). Trois choses
les gardent identiques : un test du socle compare le texte des deux motifs, et les deux côtés rejouent la MÊME liste
de cas (``core/src/context-engine/opsys-contexte.affaires.json``, lue par ``test_affaire.py`` et par
``opsys-contexte-affaire.test.ts``). Changer la forme est un choix des deux côtés à la fois.

Limite connue : la forme n'admet qu'UN niveau d'opportunité. M2 suffixe le lead du WCT, qui peut déjà être une
opportunité : ``<lead>~opp~<wct 1>~opp~<wct 2>`` serait refusée (quarantaine visible du consommateur), et un
paquet ne s'assemblerait pas pour elle. Le correctif est chez M2 (suffixer le lead d'origine), pas ici.

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

import re

SEPARATEUR_OPPORTUNITE = "~opp~"
LONGUEUR_LEAD_MAX = 64
LONGUEUR_WCT_MAX = 128
LONGUEUR_AFFAIRE_MAX = LONGUEUR_LEAD_MAX + len(SEPARATEUR_OPPORTUNITE) + LONGUEUR_WCT_MAX

GENRE_LEAD = "lead"
GENRE_OPPORTUNITE = "opportunite"

# Ces deux motifs sont recopiés tels quels par le core (`AFFAIRE_ID`) : un test du socle compare leur texte.
FORME_LEAD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
FORME_AFFAIRE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}(?:~opp~[A-Za-z0-9][A-Za-z0-9._:-]{0,127})?$")


def est_lead(valeur: object) -> bool:
    """Vrai pour un ``lead_id`` seul (jamais une opportunité) : ce que M1 publie."""
    # `fullmatch`, jamais `match` : `$` accepterait un retour à la ligne final.
    return isinstance(valeur, str) and FORME_LEAD.fullmatch(valeur) is not None


def valide(valeur: object) -> bool:
    """Vrai pour une affaire : un lead, ou l'opportunité que M2 ouvre pour lui."""
    return isinstance(valeur, str) and FORME_AFFAIRE.fullmatch(valeur) is not None


def genre(valeur: object) -> str | None:
    """``lead`` ou ``opportunite`` pour une affaire valide, sinon ``None`` : rien n'est deviné d'une forme invalide."""
    if not valide(valeur):
        return None
    return GENRE_OPPORTUNITE if SEPARATEUR_OPPORTUNITE in str(valeur) else GENRE_LEAD


def est_opportunite(valeur: object) -> bool:
    return genre(valeur) == GENRE_OPPORTUNITE
