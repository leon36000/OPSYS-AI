CONSTANTE_XMR = 2.66


def detecter_signal(metric_id, valeurs_historiques, n_minimal):
    n = len(valeurs_historiques)

    if n < n_minimal:
        return {
            "metric_id": metric_id,
            "type_signal": "DONNEES_INSUFFISANTES",
            "valeur_observee": None,
            "limite_naturelle_haute": None,
            "limite_naturelle_basse": None,
            "n": n,
        }

    moyenne = sum(valeurs_historiques) / n
    amplitudes_mobiles = [
        abs(valeurs_historiques[i] - valeurs_historiques[i - 1])
        for i in range(1, n)
    ]
    amplitude_moyenne = (
        sum(amplitudes_mobiles) / len(amplitudes_mobiles)
        if amplitudes_mobiles
        else 0.0
    )
    limite_naturelle_haute = moyenne + CONSTANTE_XMR * amplitude_moyenne
    limite_naturelle_basse = moyenne - CONSTANTE_XMR * amplitude_moyenne

    derniere_valeur = valeurs_historiques[-1]

    if derniere_valeur > limite_naturelle_haute:
        type_signal = "HORS_LIMITE_SUPERIEURE"
    elif derniere_valeur < limite_naturelle_basse:
        type_signal = "HORS_LIMITE_INFERIEURE"
    else:
        return None

    return {
        "metric_id": metric_id,
        "type_signal": type_signal,
        "valeur_observee": derniere_valeur,
        "limite_naturelle_haute": limite_naturelle_haute,
        "limite_naturelle_basse": limite_naturelle_basse,
        "n": n,
    }
