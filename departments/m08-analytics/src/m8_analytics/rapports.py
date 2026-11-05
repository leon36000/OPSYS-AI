import json
import math
from decimal import Decimal
from typing import Any

from . import encodage


def construire_rapport(metriques, signaux, role=None, metric_ids_autorises=None):
    if metric_ids_autorises is None:
        if role is not None:
            # Fail-closed (CA-M8-11) : un rôle nommé sans liste d'autorisations
            # explicite n'est jamais interprété comme une vue complète — un rôle
            # deviné/oublié serait une fuite silencieuse (ex. coûts/marges vus
            # par un rôle terrain). Seule l'ABSENCE de rôle (usage interne, pas
            # de rôle du tout) reste la vue complète non filtrée.
            raise ValueError(
                f"role={role!r} fourni sans metric_ids_autorises : refus fail-closed, "
                "jamais une vue complète devinée pour un rôle nommé"
            )
        metriques_visibles = list(metriques)
        signaux_visibles = list(signaux)
    else:
        autorises = set(metric_ids_autorises)
        metriques_visibles = [m for m in metriques if m["metric_id"] in autorises]
        signaux_visibles = [s for s in signaux if s["metric_id"] in autorises]

    type_rapport = "RAPPORT_ANALYTIQUE"
    snapshot_id = encodage.empreinte(
        type_rapport, role, metriques_visibles, signaux_visibles
    )

    return {
        "type": type_rapport,
        "role": role,
        "metriques": metriques_visibles,
        "signaux": signaux_visibles,
        "snapshot_id": snapshot_id,
    }


def rendre_markdown(rapport: dict[str, Any]) -> str:
    """Rend en Markdown un rapport déjà construit et filtré, sans calcul ni ajout de données.

    L'empreinte lie le rendu au contenu structuré. Elle n'authentifie pas le producteur et ne prouve
    pas la qualité des sources. Seuls les champs du contrat RapportAnalytique sont rendus ; un champ
    supplémentaire fourni par un appelant n'est jamais copié dans le document.
    """
    cles_rapport = {"type", "role", "metriques", "signaux", "snapshot_id"}
    if type(rapport) is not dict or set(rapport) != cles_rapport:
        raise ValueError("REJ-RAPPORT-MARKDOWN-FORME-INVALIDE")
    if (rapport["type"] != "RAPPORT_ANALYTIQUE"
            or (rapport["role"] is not None and type(rapport["role"]) is not str)
            or type(rapport["metriques"]) is not list or type(rapport["signaux"]) is not list
            or type(rapport["snapshot_id"]) is not str):
        raise ValueError("REJ-RAPPORT-MARKDOWN-FORME-INVALIDE")
    empreinte_attendue = encodage.empreinte(
        rapport["type"], rapport["role"], rapport["metriques"], rapport["signaux"]
    )
    if rapport["snapshot_id"] != empreinte_attendue:
        raise ValueError("REJ-RAPPORT-MARKDOWN-EMPREINTE-INVALIDE")

    def texte_cellule(valeur: Any) -> str:
        if valeur is None:
            rendu = "non calculable"
        elif type(valeur) is str:
            rendu = valeur
        elif type(valeur) is int:
            rendu = str(valeur)
        elif type(valeur) is float and math.isfinite(valeur):
            rendu = repr(valeur)
        elif isinstance(valeur, Decimal) and valeur.is_finite():
            rendu = str(valeur)
        else:
            raise ValueError("REJ-RAPPORT-MARKDOWN-VALEUR-INVALIDE")
        # Une cellule ne peut ni ouvrir une nouvelle ligne, ni injecter un lien, du HTML ou une
        # nouvelle structure Markdown depuis un identifiant fourni par un producteur.
        rendu = rendu.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        rendu = rendu.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        for caractere in "\\`*_{}[]()#+!|":
            rendu = rendu.replace(caractere, "\\" + caractere)
        try:
            rendu.encode("utf-8", errors="strict")
        except UnicodeError:
            raise ValueError("REJ-RAPPORT-MARKDOWN-VALEUR-INVALIDE") from None
        return rendu

    def extensions_json(extensions: dict[str, Any]) -> str:
        """Rend toutes les extensions JSON autorisées, sans en supprimer ni les interpréter."""
        if not extensions:
            return "—"
        try:
            texte = json.dumps(extensions, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError, RecursionError, UnicodeError):
            raise ValueError("REJ-RAPPORT-MARKDOWN-EXTENSION-INVALIDE") from None
        return texte_cellule(texte)

    lignes = [
        "# Rapport analytique",
        "",
        f"Rôle indiqué : {texte_cellule(rapport['role']) if rapport['role'] is not None else 'non fourni'}",
        f"Empreinte du rapport : `{rapport['snapshot_id']}`",
        "",
        "Cette empreinte lie le rendu au contenu structuré; elle n'authentifie pas les sources.",
        "",
        "## Mesures",
        "",
        "| Mesure | Valeur exacte | Fraîcheur (jours) | Observations | "
        "Version | Qualité des entrées | Extensions (JSON) |",
        "| --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    champs_metrique = {"metric_id", "valeur", "version_definition", "fraicheur", "n"}
    for metrique in rapport["metriques"]:
        if (type(metrique) is not dict or not {"metric_id", "valeur", "version_definition", "fraicheur", "n"}
                <= set(metrique)
                or any(type(cle) is not str for cle in metrique)
                or type(metrique["metric_id"]) is not str or type(metrique["version_definition"]) is not str
                or type(metrique["n"]) is not int or metrique["n"] < 0):
            raise ValueError("REJ-RAPPORT-MARKDOWN-METRIQUE-INVALIDE")
        invalides = metrique.get("valeurs_invalides", 0)
        derniere_invalide = metrique.get("derniere_valeur_invalide", False)
        if type(invalides) is not int or invalides < 0 or type(derniere_invalide) is not bool:
            raise ValueError("REJ-RAPPORT-MARKDOWN-METRIQUE-INVALIDE")
        qualite = "non signalée"
        if invalides or derniere_invalide:
            qualite = f"{invalides} observation(s) invalide(s); dernière invalide : {derniere_invalide}"
        cellules = (
            texte_cellule(metrique["metric_id"]), texte_cellule(metrique["valeur"]),
            texte_cellule(metrique["fraicheur"]), str(metrique["n"]),
            texte_cellule(metrique["version_definition"]), texte_cellule(qualite),
            extensions_json({cle: metrique[cle] for cle in sorted(set(metrique) - champs_metrique)}),
        )
        lignes.append("| " + " | ".join(cellules) + " |")
    if not rapport["metriques"]:
        lignes.append("| Aucune mesure | non calculable | non calculable | 0 | — | non signalée | — |")

    lignes.extend(("", "## Signaux", "", "| Mesure | Signal | Observé | Limite basse | Limite haute | "
                   "Observations | Extensions (JSON) |",
                   "| --- | --- | ---: | ---: | ---: | ---: | --- |"))
    champs_signal = {"metric_id", "type_signal", "valeur_observee", "limite_naturelle_haute",
                     "limite_naturelle_basse", "n"}
    for signal in rapport["signaux"]:
        if (type(signal) is not dict or not champs_signal <= set(signal)
                or any(type(cle) is not str for cle in signal)
                or type(signal["metric_id"]) is not str or type(signal["type_signal"]) is not str
                or type(signal["n"]) is not int or signal["n"] < 0):
            raise ValueError("REJ-RAPPORT-MARKDOWN-SIGNAL-INVALIDE")
        cellules = (
            texte_cellule(signal["metric_id"]), texte_cellule(signal["type_signal"]),
            texte_cellule(signal["valeur_observee"]), texte_cellule(signal["limite_naturelle_basse"]),
            texte_cellule(signal["limite_naturelle_haute"]), str(signal["n"]),
            extensions_json({cle: signal[cle] for cle in sorted(set(signal) - champs_signal)}),
        )
        lignes.append("| " + " | ".join(cellules) + " |")
    if not rapport["signaux"]:
        lignes.append("| Aucun signal | — | — | — | — | 0 | — |")
    return "\n".join(lignes) + "\n"
