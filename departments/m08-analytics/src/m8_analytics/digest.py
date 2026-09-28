"""Digest quotidien déterministe de M8 (T3.1 : signaux XmR ; T3.1-suite,
docs/programme/PLAN.md : alertes de qualité proposées).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge — ``produire_digest_quotidien``
ne fait que filtrer, dédupliquer et compter des objets déjà calculés ailleurs (``xmr.py``,
``qualite.py`` + ``alertes.py``), jamais un nouveau calcul métier.
"""

from __future__ import annotations

from . import encodage

_MESSAGE_AUCUNE_ALERTE = "Aucune alerte proposée aujourd'hui."


def produire_digest_quotidien(signaux: list[dict], alertes_proposees: list[dict] | None = None) -> dict:
    """``signaux`` : sorties de ``xmr.detecter_signal`` déjà calculées (T3.1, inchangé).

    ``alertes_proposees`` (T3.1-suite) : objets déjà construits par ``alertes.proposer_action``
    — chacun porte déjà sa provenance (``source``), donc le digest reste « sourcé » sans rien
    ajouter. Dédupliquées par contenu exact (``encodage.empreinte``, même mécanisme que le
    hash-chaînage du registre) : une même alerte proposée deux fois dans l'entrée n'apparaît
    qu'une fois — l'ordre de PREMIÈRE apparition est conservé. ``None`` (défaut, aucun changement
    pour les appelants existants) équivaut à une liste vide : aucune alerte proposée aujourd'hui.
    ``resume_alertes`` le dit explicitement, jamais une liste vide silencieuse à interpréter."""
    type_rapport = "DIGEST_ANALYTICS"
    signaux_actifs = [
        signal
        for signal in signaux
        if signal["type_signal"] != "DONNEES_INSUFFISANTES"
    ]
    nb_signaux_actifs = len(signaux_actifs)

    alertes_dedupliquees: list[dict] = []
    empreintes_vues: set[str] = set()
    for alerte in alertes_proposees or []:
        empreinte_alerte = encodage.empreinte(alerte)
        if empreinte_alerte in empreintes_vues:
            continue
        empreintes_vues.add(empreinte_alerte)
        alertes_dedupliquees.append(alerte)
    nb_alertes_proposees = len(alertes_dedupliquees)
    resume_alertes = (
        _MESSAGE_AUCUNE_ALERTE
        if nb_alertes_proposees == 0
        else f"{nb_alertes_proposees} alerte(s) proposée(s) aujourd'hui, sourcée(s) ci-dessous."
    )

    hash_digest = encodage.empreinte(type_rapport, signaux_actifs, alertes_dedupliquees)

    return {
        "type": type_rapport,
        "nb_signaux_actifs": nb_signaux_actifs,
        "signaux_actifs": signaux_actifs,
        "nb_alertes_proposees": nb_alertes_proposees,
        "alertes_proposees": alertes_dedupliquees,
        "resume_alertes": resume_alertes,
        "hash_digest": hash_digest,
    }
