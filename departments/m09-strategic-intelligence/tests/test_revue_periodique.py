"""M9.6–7 — revues périodiques : périodes, fuseaux, arrivée tardive, versions immuables, tendances (fictif)."""

import copy

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import revue_periodique as rp

FICTIF = True
TOR = "America/Toronto"


def _cap(lecture_id, *, index, precedent, recu_a, reponse=None, arguments=None):
    reponse = reponse or {"ok": True, "resultat": {"accepte": True, "resultat": {"x": index}}}
    return cs.construire(
        cat.obtenir(lecture_id),
        arguments or {},
        [reponse],
        recu_a=recu_a,
        reference=None,
        index=index,
        hash_precedent=precedent,
    )


def _chaine(*specs):
    chaine = []
    for lecture_id, recu_a, *reste in specs:
        chaine.append(
            _cap(
                lecture_id,
                index=len(chaine),
                precedent=chaine[-1]["hash_maillon"] if chaine else "",
                recu_a=recu_a,
                reponse=reste[0] if reste else None,
            )
        )
    return chaine


def _cloture(session_id, recu_a, issue="RECOMMANDATION", sensibles=1):
    actions = [
        {"action": f"a{i}", "type": "depense_reelle", "verdict": "VALIDATION_HUMAINE_REQUISE"} for i in range(sensibles)
    ]
    return {
        "type": "CLOTURE",
        "session_id": session_id,
        "recu_a": recu_a,
        "issue": issue,
        "rapport_id": "r" * 8,
        "gouvernance": {"actions": actions} if issue == "RECOMMANDATION" else None,
    }


def _ouverture(session_id, recu_a):
    return {"type": "OUVERTURE", "session_id": session_id, "recu_a": recu_a}


@pytest.mark.parametrize(
    ("granularite", "ancre", "debut_local", "fin_local"),
    [
        ("hebdomadaire", "2026-10-21", "2026-10-19", "2026-10-26"),  # mercredi → lundi
        ("hebdomadaire", "2026-10-19", "2026-10-19", "2026-10-26"),
        ("mensuelle", "2026-10-31", "2026-10-01", "2026-11-01"),
        ("mensuelle", "2026-12-15", "2026-12-01", "2027-01-01"),
        ("trimestrielle", "2026-11-30", "2026-10-01", "2027-01-01"),
        ("trimestrielle", "2026-02-02", "2026-01-01", "2026-04-01"),
    ],
)
def test_periodes_locales(granularite, ancre, debut_local, fin_local):
    periode = rp.bornes(granularite, ancre, TOR)
    assert (periode["debut_local"], periode["fin_local"]) == (debut_local, fin_local)


def test_fuseaux_et_heure_d_ete_changent_les_instants_utc_pas_la_periode():
    # Fin d'heure d'été au Québec : le 1er novembre 2026 à 02:00 locale ; octobre dure 31 jours locaux, 745 h réelles.
    mois = rp.bornes("mensuelle", "2026-10-15", TOR)
    assert mois["debut"] == "2026-10-01T04:00:00Z" and mois["fin"] == "2026-11-01T04:00:00Z"
    hiver = rp.bornes("mensuelle", "2026-11-15", TOR)
    assert hiver["debut"] == "2026-11-01T04:00:00Z" and hiver["fin"] == "2026-12-01T05:00:00Z"
    utc = rp.bornes("mensuelle", "2026-10-15", "UTC")
    assert utc["debut"] == "2026-10-01T00:00:00Z" and utc["fin"] == "2026-11-01T00:00:00Z"
    tokyo = rp.bornes("hebdomadaire", "2026-10-21", "Asia/Tokyo")
    assert tokyo["debut"] == "2026-10-18T15:00:00Z"


@pytest.mark.parametrize(
    ("g", "a", "f"),
    [
        ("annuelle", "2026-10-01", TOR),
        ("mensuelle", "2026-13-01", TOR),
        ("mensuelle", "2026-10-1", TOR),
        ("mensuelle", "2026-10-01", "Mars/Olympus"),
        ("mensuelle", "2026-10-01", ""),
    ],
)
def test_entrees_invalides_refusees(g, a, f):
    with pytest.raises(ValueError, match="REJ-REVUE-"):
        rp.bornes(g, a, f)


def test_periode_precedente_et_connaissance_precoce_refusee():
    semaine = rp.bornes("hebdomadaire", "2026-10-21", TOR)
    assert rp.precedente(semaine)["debut_local"] == "2026-10-12"
    assert rp.precedente(rp.bornes("trimestrielle", "2026-01-15", TOR))["debut_local"] == "2025-10-01"
    with pytest.raises(ValueError, match="REJ-REVUE-PRECOCE"):
        rp.composer(
            [], [], granularite="hebdomadaire", ancre="2026-10-21", fuseau=TOR, connaissance="2026-10-22T12:00:00Z"
        )


def test_revue_hebdomadaire_rattache_par_reception_dans_le_fuseau_demande():
    chaine = _chaine(
        ("m6.disponibilite", "2026-10-19T03:00:00Z"),  # dimanche 23 h locale : semaine précédente
        ("m6.disponibilite", "2026-10-19T05:00:00Z"),  # lundi 1 h locale : dans la période
        ("m2.leads", "2026-10-25T20:00:00Z", {"ok": False, "erreur": "producteur_indisponible"}),
        ("m6.disponibilite", "2026-10-26T05:00:00Z"),  # lundi suivant : hors période
    )
    sessions = [
        _ouverture("s1", "2026-10-22T14:00:00Z"),
        _cloture("s1", "2026-10-23T14:00:00Z"),
        _ouverture("s0", "2026-10-15T14:00:00Z"),
        _cloture("s0", "2026-10-16T14:00:00Z", "ABSTENTION"),
    ]
    revue = rp.composer(
        chaine,
        sessions,
        granularite="hebdomadaire",
        ancre="2026-10-21",
        fuseau=TOR,
        connaissance="2026-10-27T00:00:00Z",
    )
    synthese = revue["synthese"]
    assert (synthese["captures_recues"], synthese["refusees_ou_en_erreur"]) == (2, 1)
    assert (synthese["sessions_ouvertes"], synthese["sessions_closes"], synthese["recommandations"]) == (1, 1, 1)
    assert {c["index"] for c in revue["captures_de_la_periode"]} == {1, 2}
    assert revue["decisions"][0]["actions_sensibles"] == 1
    tendance = revue["tendances_de_la_connaissance"]["sessions_closes"]
    assert (tendance["precedente"], tendance["courante"], tendance["ecart"]) == (1, 1, 0)
    assert revue["tendances_de_la_connaissance"]["captures_recues"]["precedente"] == 1
    assert "tendance" in revue["limites"][0] or "CONNAISSANCE" in revue["limites"][0]
    assert rp.valider_chaine([]) == (True, "")


def test_deterministe_reproductible_et_identifiant_lie_au_contenu():
    chaine = _chaine(("m6.disponibilite", "2026-10-20T15:00:00Z"))
    a = rp.composer(
        chaine, [], granularite="mensuelle", ancre="2026-10-05", fuseau=TOR, connaissance="2026-11-02T00:00:00Z"
    )
    b = rp.composer(
        copy.deepcopy(chaine),
        [],
        granularite="mensuelle",
        ancre="2026-10-05",
        fuseau=TOR,
        connaissance="2026-11-02T00:00:00Z",
    )
    assert a == b and a["revue_id"] == b["revue_id"]


def test_arrivee_tardive_nouvelle_version_ancienne_intacte():
    chaine = _chaine(("m6.disponibilite", "2026-10-20T15:00:00Z"))
    v1 = rp.composer(
        chaine, [], granularite="hebdomadaire", ancre="2026-10-21", fuseau=TOR, connaissance="2026-10-27T00:00:00Z"
    )
    pub1 = rp.publier([], v1, publie_a="2026-10-27T00:00:01Z")
    assert pub1["version"] == 1 and pub1["remplace_version"] is None and v1["arrivees_tardives"] == []
    assert rp.publier([pub1], v1, publie_a="2026-10-27T00:00:02Z") is None  # rejeu identique
    # Publier plus tard SANS rien de nouveau : même contenu, même version (la connaissance seule n'est pas un
    # changement).
    plus_tard = rp.composer(
        chaine, [], granularite="hebdomadaire", ancre="2026-10-21", fuseau=TOR, connaissance="2026-11-15T00:00:00Z"
    )
    assert (
        plus_tard["revue_id"] == v1["revue_id"]
        and rp.publier([pub1], plus_tard, publie_a="2026-11-15T00:00:01Z") is None
    )
    # Une capture reçue après la fin et SANS étendue métier déclarée ne concerne pas la période : revue inchangée.
    sans = chaine + [
        _cap("m6.disponibilite", index=1, precedent=chaine[-1]["hash_maillon"], recu_a="2026-10-28T12:00:00Z")
    ]
    assert (
        rp.composer(
            sans, [], granularite="hebdomadaire", ancre="2026-10-21", fuseau=TOR, connaissance="2026-10-29T00:00:00Z"
        )["revue_id"]
        == v1["revue_id"]
    )
    # Une capture reçue après la fin dont l'étendue métier DÉCLARÉE chevauche la période est une arrivée tardive.
    lead = {
        "ok": True,
        "resultat": {
            "accepte": True,
            "resultat": {
                "leads": [
                    {
                        "lead_id": "L1",
                        "ingere_le": "2026-10-21T10:00:00-04:00",
                        "derniere_activite": "2026-10-22T10:00:00-04:00",
                    }
                ],
                "suivant": None,
            },
        },
    }
    tardive = _cap(
        "m2.leads", index=1, precedent=chaine[-1]["hash_maillon"], recu_a="2026-10-28T12:00:00Z", reponse=lead
    )
    v2 = rp.composer(
        [*chaine, tardive],
        [],
        granularite="hebdomadaire",
        ancre="2026-10-21",
        fuseau=TOR,
        connaissance="2026-10-29T00:00:00Z",
    )
    assert v2["revue_id"] != v1["revue_id"] and [a["lecture_id"] for a in v2["arrivees_tardives"]] == ["m2.leads"]
    assert v2["synthese"] == v1["synthese"]  # ce que M9 avait reçu à la fin de la période ne change jamais
    pub2 = rp.publier([pub1], v2, publie_a="2026-10-29T00:00:01Z")
    assert pub2["version"] == 2 and pub2["remplace_version"] == 1 and pub2["arrivees_tardives_ajoutees"] == 1
    assert pub1["revue"]["arrivees_tardives"] == []  # l'ancienne version n'est jamais réécrite
    assert rp.valider_chaine([pub1, pub2]) == (True, "")


def test_publication_datee_et_chaine_alteree_refusees():
    v1 = rp.composer(
        [], [], granularite="hebdomadaire", ancre="2026-10-21", fuseau=TOR, connaissance="2026-10-27T00:00:00Z"
    )
    with pytest.raises(ValueError, match="REJ-REVUE-TEMPS"):
        rp.publier([], v1, publie_a="2026-10-26T00:00:00Z")
    with pytest.raises(ValueError, match="REJ-REVUE-TEMPS"):
        rp.publier([], v1, publie_a="2026-10-28T00:00:00")
    pub = rp.publier([], v1, publie_a="2026-10-28T00:00:00Z")
    altere = copy.deepcopy(pub)
    altere["revue"]["synthese"]["captures_recues"] = 99
    assert rp.valider_chaine([altere])[0] is False
    autre_periode = rp.composer(
        [], [], granularite="hebdomadaire", ancre="2026-10-28", fuseau=TOR, connaissance="2026-11-03T00:00:00Z"
    )
    assert (
        rp.publier([pub], autre_periode, publie_a="2026-11-03T00:00:01Z")["version"] == 1
    )  # autre période : version 1


def test_trimestre_et_fuseaux_distincts_donnent_des_revues_distinctes():
    chaine = _chaine(
        ("m6.disponibilite", "2026-10-01T02:00:00Z")
    )  # 30 sept 22 h locale : trimestre précédent à Toronto
    toronto = rp.composer(
        chaine, [], granularite="trimestrielle", ancre="2026-10-15", fuseau=TOR, connaissance="2027-01-02T00:00:00Z"
    )
    utc = rp.composer(
        chaine, [], granularite="trimestrielle", ancre="2026-10-15", fuseau="UTC", connaissance="2027-01-02T00:00:00Z"
    )
    assert toronto["synthese"]["captures_recues"] == 0 and utc["synthese"]["captures_recues"] == 1
    assert toronto["revue_id"] != utc["revue_id"]
