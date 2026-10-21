"""Composer un dossier historique sourcé depuis une copie validée, sans effet métier.

La sélection et les contradictions viennent du consolidateur existant. Une sélection
n'établit ni l'actualité ni la vérité d'une observation. Ce dossier n'est pas le rapport
stratégique complet, et ne valide aucune décision.
"""
import hashlib
import json

from . import etat_consolide


def construire_dossier(copie_validee, question, modules_attendus, *, budget_caracteres):
    """L'adaptateur fournit sa capture validée ; aucune relecture de source durable ici."""
    if not isinstance(question, str) or not question.strip() or len(question) > 2048:
        raise ValueError("REJ-DOSSIER-QUESTION : question non vide de 2048 caractères au maximum requise")
    if (
        not isinstance(modules_attendus, list) or not 1 <= len(modules_attendus) <= 16
        or any(not isinstance(m, str) or not m.strip() or len(m) > 128 for m in modules_attendus)
        or len(set(modules_attendus)) != len(modules_attendus)
    ):
        raise ValueError("REJ-DOSSIER-MODULES : 1 à 16 identifiants distincts non vides, de 128 caractères au maximum")

    # La chaîne existante ne garantit pas l'unicité des index stockés. Refuser AVANT
    # de former une table ou de dédupliquer les citations : aucune variante ne doit
    # être remplacée silencieusement par une autre ligne portant le même index.
    lignes = copie_validee.lire()
    # Une chaîne peut être hashée en mémoire avec des clés/tuples que le transport
    # JSON convertirait. Refuser plutôt que citer une ligne différente de sa preuve.
    try:
        representation = json.dumps(lignes, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if json.loads(representation) != lignes:
            raise ValueError("conversion JSON")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("REJ-DOSSIER-SERIALISATION : preuves non représentables sans conversion JSON") from exc
    par_index = {}
    for ligne in lignes:
        index = ligne["index"]
        if type(index) is not int or index < 0 or index in par_index:
            raise ValueError("REJ-DOSSIER-REFERENCE : index de preuve invalide ou ambigu")
        par_index[index] = ligne

    etat = etat_consolide.construire_etat_consolide(copie_validee)
    indices = set()
    for fait in etat["faits_par_module"].values():
        index = fait["index"]
        if index not in par_index or par_index[index] != fait:
            raise ValueError("REJ-DOSSIER-REFERENCE : fait sélectionné sans preuve exacte")
        indices.add(index)
    for contradiction in etat["contradictions"]:
        for champ in ("ligne_id_a", "ligne_id_b"):
            index = contradiction[champ]
            if type(index) is not int or index not in par_index:
                raise ValueError("REJ-DOSSIER-REFERENCE : variante contradictoire sans preuve exacte")
            indices.add(index)

    dossier = {
        "type": "DOSSIER_PREPARATOIRE_DIRECTION",
        "question": question,
        "modules_attendus": list(modules_attendus),
        "etat_id": etat["etat_id"],
        "statut_preparation": "NON_VALIDE",
        "actualite": "NON_EVALUEE",
        "faits_selectionnes": etat["faits_par_module"],
        "contradictions": etat["contradictions"],
        "preuves": [par_index[index] for index in sorted(indices)],
        "modules_manquants": sorted(set(modules_attendus) - etat["faits_par_module"].keys()),
        "limites": [
            "Observations historiques reçues : sélection chronologique "
            "sans validation de leur vérité ni de leur actualité.",
            "Les contradictions conservent les deux variantes ; aucune n'est arbitrée.",
            "Les modules attendus sont déclarés par l'appelant ; leur présence ne démontre aucune couverture complète.",
            "Dossier préparatoire seulement : aucune recommandation, décision, approbation ou action exécutée.",
        ],
    }
    dossier["dossier_id"] = hashlib.sha256(json.dumps(
        dossier, sort_keys=True, ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()
    if len(json.dumps(dossier, ensure_ascii=False, allow_nan=False)) > budget_caracteres:
        raise ValueError("REJ-DOSSIER-BORNE : dossier et preuves dépassent le budget ; revue séparée requise")
    return dossier
