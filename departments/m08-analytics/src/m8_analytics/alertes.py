"""Alertes de qualité/fraîcheur M8 (T3.1, DEFINITION-PRODUIT.md §7 M8.9 : « chaque alerte
propose une action, pas seulement un problème »).

``proposer_action`` construit un objet de PRÉSENTATION structuré {quoi, a_qui, pourquoi, preuve}
à partir d'une évaluation non ``None`` de ``qualite.py`` — il ne fait jamais rien d'autre. M8 ne
décide pas (c'est M9) et n'agit jamais lui-même sur un autre département : ``a_qui`` NOMME un
destinataire suggéré (le département propriétaire de la métrique, tel que déclaré dans le
registre), ce module n'appelle, n'écrit ni ne notifie personne. Comme pour ``SignalXmR``
(DA-M8-07, ``conformite.py::verifier_aucune_cause_signalee``), ``pourquoi`` documente la RÈGLE ou
le SEUIL franchi — un fait mesuré et chiffré — jamais une cause métier ou un responsable ; aucune
clé ``cause``/``responsable``/``raison_signalee`` n'apparaît ici, et la garde AST transversale du
paquet le vérifie sur tout ``src/m8_analytics``.

T3.1-suite : ``proposer_action`` gère désormais 5 verdicts (absence, péremption, hors plage,
doublon d'observation, incohérence entre séries). Les deux derniers ne sont PAS encore publiés
sur le bus ``m8.alerte_proposee`` par ``outils.py`` — le schéma du catalogue
(``src/opsys/evenements/catalogue/m8.alerte_proposee.json``) fige encore ``type_alerte`` et
``preuve`` aux trois premiers, volontairement non étendu par ce lot (portée du worktree). Ces deux
alertes restent pleinement utilisables via la réponse de l'outil et le digest quotidien
(``digest.py``).

Module PUR (ADR-0009) : aucun import d'``opsys``.
"""

from __future__ import annotations

from typing import Any

from . import qualite

__all__ = ["proposer_action"]


def proposer_action(evaluation: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    """Alerte proposée pour une évaluation NON None de ``qualite.py`` (l'appelant ne construit
    une alerte que lorsqu'il y a effectivement quelque chose à signaler) et la définition de
    registre associée (``contrats.CHAMPS_DEFINITION_REGISTRE``, pour ``a_qui``/``source``).

    Fail-closed : un verdict d'évaluation sans correspondance connue lève ``ValueError`` plutôt
    que d'inventer un texte d'action — jamais une action devinée pour un signal inconnu.
    """
    verdict = evaluation["verdict"]
    metric_id = evaluation["metric_id"]
    a_qui = definition["departement_proprietaire"]

    if verdict == qualite.VERDICT_DONNEE_ABSENTE:
        quoi = f"Aucune valeur reçue pour {metric_id}."
        pourquoi = f"n = {evaluation['n']} : aucune donnée exploitable dans le registre."
        preuve: dict[str, Any] = {"metric_id": metric_id, "n": evaluation["n"]}
    elif verdict == qualite.VERDICT_DONNEE_PERIMEE:
        quoi = f"Valeur périmée pour {metric_id}."
        pourquoi = (
            f"âge observé {evaluation['fraicheur_jours']:.2f} jours > fraîcheur attendue "
            f"{evaluation['fraicheur_attendue_jours']} jours."
        )
        preuve = {
            "metric_id": metric_id,
            "fraicheur_jours": evaluation["fraicheur_jours"],
            "fraicheur_attendue_jours": evaluation["fraicheur_attendue_jours"],
        }
    elif verdict == qualite.VERDICT_HORS_PLAGE:
        quoi = f"Valeur hors plage pour {metric_id}."
        pourquoi = (
            f"valeur observée {evaluation['valeur']} hors de "
            f"[{evaluation['plage_min']}, {evaluation['plage_max']}]."
        )
        preuve = {
            "metric_id": metric_id,
            "valeur": evaluation["valeur"],
            "plage_min": evaluation["plage_min"],
            "plage_max": evaluation["plage_max"],
        }
    elif verdict == qualite.VERDICT_DOUBLON:
        horodatages = evaluation["horodatages_doublons"]
        quoi = f"Observations en double pour {metric_id}."
        pourquoi = (
            f"{len(horodatages)} horodatage(s) portent plus d'une observation dans le registre : "
            f"{', '.join(sorted(horodatages))}."
        )
        preuve = {
            "metric_id": metric_id,
            "horodatages_doublons": horodatages,
            "n_observations": evaluation["n_observations"],
        }
    elif verdict == qualite.VERDICT_INCOHERENT:
        quoi = f"Valeur incohérente avec ses composantes pour {metric_id}."
        pourquoi = (
            f"valeur observée {evaluation['valeur']} ≠ somme attendue des composantes "
            f"{evaluation['valeur_attendue']:.4f} (écart {evaluation['ecart']:+.4f}, "
            f"tolérance {evaluation['tolerance']})."
        )
        preuve = {
            "metric_id": metric_id,
            "valeur": evaluation["valeur"],
            "valeur_attendue": evaluation["valeur_attendue"],
            "ecart": evaluation["ecart"],
            "tolerance": evaluation["tolerance"],
            "composantes": evaluation["composantes"],
        }
    else:
        raise ValueError(f"verdict d'évaluation sans action associée, aucune action inventée : {verdict!r}")

    return {
        "type_alerte": verdict,
        "quoi": quoi,
        "a_qui": a_qui,
        "pourquoi": pourquoi,
        "preuve": preuve,
        "source": definition["source"],
    }
