"""Interface explicite vers les contrats canoniques de variance matériaux M6.

Aucun outil/factory M6 ni calcul recopié : validateurs et projections sont les
fonctions originales. Leur import reste transitivement lié aux adaptateurs SQL
M6 ; cette interface ne revendique pas un graphe d’import strictement pur.
Les appelants fournissent leurs copies de sources et gardent leurs propres accès.
"""

from m6_material_control import besoins_prevus
from m6_material_control import classement_variance_appareil as _annotations

Refus = _annotations.Refus
REGISTRE = _annotations.REGISTRE
REGISTRE_REFUS = _annotations.REGISTRE_REFUS
texte = _annotations.texte
entier = _annotations.entier
motif_valide = _annotations.motif_valide
reference = _annotations.reference
reference_valide = _annotations.reference_valide
selection = _annotations.selection
pour_objet = _annotations.pour_objet
projection = _annotations.projection
source_projection = _annotations.source_projection
valider_source = _annotations.valider_source
empreinte_charge = _annotations.encodage.empreinte
hash_valide = _annotations.preuves._hash
besoin_pour_devis = besoins_prevus.pour_devis
