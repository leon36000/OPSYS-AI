import hashlib
import json


def construire_etat_consolide(registre_snapshots):
    maillons = registre_snapshots.lire()
    faits_par_module = {}
    maillons_par_source_et_horodatage = {}

    for maillon in maillons:
        module_source = maillon["module_source"]
        horodatage = maillon["horodatage"]

        faits_par_module[module_source] = maillon

        cle_groupe = (module_source, horodatage)
        if cle_groupe not in maillons_par_source_et_horodatage:
            maillons_par_source_et_horodatage[cle_groupe] = []
        maillons_par_source_et_horodatage[cle_groupe].append(maillon)

    contradictions = []

    for (module_source, horodatage), maillons_groupe in (
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
                            "horodatage": horodatage,
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
