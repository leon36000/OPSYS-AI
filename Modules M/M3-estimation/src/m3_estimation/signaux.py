"""Signal de relance « DEMANDE_ENTREES_VISUELLES » du module M3-estimation.

Ce module construit l'unique signal sortant ratifié par l'architecture §2.7 :
quand une estimation est BLOQUÉE faute d'entrées visuelles exploitables, M3
demande les éléments manquants par ce signal, et rien d'autre.

Deux contraintes fondent ce fichier :

1. ``devis_id`` est un PARAMÈTRE, jamais une donnée fabriquée ici. Le signal
   l'exige, et il est produit par la story S007 : un devis BLOQUÉ en possède
   un lui aussi — dérivé du lead et de l'empreinte du marqueur, indépendamment
   du blocage. Le module le REÇOIT et ne le fabrique jamais : « fourni, jamais
   deviné », comme le barème et les seuils.
2. La fréquence d'émission est bornée : UN signal par estimation, jamais de
   relance en boucle. ``emission_count`` vaut donc toujours 1 en v1.

Aucun import inter-modules (décision #109) : seul le catalogue de verdicts du
paquet est importé, en relatif.
"""

from . import verdicts

# Provenance : section 2.7 de l'architecture du module M3 — liste FERMÉE des
# cinq clés du signal, dans l'ordre ratifié.
CHAMPS_SIGNAL = ("type", "lead_id", "devis_id", "elements_manquants", "emission_count")
TYPE_SIGNAL = "DEMANDE_ENTREES_VISUELLES"
EMISSION_UNIQUE = 1


def construire_signal_relance(lead_id, devis_id, elements_manquants):
    """Construit le signal « DEMANDE_ENTREES_VISUELLES » ou rend un verdict.

    Retourne ``(signal, None)`` quand les trois paramètres sont valides,
    ``(None, verdict)`` sinon. Rien n'est produit dès qu'un contrôle échoue.

    Contrôles, dans l'ordre :
      1. ``lead_id`` et ``devis_id`` sont des chaînes non vides ;
      2. ``elements_manquants`` est une liste non vide dont chaque élément est
         une chaîne non vide ;
      3. toute faute donne ``REJ-SIGNAL-INVALIDE``, le détail nommant le
         champ fautif.
    """
    if not isinstance(lead_id, str) or not lead_id.strip():
        return None, verdicts.construire_verdict(
            "REJ-SIGNAL-INVALIDE",
            detail="lead_id doit être une chaîne non vide",
        )
    if not isinstance(devis_id, str) or not devis_id.strip():
        return None, verdicts.construire_verdict(
            "REJ-SIGNAL-INVALIDE",
            detail="devis_id doit être une chaîne non vide",
        )
    # Un signal qui ne dit pas ce qui manque n'aide personne : la liste vide est refusée.
    if not isinstance(elements_manquants, list) or not elements_manquants:
        return None, verdicts.construire_verdict(
            "REJ-SIGNAL-INVALIDE",
            detail="elements_manquants doit être une liste non vide",
        )
    for element in elements_manquants:
        if not isinstance(element, str) or not element.strip():
            return None, verdicts.construire_verdict(
                "REJ-SIGNAL-INVALIDE",
                detail="elements_manquants ne contient que des chaînes non vides",
            )
    signal = {
        "type": TYPE_SIGNAL,
        "lead_id": lead_id,
        "devis_id": devis_id,
        # Copie de la liste reçue : jamais la liste elle-même, qu'un appelant pourrait muter après coup.
        "elements_manquants": list(elements_manquants),
        "emission_count": EMISSION_UNIQUE,
    }
    return signal, None


__all__ = [
    "CHAMPS_SIGNAL",
    "TYPE_SIGNAL",
    "EMISSION_UNIQUE",
    "construire_signal_relance",
]
