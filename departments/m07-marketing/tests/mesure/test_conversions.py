"""Conversions hors ligne : liste fermée, idempotence, révision, tout-ou-rien, événement conforme, chaîne de hachage."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime

import pytest
from fabriques_mesure import evenements_de
from m7_marketing import journal_chaine
from m7_marketing.mesure import conversions as conv

from opsys import evenements, stockage
from opsys.evenements import schemas

MAINTENANT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _c(**modif):
    base = {
        "conversion_id": "conv-0001",
        "lead_id": "lead-fictif-001",
        "type": "vente",
        "convertie_le": "2026-10-20",
        "valeur_cad": "12500.5",
        "utm_source": "FB",
        "utm_medium": "Paid Search",
        "utm_campaign": "Fenetre Ete 2026",
    }
    base.update(modif)
    return base


def _importer(lot, maintenant=MAINTENANT):
    with stockage.transaction():
        return conv.importer(stockage.maillons(*conv.REGISTRE), lot, "agent", maintenant)


def _registre():
    return conv.courantes(stockage.maillons(*conv.REGISTRE))


def _refus(r):
    assert r["accepte"] is False
    return r["refus"][0]["code"]


def test_import_normalise_la_source_et_annonce_l_evenement_conforme_au_schema(base):
    r = _importer([_c()])
    assert r == {
        "accepte": True,
        "ecrites": 1,
        "revisions": 0,
        "deja_presentes": 0,
        "conversions": [{"conversion_id": "conv-0001", "revision": 1}],
    }
    e = _registre()["conv-0001"]
    assert (e["utm_source"], e["utm_medium"], e["utm_campaign"], e["valeur_cad"]) == (
        "facebook",
        "cpc",
        "fenetre-ete-2026",
        "12500.50",
    )
    [(ident, charge)] = evenements_de(conv.TYPE_EVENEMENT)
    assert ident == "m7-conversion-conv-0001-r1"
    assert charge == {
        "conversion_id": "conv-0001",
        "lead_id": "lead-fictif-001",
        "type": "vente",
        "convertie_le": "2026-10-20",
        "utm_source": "facebook",
        "utm_medium": "cpc",
        "utm_campaign": "fenetre-ete-2026",
        "valeur_cad": "12500.50",
        "source_normalisee": True,
        "importee_le": "2026-11-01T12:00:00Z",
    }
    assert schemas.erreurs_charge(conv.TYPE_EVENEMENT, charge) == []


def test_une_conversion_sans_source_reste_sans_source(base):
    _importer([_c(conversion_id="conv-0002", utm_source=None, utm_medium=None, utm_campaign=None, valeur_cad=None)])
    e = _registre()["conv-0002"]
    assert e["utm_source"] is None and e["utm_medium"] is None and e["utm_campaign"] is None and e["valeur_cad"] is None
    [(_, charge)] = evenements_de(conv.TYPE_EVENEMENT)
    assert charge["source_normalisee"] is False and charge["utm_source"] is None
    sans_champs = {k: v for k, v in _c(conversion_id="conv-0003").items() if not k.startswith("utm_")}
    _importer([sans_champs])
    assert _registre()["conv-0003"]["utm_source"] is None


def test_rejeu_identique_ne_change_rien_et_ne_republie_pas(base):
    _importer([_c()])
    n = len(stockage.maillons(*conv.REGISTRE))
    r = _importer([_c()], MAINTENANT.replace(hour=15))
    assert r["ecrites"] == 0 and r["deja_presentes"] == 1 and r["conversions"] == []
    assert len(stockage.maillons(*conv.REGISTRE)) == n
    assert len(evenements_de(conv.TYPE_EVENEMENT)) == 1


def test_meme_forme_normalisee_est_le_meme_contenu(base):
    _importer([_c()])
    r = _importer([_c(utm_source="facebook", utm_medium="cpc", utm_campaign="fenetre-ete-2026", valeur_cad="12500.50")])
    assert r["deja_presentes"] == 1 and r["ecrites"] == 0


def test_meme_identifiant_contenu_different_est_un_conflit(base):
    _importer([_c()])
    assert _refus(_importer([_c(valeur_cad="999")])) == "REJ-MESURE-CONVERSION-CONFLIT"
    assert len(stockage.maillons(*conv.REGISTRE)) == 1


def test_revision_explicite_avec_motif(base):
    _importer([_c()])
    r = _importer([_c(valeur_cad="13000", revision=2, motif_revision="correction_valeur")])
    assert r["revisions"] == 1 and r["ecrites"] == 0
    assert _registre()["conv-0001"]["revision"] == 2 and _registre()["conv-0001"]["valeur_cad"] == "13000.00"
    ids = [i for i, _ in evenements_de(conv.TYPE_EVENEMENT)]
    assert ids == ["m7-conversion-conv-0001-r1", "m7-conversion-conv-0001-r2"]


@pytest.mark.parametrize(
    "modif,code",
    [
        ({"revision": 2}, "REJ-MESURE-CONVERSION-MOTIF"),
        ({"revision": 2, "motif_revision": "parce que"}, "REJ-MESURE-CONVERSION-MOTIF"),
        ({"revision": 1, "motif_revision": "correction_valeur"}, "REJ-MESURE-CONVERSION-MOTIF"),
        (
            {"revision": 3, "motif_revision": "correction_valeur", "valeur_cad": "1"},
            "REJ-MESURE-CONVERSION-REVISION-SAUTEE",
        ),
        ({"revision": 2, "motif_revision": "correction_valeur"}, "REJ-MESURE-CONVERSION-REVISION-PERIMEE"),
        # contenu inchangé
        ({"revision": 0}, "REJ-MESURE-CONVERSION-INVALIDE"),
        ({"revision": True}, "REJ-MESURE-CONVERSION-INVALIDE"),
    ],
)
def test_revisions_refusees(base, modif, code):
    _importer([_c()])
    assert _refus(_importer([_c(**modif)])) == code


def test_revision_perimee_et_initiale(base):
    _importer([_c()])
    _importer([_c(valeur_cad="1", revision=2, motif_revision="correction_valeur")])
    assert _refus(_importer([_c(valeur_cad="2", revision=1)])) == "REJ-MESURE-CONVERSION-REVISION-PERIMEE"
    assert (
        _refus(_importer([_c(conversion_id="conv-neuve", revision=2, motif_revision="correction_date")]))
        == "REJ-MESURE-CONVERSION-REVISION-INITIALE"
    )


@pytest.mark.parametrize(
    "champ,valeur",
    [
        ("nom", "Jean Tremblay"),
        ("courriel", "jean@example.test"),
        ("telephone", "514-555-0123"),
        ("gclid", "abc123"),
        ("fbclid", "xyz"),
        ("adresse", "1 rue X"),
        ("note", "texte libre"),
        ("utm_content", "x"),
    ],
)
def test_champ_hors_de_la_liste_fermee_refuse(base, champ, valeur):
    assert _refus(_importer([_c(**{champ: valeur})])) == "REJ-MESURE-CONVERSION-CHAMP-INCONNU"
    assert len(stockage.maillons(*conv.REGISTRE)) == 0 and evenements_de(conv.TYPE_EVENEMENT) == []


@pytest.mark.parametrize(
    "modif,code",
    [
        ({"lead_id": "jean@example.test"}, "REJ-MESURE-CONVERSION-INVALIDE"),
        ({"lead_id": "514-555-0123"}, "REJ-MESURE-CONVERSION-COORDONNEE"),
        ({"lead_id": "5145550123"}, "REJ-MESURE-CONVERSION-COORDONNEE"),
        ({"lead_id": "lead 001"}, "REJ-MESURE-CONVERSION-INVALIDE"),
        ({"conversion_id": "x" * 81}, "REJ-MESURE-CONVERSION-INVALIDE"),
        ({"type": "paiement"}, "REJ-MESURE-CONVERSION-INVALIDE"),
        ({"convertie_le": "2026-02-30"}, "REJ-MESURE-CONVERSION-INVALIDE"),
        ({"convertie_le": "20/10/2026"}, "REJ-MESURE-CONVERSION-INVALIDE"),
        ({"convertie_le": "2019-12-31"}, "REJ-MESURE-CONVERSION-INVALIDE"),
        ({"convertie_le": "2026-11-02"}, "REJ-MESURE-CONVERSION-FUTURE"),
        ({"valeur_cad": 1500.5}, "REJ-MESURE-CONVERSION-VALEUR"),
        ({"valeur_cad": 1500}, "REJ-MESURE-CONVERSION-VALEUR"),
        ({"valeur_cad": "-5"}, "REJ-MESURE-CONVERSION-VALEUR"),
        ({"valeur_cad": "10.999"}, "REJ-MESURE-CONVERSION-VALEUR"),
        ({"valeur_cad": "1e5"}, "REJ-MESURE-CONVERSION-VALEUR"),
        ({"valeur_cad": "NaN"}, "REJ-MESURE-CONVERSION-VALEUR"),
        ({"utm_source": "twitter"}, "REJ-MESURE-UTM-NON-NORMALISABLE"),
        ({"utm_source": "meta"}, "REJ-MESURE-UTM-NON-NORMALISABLE"),
        ({"utm_campaign": "promo-ete"}, "REJ-MESURE-UTM-NON-NORMALISABLE"),
    ],
)
def test_valeurs_invalides_refusees_et_rien_n_est_ecrit(base, modif, code):
    assert _refus(_importer([_c(**modif)])) == code
    assert len(stockage.maillons(*conv.REGISTRE)) == 0


def test_date_du_jour_permise_et_futur_juge_sur_l_instant_de_l_import(base):
    assert _importer([_c(convertie_le="2026-11-01")])["accepte"]
    soir = datetime(2026, 11, 1, 23, 59, tzinfo=UTC)
    assert _importer([_c(conversion_id="c2", convertie_le="2026-11-01")], soir)["accepte"]


def test_lot_tout_ou_rien(base):
    lot = [_c(conversion_id=f"conv-{i:04d}") for i in range(5)] + [_c(conversion_id="conv-mauvaise", type="paiement")]
    r = _importer(lot)
    assert r["accepte"] is False and "conversion 5" in r["refus"][0]["detail"]
    assert len(stockage.maillons(*conv.REGISTRE)) == 0 and evenements_de(conv.TYPE_EVENEMENT) == []


def test_lot_tout_ou_rien_si_l_evenement_echoue_en_cours_d_ecriture(base, monkeypatch):
    appels = []
    reel = evenements.publier

    def casse(*args, **kwargs):
        appels.append(1)
        if len(appels) == 3:
            raise RuntimeError("panne du bus")
        return reel(*args, **kwargs)

    monkeypatch.setattr(conv.evenements, "publier", casse)
    with pytest.raises(RuntimeError):
        _importer([_c(conversion_id=f"conv-{i:04d}") for i in range(5)])
    assert len(stockage.maillons(*conv.REGISTRE)) == 0 and evenements_de(conv.TYPE_EVENEMENT) == []


def test_bornes_du_lot(base):
    assert _importer([_c(conversion_id=f"c{i:04d}") for i in range(conv.LOT_MAX)])["ecrites"] == 200
    assert (
        _refus(_importer([_c(conversion_id=f"d{i:04d}") for i in range(conv.LOT_MAX + 1)]))
        == "REJ-MESURE-LOT-TROP-GROS"
    )
    assert _refus(_importer([])) == "REJ-MESURE-CONVERSION-INVALIDE"
    assert _refus(_importer("pas une liste")) == "REJ-MESURE-CONVERSION-INVALIDE"
    assert _refus(_importer(["texte"])) == "REJ-MESURE-CONVERSION-INVALIDE"


def test_doublon_identique_dans_le_lot_est_un_rejeu_et_contradictoire_un_conflit(base):
    r = _importer([_c(), _c()])
    assert r["ecrites"] == 1 and r["deja_presentes"] == 1
    assert (
        _refus(_importer([_c(conversion_id="z1"), _c(conversion_id="z1", valeur_cad="1")]))
        == "REJ-MESURE-CONVERSION-CONFLIT"
    )


def test_registre_ne_contient_aucune_coordonnee_ni_identifiant_publicitaire(base):
    _importer([_c()])
    brut = json.dumps(list(stockage.maillons(*conv.REGISTRE)))
    for interdit in ("@", "gclid", "fbclid", "courriel", "telephone", "nom"):
        assert interdit not in brut.replace("nomme", "")


def test_chaine_de_hachage_alteree_detectee(base):
    _importer([_c()])
    _importer([_c(conversion_id="conv-0002")])
    journal = list(stockage.maillons(*conv.REGISTRE))
    falsifie = copy.deepcopy(journal)
    falsifie[0]["valeur_cad"] = "1.00"
    with pytest.raises(conv.RefusConversion) as exc:
        conv.courantes(falsifie)
    assert exc.value.verdict["code"] == "REJ-MESURE-JOURNAL-ALTERE"
    retire = journal[1:]
    with pytest.raises(conv.RefusConversion):
        conv.courantes(retire)
    assert journal_chaine.integre(journal)


def test_import_refuse_quand_la_chaine_est_alteree(base):
    _importer([_c()])
    falsifie = copy.deepcopy(list(stockage.maillons(*conv.REGISTRE)))
    falsifie[0]["lead_id"] = "autre"
    with stockage.transaction():
        r = conv.importer(falsifie, [_c(conversion_id="c9")], "agent", MAINTENANT)
    assert _refus(r) == "REJ-MESURE-JOURNAL-ALTERE"


def test_dans_la_periode_filtre_et_trie(base):
    _importer(
        [
            _c(conversion_id="b", convertie_le="2026-10-10"),
            _c(conversion_id="a", convertie_le="2026-10-10"),
            _c(conversion_id="c", convertie_le="2026-09-30"),
            _c(conversion_id="d", convertie_le="2026-10-31"),
        ]
    )
    from datetime import date

    sel = conv.dans_la_periode(_registre(), date(2026, 10, 1), date(2026, 10, 31))
    assert [e["conversion_id"] for e in sel] == ["a", "b", "d"]


def test_valeur_canonique():
    assert conv.valeur_canonique("0") == "0.00" and conv.valeur_canonique("12.5") == "12.50"
    assert conv.valeur_canonique(None) is None
    with pytest.raises(conv.RefusConversion):
        conv.valeur_canonique(12.5)
