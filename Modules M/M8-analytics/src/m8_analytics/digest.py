from __future__ import annotations

from . import encodage


def produire_digest_quotidien(signaux: list[dict]) -> dict:
    type_rapport = "DIGEST_ANALYTICS"
    signaux_actifs = [
        signal
        for signal in signaux
        if signal["type_signal"] != "DONNEES_INSUFFISANTES"
    ]
    nb_signaux_actifs = len(signaux_actifs)
    hash_digest = encodage.empreinte(type_rapport, signaux_actifs)

    return {
        "type": type_rapport,
        "nb_signaux_actifs": nb_signaux_actifs,
        "signaux_actifs": signaux_actifs,
        "hash_digest": hash_digest,
    }
