"""Zone desservie du profil d'entreprise (PLAN T2.1) : lue dans le profil, jamais dans une demande."""

from __future__ import annotations

import pytest
import yaml

from opsys import etat, stockage, taxonomie
from opsys.taxonomie import ProfilInvalide


def test_sans_profil_aucune_ville_n_est_reconnue_et_le_verdict_dit_ou_la_declarer(opsys_home):
    villes, verdict = taxonomie.charger_zone_desservie()
    assert villes == ()
    assert verdict["code"] == taxonomie.VERDICT_ZONE_NON_CONFIGUREE
    assert str(taxonomie.fichier_profil()) in verdict["detail"]
    assert "zone_desservie" in verdict["detail"]


def test_une_zone_declaree_se_relit_a_l_identique_et_les_services_restent(opsys_home, declarer_services):
    declarer_services("gouttieres")
    fichier = taxonomie.enregistrer_zone_desservie(["Laval", "  Québec  "])
    assert fichier == taxonomie.fichier_profil()
    assert taxonomie.charger_zone_desservie() == (("Laval", "Québec"), None)
    # La zone n'écrase pas les services, et déclarer les services ensuite n'écrase pas la zone.
    assert [s.code for s in taxonomie.lire_services()] == ["gouttieres"]
    taxonomie.enregistrer_services(["reparation"])
    assert taxonomie.lire_zone_desservie() == ("Laval", "Québec")
    assert yaml.safe_load(fichier.read_text(encoding="utf-8"))["zone_desservie"] == ["Laval", "Québec"]


@pytest.mark.parametrize("contenu, motif", [
    ("zone_desservie: []\n", "vide"),
    ("zone_desservie: Laval\n", "liste"),
    ("zone_desservie: [Laval, laval]\n", "double"),
    ("zone_desservie: [Laval, 3]\n", "chaîne non vide"),
    ("zone_desservie: ['  ']\n", "chaîne non vide"),
    ("zone_desservie: [Laval\n", "illisible"),
])
def test_une_zone_mal_formee_est_refusee_avec_la_raison_jamais_lue_comme_vide(opsys_home, contenu, motif):
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True)
    fichier.write_text(contenu, encoding="utf-8")
    with pytest.raises(ProfilInvalide, match=motif):
        taxonomie.lire_zone_desservie()
    villes, verdict = taxonomie.charger_zone_desservie()
    assert villes == ()
    assert verdict["code"] == taxonomie.VERDICT_PROFIL_INVALIDE
    assert taxonomie.verifier_profil() != []


def test_un_fichier_illisible_n_est_signale_qu_une_fois_par_verifier(opsys_home):
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True)
    fichier.write_text("zone_desservie: [Laval\n", encoding="utf-8")
    assert len(taxonomie.verifier_profil()) == 1


def test_la_trop_longue_liste_et_la_ville_trop_longue_sont_refusees(opsys_home):
    with pytest.raises(ProfilInvalide, match="au plus"):
        taxonomie.normaliser_zone_desservie([f"Ville {i}" for i in range(301)])
    with pytest.raises(ProfilInvalide, match="au plus"):
        taxonomie.normaliser_zone_desservie(["x" * 81])


def test_enregistrer_la_zone_signee_ecrit_au_journal_d_audit(opsys_home):
    stockage.migrer()
    taxonomie.enregistrer_zone_desservie(["Laval"], par="nathan")
    with etat.session() as cnx:
        journal = etat.lire_journal(cnx)
    assert journal[0]["par"] == "nathan"
    assert journal[0]["action"] == "entreprise.zone_desservie"
    assert journal[0]["details"] == {"villes": ["Laval"]}
