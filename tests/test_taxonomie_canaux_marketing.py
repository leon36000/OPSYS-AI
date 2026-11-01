"""Correspondance « source UTM -> canal publicitaire » (D6 de M8-ENTREPOT-SOURCES.md) : écrite par le propriétaire dans
le
profil d'entreprise (`entreprise.yaml`, clé `canaux_marketing`), jamais dans le code. Absente, le verdict le dit
(« canaux à configurer ») ; jamais une correspondance par défaut. Sources UTM fictives."""

from __future__ import annotations

import pytest

from opsys import etat, stockage, taxonomie
from opsys.taxonomie import ProfilInvalide


def _ecrire_profil(contenu: str) -> None:
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(contenu, encoding="utf-8")


def test_sans_profil_aucune_correspondance_n_est_inventee_et_le_verdict_dit_ou_la_declarer(opsys_home):
    canaux, verdict = taxonomie.charger_canaux_marketing()
    assert canaux == {} and verdict["code"] == taxonomie.VERDICT_CANAUX_MARKETING_NON_CONFIGURES
    assert str(taxonomie.fichier_profil()) in verdict["detail"] and "canaux_marketing" in verdict["detail"]
    assert taxonomie.lire_canaux_marketing() == {}


@pytest.mark.parametrize("contenu", ["canaux_marketing:\n", "canaux_marketing: {}\n"])
def test_une_declaration_vide_n_est_pas_une_declaration(opsys_home, contenu):
    _ecrire_profil(contenu)
    assert taxonomie.charger_canaux_marketing()[1]["code"] == taxonomie.VERDICT_CANAUX_MARKETING_NON_CONFIGURES


def test_une_correspondance_valide_est_lue_en_minuscules_et_signee_au_journal(opsys_home):
    stockage.migrer()
    chemin = taxonomie.enregistrer_canaux_marketing(
        {"meta": [" Facebook ", "instagram"], "google_ads": ["google"]}, par="nathan"
    )
    assert chemin == taxonomie.fichier_profil()
    canaux, verdict = taxonomie.charger_canaux_marketing()
    assert verdict is None and canaux == {"google_ads": ("google",), "meta": ("facebook", "instagram")}
    assert taxonomie.verifier_profil() == []
    with etat.session() as cnx:
        journal = etat.lire_journal(cnx)
    assert journal[0]["action"] == "entreprise.canaux_marketing"
    assert journal[0]["details"] == {"sources_par_canal": {"google_ads": 1, "meta": 2}}


@pytest.mark.parametrize(
    ("brut", "fragment"),
    [
        ("liste", "doit être un objet"),
        ({"tiktok": ["tiktok"]}, "canaux inconnus"),
        ({"meta": "facebook"}, "une liste de sources UTM"),
        ({"meta": []}, "est vide"),
        ({"meta": ["Face book"]}, "source UTM"),
        ({"meta": [3]}, "source UTM"),
        ({"meta": ["fb", "FB"]}, "en double"),
        ({"meta": ["fb"], "google_ads": ["fb"]}, "une source, un canal"),
        ({"meta": [f"s{i}" for i in range(21)]}, "20 sources au plus"),
    ],
)
def test_une_declaration_invalide_est_refusee_jamais_lue_comme_absente(opsys_home, brut, fragment):
    with pytest.raises(ProfilInvalide, match=fragment):
        taxonomie.normaliser_canaux_marketing(brut)


def test_un_profil_invalide_est_un_verdict_distinct_de_l_absence_et_verifier_le_signale(opsys_home):
    _ecrire_profil("canaux_marketing:\n  tiktok: [tt]\n")
    canaux, verdict = taxonomie.charger_canaux_marketing()
    assert canaux == {} and verdict["code"] == taxonomie.VERDICT_PROFIL_INVALIDE
    assert any("canaux inconnus" in p for p in taxonomie.verifier_profil())
