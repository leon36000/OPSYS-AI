"""Garde-fou des interdits de M1 : ce qu'un texte destiné à un client ne dit jamais (PLAN T4.17-c).

Les règles ne sont plus ici : elles vivent dans le socle (`opsys.garde_fou_texte`), qui réunit les familles de M1 et
celles de M7. M1 choisit les siennes (`PROFIL_REPONSE_CLIENT`) : le prix chiffré, la date d'exécution, l'engagement
ferme, l'aveu et l'avis légal. Un texte public de M7 n'a pas les mêmes règles ; aucun département n'importe l'autre.

L'avis légal (« M1 ne doit jamais donner un avis légal, fiscal ou contractuel », DEFINITION-PRODUIT §7) n'était vérifié
que sur le gabarit de plainte (`plaintes.py`, T4.5). Il l'est désormais partout où M1 passe un texte ici : brouillons
de qualification, questions du profil, gabarits, résumés de transfert, et l'outil `m1_verifier_garde_fou`.

Ordre d'évaluation, fixé par le catalogue du socle et documenté : PRIX → DATE → ENGAGEMENT → AVEU → AVIS LÉGAL. Le
verdict est celui de la première règle violée : même texte, même code.
"""

from opsys import garde_fou_texte

from . import verdicts

__all__ = ["PROFIL_REPONSE_CLIENT", "verifier_sortie"]

PROFIL_REPONSE_CLIENT = garde_fou_texte.profil(
    "m1_reponse_client",
    (
        garde_fou_texte.PRIX_MONTANT,
        garde_fou_texte.DATE_EXECUTION,
        garde_fou_texte.ENGAGEMENT,
        garde_fou_texte.AVEU,
        garde_fou_texte.AVIS_LEGAL,
    ),
)

# Les deux fonctions d'aide de l'ancien module, que les tests de M1 atteignent encore par leur nom d'origine.
_normaliser = garde_fou_texte.apostrophes_droites
_decouper_segments = garde_fou_texte.decouper_segments


def verifier_sortie(texte: str, registre=None, horodatage: str | None = None) -> dict:
    if not isinstance(texte, str):
        raise TypeError("Le texte doit être une chaîne de caractères")

    violation = garde_fou_texte.premiere_violation(texte, PROFIL_REPONSE_CLIENT)
    if violation is None:
        return verdicts.construire_verdict("OK")

    verdict = verdicts.construire_verdict(violation.regle, detail=violation.detail)

    # Journalisation dans le registre si violation et registre fourni
    if registre is not None:
        if horodatage is None:
            raise ValueError("Un horodatage doit être fourni lorsque le registre est utilisé")
        entree = {
            "type_entree": "alerte",
            "horodatage": horodatage,
            "payload": {"code_verdict": violation.regle}
        }
        registre.ajouter(entree)

    return verdict
