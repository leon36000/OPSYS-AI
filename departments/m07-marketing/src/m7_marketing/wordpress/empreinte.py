"""Empreinte du contenu d'un article WordPress (`opsys-content/v1`), la même chez OPSYS et dans le plugin.

C'est ELLE que la direction approuve et que le plugin recompare, au point de sortie, au contenu réellement stocké :
tout changement du titre, du corps, de l'extrait, de l'adresse, du type ou de l'image à la une après l'approbation
change l'empreinte et bloque la publication.

Encodage canonique (UTF-8), conçu pour être identique en PHP et en Python sans dépendre d'un sérialiseur JSON :

    opsys-content/v1
    type:<n>:<valeur>
    titre:<n>:<valeur>
    contenu:<n>:<valeur>
    extrait:<n>:<valeur>
    slug:<n>:<valeur>
    image_a_la_une_sha256:<n>:<valeur>

où `<n>` est le NOMBRE D'OCTETS UTF-8 de la valeur (un LF dans une valeur ne peut donc pas imiter une autre ligne),
chaque
ligne se termine par LF, et l'empreinte est le SHA-256 hexadécimal minuscule de l'ensemble. L'image à la une est le
SHA-256 des octets du média (vide s'il n'y en a pas). Les valeurs sont celles que le plugin STOCKE (après
assainissement) :
c'est pourquoi l'empreinte qui compte est celle que le plugin rend à la création du brouillon.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

ENTETE = "opsys-content/v1"
CHAMPS = ("type", "titre", "contenu", "extrait", "slug", "image_a_la_une_sha256")


def canonique(champs: Mapping[str, str]) -> bytes:
    inconnus = sorted(set(champs) - set(CHAMPS))
    manquants = [c for c in CHAMPS if c not in champs]
    if inconnus or manquants:
        raise ValueError(f"champs d'empreinte : inconnus {inconnus}, manquants {manquants}")
    morceaux = [ENTETE + "\n"]
    for nom in CHAMPS:
        valeur = champs[nom]
        if not isinstance(valeur, str):
            raise TypeError(f"{nom} : texte attendu")
        morceaux.append(f"{nom}:{len(valeur.encode('utf-8'))}:{valeur}\n")
    return "".join(morceaux).encode("utf-8")


def empreinte_contenu(champs: Mapping[str, str]) -> str:
    return hashlib.sha256(canonique(champs)).hexdigest()
