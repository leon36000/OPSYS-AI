"""Vocabulaire des plaintes et destinataires des transferts (PLAN T4.5) : écrits par le propriétaire dans le profil
d'entreprise, jamais dans le code. Absents, le verdict le dit (« vocabulaire à configurer », « destinataire à
configurer ») ; jamais un mot ni un destinataire par défaut.

Les termes et les rôles de ces tests sont fictifs (`fictif: true` dans la fixture de M1 dont ils sont tirés)."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest
import yaml

from opsys import etat, identite, stockage, taxonomie
from opsys.taxonomie import ProfilInvalide

RACINE = Path(__file__).resolve().parents[1]
FIXTURE = RACINE / "departments" / "m01-front-office" / "fixtures" / "plaintes" / "plaintes.v1.yaml"
DEFINITION_PRODUIT = RACINE / "docs" / "produit" / "DEFINITION-PRODUIT.md"


@pytest.fixture
def profil_fictif() -> dict:
    donnees = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    assert donnees["fictif"] is True
    return donnees


def _ecrire_profil(contenu: str) -> None:
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(contenu, encoding="utf-8")


def _sans_accent(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texte.lower()) if not unicodedata.combining(c))


# -- Ensembles fermés : ceux de la définition du produit ---------------------------------------------------------------


def test_les_types_de_transfert_sont_ceux_de_la_definition_du_produit():
    """DEFINITION-PRODUIT §7 M1.12 : « types : ventes, estimation, admin, finance, plainte, urgence, technique,
    propriétaire ». Le code les écrit sans accent ; ni un de plus ni un de moins."""
    ligne = next(ligne for ligne in DEFINITION_PRODUIT.read_text(encoding="utf-8").splitlines() if "M1.12" in ligne)
    liste = re.search(r"types\s*:\s*([^)]*)\)", ligne)
    assert liste is not None, "la ligne M1.12 ne dit plus ses types : ce garde-fou est à revoir"
    dans_le_produit = [_sans_accent(t.strip()) for t in liste.group(1).split(",")]
    assert list(taxonomie.TYPES_TRANSFERT) == dans_le_produit
    assert len(set(taxonomie.TYPES_TRANSFERT)) == 8


def test_les_categories_de_signal_sont_celles_du_plan():
    """PLAN T4.5 : insatisfaction, dégât, garantie, avocat, urgence de sécurité."""
    assert taxonomie.CATEGORIES_SIGNAL_PLAINTE == ("insatisfaction", "degat", "garantie", "avocat", "securite")


def test_les_destinataires_possibles_sont_des_personnes_de_l_entreprise_jamais_le_client_ni_l_agent():
    assert set(taxonomie.ROLES_DESTINATAIRES_TRANSFERT) == identite.ROLES - {"client", "system_agent"}


# -- Vocabulaire : jamais dans le code, jamais inventé -----------------------------------------------------------------


def test_sans_profil_aucun_mot_n_est_invente_et_le_verdict_dit_ou_les_declarer(opsys_home):
    signaux, verdict = taxonomie.charger_signaux_plainte()
    assert signaux == {}
    assert verdict["code"] == taxonomie.VERDICT_SIGNAUX_PLAINTE_NON_CONFIGURES
    assert verdict["detail"].startswith("vocabulaire des plaintes à configurer")
    assert str(taxonomie.fichier_profil()) in verdict["detail"] and "signaux_plainte" in verdict["detail"]
    for categorie in taxonomie.CATEGORIES_SIGNAL_PLAINTE:
        assert categorie in verdict["detail"]
    assert taxonomie.lire_signaux_plainte() == {}


@pytest.mark.parametrize("contenu", ["signaux_plainte:\n", "signaux_plainte: {}\n"])
def test_un_vocabulaire_vide_vaut_un_vocabulaire_absent(opsys_home, contenu):
    _ecrire_profil(contenu)
    assert taxonomie.charger_signaux_plainte()[1]["code"] == taxonomie.VERDICT_SIGNAUX_PLAINTE_NON_CONFIGURES
    assert taxonomie.verifier_profil() == []


def test_le_vocabulaire_declare_se_relit_a_l_identique_et_le_reste_du_profil_demeure(
    opsys_home, declarer_services, profil_fictif
):
    declarer_services("gouttieres")
    taxonomie.enregistrer_zone_desservie(["Laval"])
    taxonomie.enregistrer_fenetre_conversation(30)
    fichier = taxonomie.enregistrer_signaux_plainte(profil_fictif["signaux_plainte"])
    assert fichier == taxonomie.fichier_profil()

    signaux, verdict = taxonomie.charger_signaux_plainte()
    assert verdict is None
    assert set(signaux) == set(taxonomie.CATEGORIES_SIGNAL_PLAINTE)
    assert signaux["avocat"][0] == "avocat" and "mise en demeure" in signaux["avocat"]
    assert signaux["insatisfaction"] == tuple(profil_fictif["signaux_plainte"]["insatisfaction"]), "ordre écrit"

    taxonomie.enregistrer_services(["reparation"])
    taxonomie.enregistrer_zone_desservie(["Québec"])
    assert taxonomie.charger_signaux_plainte()[0] == signaux
    assert [s.code for s in taxonomie.lire_services()] == ["reparation"]
    assert taxonomie.lire_zone_desservie() == ("Québec",)
    assert taxonomie.lire_fenetre_conversation() == 30


def test_une_categorie_absente_n_est_pas_une_erreur(opsys_home):
    taxonomie.enregistrer_signaux_plainte({"securite": ["danger"]})
    assert taxonomie.charger_signaux_plainte() == ({"securite": ("danger",)}, None)


def test_un_terme_est_nettoye_des_blancs_en_trop(opsys_home):
    assert taxonomie.normaliser_signaux_plainte({"avocat": ["  mise   en  demeure "]}) == {
        "avocat": ("mise en demeure",)}


@pytest.mark.parametrize("contenu, motif", [
    ("signaux_plainte: [a]\n", "objet"),
    ("signaux_plainte: {avocat: []}\n", "est vide"),
    ("signaux_plainte: {avocat: avocat}\n", "liste de termes"),
    ("signaux_plainte: {avocat: {a: b}}\n", "liste de termes"),
    ("signaux_plainte: {menace: [avocat]}\n", "catégories inconnues"),
    ("signaux_plainte: {avocat: [ab]}\n", "trop court"),
    ("signaux_plainte: {avocat: ['']}\n", "trop court"),
    ("signaux_plainte: {avocat: [12345]}\n", "un terme d'une ligne"),
    ("signaux_plainte: {avocat: [\"a\\nb c\"]}\n", "un terme d'une ligne"),
    ("signaux_plainte: {avocat: [avocat, Avocat]}\n", "en double"),
    ("signaux_plainte: {avocat: [avocat\n", "illisible"),
])
def test_un_vocabulaire_mal_forme_est_refuse_avec_la_raison_jamais_lu_comme_absent(opsys_home, contenu, motif):
    _ecrire_profil(contenu)
    with pytest.raises(ProfilInvalide, match=motif):
        taxonomie.lire_signaux_plainte()
    signaux, verdict = taxonomie.charger_signaux_plainte()
    assert signaux == {}
    assert verdict["code"] == taxonomie.VERDICT_PROFIL_INVALIDE, "distinct de l'absence"
    assert taxonomie.verifier_profil() != []


def test_trop_de_termes_ou_un_terme_trop_long_est_refuse(opsys_home):
    soixante_et_un = [f"terme{i:02d}" for i in range(61)]
    with pytest.raises(ProfilInvalide, match="60 termes au plus"):
        taxonomie.normaliser_signaux_plainte({"avocat": soixante_et_un})
    assert len(taxonomie.normaliser_signaux_plainte({"avocat": soixante_et_un[:60]})["avocat"]) == 60
    with pytest.raises(ProfilInvalide, match="80 caractères"):
        taxonomie.normaliser_signaux_plainte({"avocat": ["x" * 81]})


def test_enregistrer_un_vocabulaire_invalide_ne_touche_pas_au_profil(opsys_home, declarer_services):
    declarer_services("gouttieres")
    avant = taxonomie.fichier_profil().read_text(encoding="utf-8")
    for invalide in ({}, [], {"avocat": []}, {"menace": ["avocat"]}, {"avocat": ["ab"]}, None):
        with pytest.raises(ProfilInvalide):
            taxonomie.enregistrer_signaux_plainte(invalide)
    assert taxonomie.fichier_profil().read_text(encoding="utf-8") == avant


def test_enregistrer_le_vocabulaire_signe_au_journal_avec_le_nombre_de_termes(opsys_home, profil_fictif):
    stockage.migrer()
    taxonomie.enregistrer_signaux_plainte(profil_fictif["signaux_plainte"], par="nathan")
    with etat.session() as cnx:
        journal = etat.lire_journal(cnx)
    assert journal[0]["par"] == "nathan" and journal[0]["action"] == "entreprise.signaux_plainte"
    assert journal[0]["details"] == {"termes_par_categorie": {
        categorie: len(termes) for categorie, termes in profil_fictif["signaux_plainte"].items()}}


# -- Destinataires : « à configurer », jamais une personne choisie par le code ---


def test_sans_profil_chaque_type_de_transfert_dit_destinataire_a_configurer(opsys_home):
    for type_transfert in taxonomie.TYPES_TRANSFERT:
        role, verdict = taxonomie.charger_destinataire_du_transfert(type_transfert)
        assert role is None
        assert verdict["code"] == taxonomie.VERDICT_DESTINATAIRE_NON_CONFIGURE
        assert verdict["detail"].startswith("destinataire à configurer")
        assert f"'{type_transfert}'" in verdict["detail"]
        assert str(taxonomie.fichier_profil()) in verdict["detail"] and "destinataires_transfert" in verdict["detail"]
    assert taxonomie.lire_destinataires_transfert() == {}


@pytest.mark.parametrize("contenu", ["destinataires_transfert:\n", "destinataires_transfert: {}\n"])
def test_une_table_vide_vaut_une_table_absente(opsys_home, contenu):
    _ecrire_profil(contenu)
    assert taxonomie.charger_destinataire_du_transfert("plainte")[1]["code"] == (
        taxonomie.VERDICT_DESTINATAIRE_NON_CONFIGURE)
    assert taxonomie.verifier_profil() == []


def test_la_table_partielle_dit_un_role_pour_les_types_declares_et_a_configurer_pour_les_autres(
    opsys_home, profil_fictif
):
    taxonomie.enregistrer_destinataires_transfert({"plainte": "nathan_owner", "ventes": "seller"})
    assert taxonomie.charger_destinataire_du_transfert("plainte") == ("nathan_owner", None)
    assert taxonomie.charger_destinataire_du_transfert("ventes") == ("seller", None)
    role, verdict = taxonomie.charger_destinataire_du_transfert("finance")
    assert role is None and verdict["code"] == taxonomie.VERDICT_DESTINATAIRE_NON_CONFIGURE

    taxonomie.enregistrer_destinataires_transfert(profil_fictif["destinataires_transfert"])
    assert taxonomie.lire_destinataires_transfert() == profil_fictif["destinataires_transfert"]
    assert set(taxonomie.lire_destinataires_transfert()) == set(taxonomie.TYPES_TRANSFERT)


def test_un_type_de_transfert_inconnu_est_une_erreur_de_l_appelant(opsys_home):
    with pytest.raises(ValueError, match="type de transfert inconnu"):
        taxonomie.charger_destinataire_du_transfert("livraison")


@pytest.mark.parametrize("contenu, motif", [
    ("destinataires_transfert: [admin]\n", "objet"),
    ("destinataires_transfert: {livraison: admin}\n", "types de transfert inconnus"),
    ("destinataires_transfert: {plainte: nathan}\n", "un rôle parmi"),
    ("destinataires_transfert: {plainte: client}\n", "un rôle parmi"),
    ("destinataires_transfert: {plainte: system_agent}\n", "un rôle parmi"),
    ("destinataires_transfert: {plainte: [admin]}\n", "un rôle parmi"),
    ("destinataires_transfert: {plainte: ~}\n", "un rôle parmi"),
    ("destinataires_transfert: {plainte: admin\n", "illisible"),
])
def test_une_table_mal_formee_est_refusee_avec_la_raison_jamais_lue_comme_a_configurer(opsys_home, contenu, motif):
    _ecrire_profil(contenu)
    with pytest.raises(ProfilInvalide, match=motif):
        taxonomie.lire_destinataires_transfert()
    role, verdict = taxonomie.charger_destinataire_du_transfert("plainte")
    assert role is None
    assert verdict["code"] == taxonomie.VERDICT_PROFIL_INVALIDE, "distinct de l'absence"
    assert taxonomie.verifier_profil() != []


def test_enregistrer_une_table_invalide_ne_touche_pas_au_profil(opsys_home, declarer_services):
    declarer_services("gouttieres")
    avant = taxonomie.fichier_profil().read_text(encoding="utf-8")
    for invalide in ({}, [], {"plainte": "client"}, {"livraison": "admin"}, {"plainte": "Nathan"}, None):
        with pytest.raises(ProfilInvalide):
            taxonomie.enregistrer_destinataires_transfert(invalide)
    assert taxonomie.fichier_profil().read_text(encoding="utf-8") == avant


def test_enregistrer_les_destinataires_signe_au_journal_avec_des_roles_jamais_des_noms(opsys_home):
    stockage.migrer()
    taxonomie.enregistrer_destinataires_transfert({"plainte": "nathan_owner", "finance": "finance"}, par="nathan")
    with etat.session() as cnx:
        journal = etat.lire_journal(cnx)
    assert journal[0]["action"] == "entreprise.destinataires_transfert"
    assert journal[0]["details"] == {"destinataires": {"plainte": "nathan_owner", "finance": "finance"}}
