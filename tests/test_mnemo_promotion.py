"""Promotion gouvernée généralisée : mêmes états et mêmes transitions que la boucle d'apprentissage de M1 (M1.13).

Le test de parité rejoue les MÊMES suites de décisions dans le moteur de M1 (`m1_front_office.apprentissage.etat`) et
dans
le moteur générique (`opsys.mnemo.promotion.rejouer`, `ordre_strict=True` comme M1) : mêmes états, même pile, même
canari,
et les mêmes refus. Données fictives.
"""

from __future__ import annotations

import itertools

import pytest
from m1_front_office import apprentissage as m1

from opsys.mnemo import codes, promotion
from opsys.mnemo.codes import ErreurMnemo

FICTIF = True


def _prop(ident="L1"):
    return {"type_entree": "prop", "id": ident}


def _dec(ident, etape, **plus):
    return {"type_entree": "dec", "id": ident, "etape": etape, **plus}


def _rejouer(maillons, **kw):
    return promotion.rejouer(maillons, type_proposition="prop", type_decision="dec", cle_id="id", **kw)


def test_sans_decision_rien_n_est_actif():
    e = _rejouer([_prop()])
    assert e.etats == {"L1": "proposee"} and e.actives() == () and e.canari is None


def test_parcours_canari_promotion_retour_arriere():
    e = _rejouer([_prop(), _dec("L1", "canari", pourcentage=20)])
    assert e.canari == ("L1", 20) and e.etats["L1"] == "canari" and e.pile == ()
    e = _rejouer([_prop(), _dec("L1", "canari", pourcentage=20), _dec("L1", "complete")])
    assert e.canari is None and e.pile == ("L1",) and e.etats["L1"] == "complete"
    e = _rejouer([_prop(), _dec("L1", "canari", pourcentage=20), _dec("L1", "complete"), _dec("L1", "retour_arriere")])
    assert e.pile == () and e.etats["L1"] == "retiree"


@pytest.mark.parametrize(
    "sequence",
    [
        [("complete", {})],
        [("retour_arriere", {})],
        [("canari", {"pourcentage": 10}), ("canari", {"pourcentage": 10})],
        [("refusee", {}), ("canari", {"pourcentage": 10})],
        [("canari", {"pourcentage": 10}), ("refusee", {})],
        [("canari", {"pourcentage": 10}), ("complete", {}), ("complete", {})],
        [("canari", {"pourcentage": 10}), ("retour_arriere", {}), ("complete", {})],
        [("canari", {"pourcentage": 10}), ("complete", {}), ("retour_arriere", {}), ("retour_arriere", {})],
        [("inconnue", {})],
    ],
)
def test_toute_transition_illegale_est_refusee(sequence):
    with pytest.raises(ErreurMnemo, match="REJ-MNEMO-LECON"):
        _rejouer([_prop(), *[_dec("L1", e, **p) for e, p in sequence]])


def test_decision_sur_proposition_inconnue_et_pourcentage_hors_bornes():
    with pytest.raises(ErreurMnemo, match=codes.LECON_INCONNUE):
        _rejouer([_dec("L9", "canari", pourcentage=5)])
    for mauvais in (0, 51, 100, -3, None, "20", 20.0, True):
        with pytest.raises(ErreurMnemo, match=codes.LECON_CANARI):
            _rejouer([_prop(), _dec("L1", "canari", pourcentage=mauvais)])


def test_un_seul_canari_a_la_fois_mais_un_nouveau_apres_la_conclusion():
    with pytest.raises(ErreurMnemo, match="déjà en cours"):
        _rejouer([_prop("L1"), _prop("L2"), _dec("L1", "canari", pourcentage=5), _dec("L2", "canari", pourcentage=5)])
    e = _rejouer(
        [
            _prop("L1"),
            _prop("L2"),
            _dec("L1", "canari", pourcentage=5),
            _dec("L1", "complete"),
            _dec("L2", "canari", pourcentage=5),
        ]
    )
    assert e.canari == ("L2", 5) and e.pile == ("L1",)


def test_ordre_strict_empile_et_ordre_libre_permet_de_retirer_n_importe_quelle_lecon():
    base = [
        _prop("L1"),
        _prop("L2"),
        _dec("L1", "canari", pourcentage=5),
        _dec("L1", "complete"),
        _dec("L2", "canari", pourcentage=5),
        _dec("L2", "complete"),
    ]
    with pytest.raises(ErreurMnemo, match="illégal"):
        _rejouer([*base, _dec("L1", "retour_arriere")], ordre_strict=True)
    e = _rejouer([*base, _dec("L1", "retour_arriere")], ordre_strict=False)
    assert e.pile == ("L2",) and e.etats["L1"] == "retiree"
    e = _rejouer([*base, _dec("L2", "retour_arriere")], ordre_strict=True)
    assert e.pile == ("L1",)


def test_le_canari_est_deterministe_proportionnel_et_stable():
    cles = [f"cas:{i:05d}" for i in range(2000)]
    dedans = [c for c in cles if promotion.dans_le_canari(c, 30)]
    assert dedans == [c for c in cles if promotion.dans_le_canari(c, 30)]
    assert 0.24 < len(dedans) / len(cles) < 0.36
    assert not any(promotion.dans_le_canari(c, 0) for c in cles)
    assert all(promotion.dans_le_canari(c, 100) for c in cles[:50])
    # la graine (l'identifiant de la leçon) rend deux canaris indépendants : les mêmes cas ne sont pas toujours choisis
    a = {c for c in cles if promotion.dans_le_canari(c, 30, graine="L1")}
    b = {c for c in cles if promotion.dans_le_canari(c, 30, graine="L2")}
    assert a != b and 0.15 < len(a & b) / len(a) < 0.45


def test_parite_avec_la_boucle_d_apprentissage_de_m1():
    """Même fonction de hachage sans graine, mêmes états et mêmes refus pour toutes les suites de 1 à 4 décisions."""
    assert all(m1.dans_le_canari(c, 30) == promotion.dans_le_canari(c, 30) for c in (f"c{i}" for i in range(500)))
    etapes = [("canari", {"pourcentage": 20}), ("complete", {}), ("retour_arriere", {}), ("refusee", {})]
    compte = {"legal": 0, "illegal": 0}
    for longueur in range(1, 5):
        for suite in itertools.product(etapes, repeat=longueur):
            m1_maillons = [
                {"type_entree": m1.TYPE_PROPOSITION, "proposition_id": "pr-1", "genre": "regle_tri", "regles": []}
            ] + [{"type_entree": m1.TYPE_DECISION, "proposition_id": "pr-1", "etape": e, **p} for e, p in suite]
            mien = [_prop("pr-1")] + [_dec("pr-1", e, **p) for e, p in suite]
            try:
                attendu = m1.etat(m1_maillons)
            except m1.RefusApprentissage:
                compte["illegal"] += 1
                with pytest.raises(ErreurMnemo):
                    _rejouer(mien, ordre_strict=True)
                continue
            compte["legal"] += 1
            obtenu = _rejouer(mien, ordre_strict=True)
            assert dict(obtenu.etats) == dict(attendu.etats), suite
            assert obtenu.pile == attendu.pile_completes, suite
            assert (obtenu.canari[1] if obtenu.canari else None) == (attendu.canari[2] if attendu.canari else None)
    assert compte["legal"] >= 5 and compte["illegal"] > 100  # la parité couvre bien des suites légales ET illégales
