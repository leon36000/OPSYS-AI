"""Fenêtre de conversation du profil d'entreprise (PLAN T2.1-b) : lue dans le profil, jamais inventée."""

from __future__ import annotations

import pytest
import yaml

from opsys import etat, stockage, taxonomie
from opsys.taxonomie import ProfilInvalide


def test_sans_profil_aucune_fenetre_n_est_inventee_et_le_verdict_dit_ou_la_declarer(opsys_home):
    minutes, verdict = taxonomie.charger_fenetre_conversation()
    assert minutes is None
    assert verdict["code"] == taxonomie.VERDICT_FENETRE_NON_CONFIGUREE
    assert str(taxonomie.fichier_profil()) in verdict["detail"]
    assert "fenetre_conversation_minutes" in verdict["detail"] and "message par message" in verdict["detail"]
    assert taxonomie.lire_fenetre_conversation() is None


def test_un_profil_de_services_et_de_zone_sans_fenetre_n_a_pas_de_fenetre(opsys_home, declarer_services):
    declarer_services("gouttieres")
    taxonomie.enregistrer_zone_desservie(["Laval"])
    assert taxonomie.charger_fenetre_conversation()[0] is None


def test_une_fenetre_declaree_se_relit_a_l_identique_et_services_et_zone_restent(opsys_home, declarer_services):
    declarer_services("gouttieres")
    taxonomie.enregistrer_zone_desservie(["Laval"])
    fichier = taxonomie.enregistrer_fenetre_conversation(30)
    assert fichier == taxonomie.fichier_profil()
    assert taxonomie.charger_fenetre_conversation() == (30, None)
    assert [s.code for s in taxonomie.lire_services()] == ["gouttieres"]
    assert taxonomie.lire_zone_desservie() == ("Laval",)
    # Déclarer les services, puis la zone, ensuite n'écrase pas la fenêtre.
    taxonomie.enregistrer_services(["reparation"])
    taxonomie.enregistrer_zone_desservie(["Québec"])
    assert taxonomie.lire_fenetre_conversation() == 30
    assert yaml.safe_load(fichier.read_text(encoding="utf-8"))["fenetre_conversation_minutes"] == 30


@pytest.mark.parametrize("minutes", [1, 30, 1440, taxonomie.FENETRE_CONVERSATION_MAX_MINUTES])
def test_les_durees_valides_sont_acceptees_bornes_comprises(minutes):
    assert taxonomie.normaliser_fenetre_conversation(minutes) == minutes


@pytest.mark.parametrize("contenu", [
    "fenetre_conversation_minutes: 0\n",
    "fenetre_conversation_minutes: -5\n",
    f"fenetre_conversation_minutes: {taxonomie.FENETRE_CONVERSATION_MAX_MINUTES + 1}\n",
    "fenetre_conversation_minutes: 30.5\n",
    "fenetre_conversation_minutes: '30'\n",
    "fenetre_conversation_minutes: true\n",
    "fenetre_conversation_minutes: [30]\n",
    "fenetre_conversation_minutes:\n",
    "fenetre_conversation_minutes: [30\n",
])
def test_une_fenetre_mal_formee_est_refusee_jamais_lue_comme_absente(opsys_home, contenu):
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True)
    fichier.write_text(contenu, encoding="utf-8")
    with pytest.raises(ProfilInvalide):
        taxonomie.lire_fenetre_conversation()
    minutes, verdict = taxonomie.charger_fenetre_conversation()
    assert minutes is None
    assert verdict["code"] == taxonomie.VERDICT_PROFIL_INVALIDE, "distinct de l'absence"
    assert taxonomie.verifier_profil() != []


def test_enregistrer_une_fenetre_invalide_ne_touche_pas_au_profil(opsys_home, declarer_services):
    declarer_services("gouttieres")
    avant = taxonomie.fichier_profil().read_text(encoding="utf-8")
    for invalide in (0, 30.5, "30", True, None):
        with pytest.raises(ProfilInvalide):
            taxonomie.enregistrer_fenetre_conversation(invalide)
    assert taxonomie.fichier_profil().read_text(encoding="utf-8") == avant


def test_enregistrer_la_fenetre_signee_ecrit_au_journal_d_audit(opsys_home):
    stockage.migrer()
    taxonomie.enregistrer_fenetre_conversation(45, par="nathan")
    with etat.session() as cnx:
        journal = etat.lire_journal(cnx)
    assert journal[0]["par"] == "nathan"
    assert journal[0]["action"] == "entreprise.fenetre_conversation"
    assert journal[0]["details"] == {"minutes": 45}
