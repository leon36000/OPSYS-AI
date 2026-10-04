import hashlib
import json
from datetime import UTC, datetime


def _analyser_horodatage(horodatage):
    """Parse un horodatage ISO-8601, fuseau compris (patron M8 exact,
    m8_analytics/semantique.py::_analyser_horodatage).

    Un horodatage sans fuseau explicite est traité comme UTC : M9 n'a pas
    d'horloge propre et ne doit jamais deviner un fuseau différent de celui
    fourni par l'appelant ; UTC est la seule convention qui rend deux
    horodatages comparables entre eux sans introduire de biais.
    """
    valeur = horodatage[:-1] + "+00:00" if horodatage.endswith("Z") else horodatage
    analyse = datetime.fromisoformat(valeur)
    if analyse.tzinfo is None:
        analyse = analyse.replace(tzinfo=UTC)
    return analyse


def construire_etat_consolide(registre_snapshots):
    maillons = registre_snapshots.lire()
    faits_par_module = {}
    maillons_par_source_et_horodatage = {}

    for maillon in maillons:
        module_source = maillon["module_source"]
        horodatage = maillon["horodatage"]

        actuel = faits_par_module.get(module_source)
        # Comparaison chronologique (datetime ISO-8601 parsé, fuseaux compris)
        # — JAMAIS une comparaison alphabétique des chaînes brutes, qui peut
        # inverser l'ordre réel entre deux fuseaux différents (ex.
        # "...+09:00" vs "...+00:00" : voir test dédié).
        if actuel is None or (
            _analyser_horodatage(horodatage) >= _analyser_horodatage(actuel["horodatage"])
        ):
            faits_par_module[module_source] = maillon

        horodatage_utc = _analyser_horodatage(horodatage).astimezone(UTC).isoformat()
        cle_groupe = (module_source, horodatage_utc)
        if cle_groupe not in maillons_par_source_et_horodatage:
            maillons_par_source_et_horodatage[cle_groupe] = []
        maillons_par_source_et_horodatage[cle_groupe].append(maillon)

    contradictions = []

    for (module_source, horodatage_utc), maillons_groupe in (
        maillons_par_source_et_horodatage.items()
    ):
        for position_a in range(len(maillons_groupe)):
            for position_b in range(position_a + 1, len(maillons_groupe)):
                maillon_a = maillons_groupe[position_a]
                maillon_b = maillons_groupe[position_b]

                if maillon_a["valeurs"] != maillon_b["valeurs"]:
                    contradictions.append(
                        {
                            "ligne_id_a": min(
                                maillon_a["index"],
                                maillon_b["index"],
                            ),
                            "ligne_id_b": max(
                                maillon_a["index"],
                                maillon_b["index"],
                            ),
                            "module_source": module_source,
                            # Provenance: conserver les représentations originales en plus
                            # de l'instant canonique utilisé pour grouper les observations.
                            "horodatage": maillon_a["horodatage"],
                            "horodatage_utc": horodatage_utc,
                            "horodatages_sources": sorted({maillon_a["horodatage"], maillon_b["horodatage"]}),
                        }
                    )

    contradictions = sorted(
        contradictions,
        key=lambda contradiction: (
            contradiction["ligne_id_a"],
            contradiction["ligne_id_b"],
        ),
    )

    rapport_sans_id = {
        "type": "ETAT_CONSOLIDE",
        "faits_par_module": faits_par_module,
        "contradictions": contradictions,
    }
    etat_id = hashlib.sha256(
        json.dumps(
            rapport_sans_id,
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    return {
        "type": "ETAT_CONSOLIDE",
        "faits_par_module": faits_par_module,
        "contradictions": contradictions,
        "etat_id": etat_id,
    }
