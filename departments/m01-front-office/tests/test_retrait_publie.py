"""Le STOP d'un correspondant est publié au bus (PLAN T4.17-c) : `m1.retrait_consentement`.

Un correspondant qui écrit STOP se retire des messages ; M7 en tire le retrait de son consentement marketing. M1 ne
connaît pas M7 : il publie un fait, par le `lead_id` des leads déjà ouverts pour ce correspondant. Le numéro n'en sort
jamais. Ces tests passent par le vrai point d'entrée (`Capacites`), le vrai manifeste de M1 et une base SQLite migrée ;
le test de bout en bout jusqu'à M7 est `tests/test_stop_retire_consentement_marketing.py`, à la racine. Numéros en 555.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from m1_front_office import outils as outils_m1
from m1_front_office import retrait
from m1_front_office.reception import identifiant_de_conversation
from sqlalchemy import select

from opsys import evenements, identite, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.departements import lire_manifeste
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
M1 = Path(__file__).resolve().parents[1]
NUMERO = "+15145550142"
AUTRE_NUMERO = "+15145550177"
RECU_LE = "2026-09-29T09:15:00-04:00"
STOP_LE = "2026-09-30T08:15:00-04:00"
GOUTTIERES = "Bonjour, mes gouttières fuient à Laval, c'est urgent."
REVETEMENT = "Bonjour, je veux refaire mon revêtement extérieur à Laval."
CONVERSATION = identifiant_de_conversation("sms", NUMERO)


def _sms(texte, message_id, *, expediteur=NUMERO, recu_le=RECU_LE):
    return {"canal": "sms", "expediteur": expediteur, "message_id": message_id, "recu_le": recu_le, "texte": texte}


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    outils_m1.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner"])
    yield
    outils_m1.reinitialiser_registre()
    stockage.liberer()


@pytest.fixture
def capacites(instance):
    dep = lire_manifeste(M1)
    return Capacites({dep.id: dep}, stockage.transaction, memoire=False)


def _retraits_publies():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m1.retrait_consentement"
        ).order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id)).all()
    return [(ligne.evenement_id, codec.decoder(ligne.charge)) for ligne in lignes]


def _lignes():
    with stockage.transaction():
        return outils_m1._obtenir_registre().lire()


def _lead_id(capacites, message_id="SM-1", texte=GOUTTIERES, **surcharges):
    """Le lead_id vient de la conversation, du texte ET de l'identité du canal : un même texte du même correspondant
    donne le même lead (M1 le déduplique) ; pour un second lead, un autre texte."""
    reponse = capacites.appeler("m1_recevoir_message_canal", _sms(texte, message_id, **surcharges))
    assert reponse["ok"] is True and reponse["resultat"]["decision"] == "TRANSMETTRE_M2", reponse
    return reponse["resultat"]["lead"]["lead_id"]


def _stop(capacites, message_id="SM-STOP", **surcharges):
    champs = {"recu_le": STOP_LE, **surcharges}
    reponse = capacites.appeler("m1_recevoir_message_canal", _sms("STOP", message_id, **champs))
    assert reponse["ok"] is True and reponse["resultat"]["decision"] == "RETRAIT_CONSENTEMENT", reponse
    return reponse["resultat"]


# -- retrait.py : pur  ---
def _lead_emis(lead_id, conversation_id="conv-a"):
    return {"type_entree": "lead_emis", "conversation_id": conversation_id, "lead": {"lead_id": lead_id}}


def test_les_leads_d_une_conversation_sont_dans_l_ordre_du_registre_sans_repetition():
    lignes = [
        _lead_emis("lead-1"), _lead_emis("lead-x", "conv-b"), _lead_emis("lead-2"), _lead_emis("lead-1"),
        {"type_entree": "signal", "conversation_id": "conv-a", "lead": {"lead_id": "pas-un-lead"}},
        {"type_entree": "lead_emis", "conversation_id": "conv-a", "lead": "illisible"},
        {"type_entree": "lead_emis", "conversation_id": "conv-a", "lead": {"lead_id": ""}},
    ]
    assert retrait.leads_de_la_conversation(lignes, "conv-a") == ("lead-1", "lead-2")
    assert retrait.leads_de_la_conversation(lignes, "conv-inconnue") == ()
    assert retrait.leads_de_la_conversation([], "conv-a") == ()


def test_l_alerte_de_retrait_est_la_premiere_de_la_conversation():
    premiere = {"type_entree": "alerte", "marqueur": "retrait_consentement", "conversation_id": "c", "signal_id": "s1"}
    seconde = {**premiere, "signal_id": "s2"}
    autre = {**premiere, "conversation_id": "d", "signal_id": "s3"}
    bruit = {"type_entree": "alerte", "marqueur": "absence_consentement", "conversation_id": "c", "signal_id": "s0"}
    assert retrait.alerte_de_retrait([bruit, premiere, seconde, autre], "c") is premiere
    assert retrait.alerte_de_retrait([bruit, autre], "c") is None
    assert retrait.alerte_de_retrait([{**premiere, "type_entree": "signal"}], "c") is None


def test_la_charge_ne_porte_que_les_leads_le_canal_l_heure_et_le_signal():
    alerte = {"canal": "texte", "source": "sms", "conversation_id": CONVERSATION, "signal_id": "sms:SM-STOP",
              "horodatage": STOP_LE, "contact": {"telephone": NUMERO}}
    assert retrait.charge(alerte, ("lead-1", "lead-2")) == {
        "lead_ids": ["lead-1", "lead-2"], "canal": "sms", "horodatage": STOP_LE, "signal_id": "sms:SM-STOP"}


def test_l_identifiant_d_evenement_est_deterministe_independant_de_l_ordre_et_propre_au_signal():
    un = retrait.identifiant_evenement("sms:SM-1", ["lead-a", "lead-b"])
    assert un == retrait.identifiant_evenement("sms:SM-1", ["lead-b", "lead-a"])
    assert un.startswith("m1-retrait-consentement-") and len(un) == len("m1-retrait-consentement-") + 24
    assert un != retrait.identifiant_evenement("sms:SM-2", ["lead-a", "lead-b"])
    assert un != retrait.identifiant_evenement("sms:SM-1", ["lead-a"])
    # Le préfixe de longueur rend le matériau injectif : ni « a|bc » ni « ab|c » ne se confondent.
    assert retrait.identifiant_evenement("a", ["bc"]) != retrait.identifiant_evenement("ab", ["c"])


# -- le STOP publie les leads déjà ouverts  ---
def test_le_stop_publie_les_leads_du_correspondant_sans_aucun_contact(capacites):
    lead = _lead_id(capacites)
    resultat = _stop(capacites)

    ((evenement_id, charge),) = _retraits_publies()
    assert charge == {"lead_ids": [lead], "canal": "sms", "horodatage": STOP_LE, "signal_id": "sms:SM-STOP"}
    assert evenement_id == retrait.identifiant_evenement("sms:SM-STOP", [lead])
    assert resultat["retrait_publie"] == {"leads": 1, "evenement_id": evenement_id}
    # Le numéro et la conversation (une empreinte du numéro) ne sortent pas de M1 : jamais dans la charge.
    texte = json.dumps(charge)
    assert NUMERO not in texte and "5145550142" not in texte and CONVERSATION not in texte and "sms-" not in texte
    with stockage.transaction():
        assert evenements.charge_publiee("m1.retrait_consentement", evenement_id) == charge


def test_le_stop_ecrit_toujours_son_alerte_au_registre_comme_avant(capacites):
    _lead_id(capacites)
    _stop(capacites)
    alerte = [ligne for ligne in _lignes() if ligne["type_entree"] == "alerte"]
    assert len(alerte) == 1 and alerte[0]["marqueur"] == "retrait_consentement"
    assert (alerte[0]["signal_id"], alerte[0]["horodatage"], alerte[0]["conversation_id"]) == (
        "sms:SM-STOP", STOP_LE, CONVERSATION)


def test_un_stop_rejoue_ne_publie_pas_un_second_evenement(capacites):
    _lead_id(capacites)
    premier = _stop(capacites)
    rejoue = capacites.appeler("m1_recevoir_message_canal", _sms("STOP", "SM-STOP", recu_le=STOP_LE))["resultat"]
    assert rejoue["doublon"] is True and rejoue["decision"] == "RETRAIT_CONSENTEMENT"
    assert len(_retraits_publies()) == 1 and premier["retrait_publie"]["leads"] == 1


def test_un_stop_sans_aucun_lead_ne_publie_rien_car_il_n_y_a_rien_a_retirer_ailleurs(capacites):
    resultat = _stop(capacites)
    assert _retraits_publies() == []
    assert resultat["retrait_publie"] == {"leads": 0, "evenement_id": None}
    assert [ligne["marqueur"] for ligne in _lignes() if ligne["type_entree"] == "alerte"] == ["retrait_consentement"]


def test_un_stop_ne_retire_pas_les_leads_d_un_autre_correspondant(capacites):
    lead_a = _lead_id(capacites, "SM-A")
    lead_b = _lead_id(capacites, "SM-B", expediteur=AUTRE_NUMERO)
    assert lead_a != lead_b
    _stop(capacites, "SM-STOP-B", expediteur=AUTRE_NUMERO)
    ((_, charge),) = _retraits_publies()
    assert charge["lead_ids"] == [lead_b]


def test_un_correspondant_avec_deux_leads_les_retire_tous_et_un_second_stop_est_un_autre_evenement(capacites):
    premier = _lead_id(capacites, "SM-1")
    second = _lead_id(capacites, "SM-2", REVETEMENT, recu_le="2026-09-29T15:00:00-04:00")
    assert premier != second
    _stop(capacites, "SM-STOP-1")
    _stop(capacites, "SM-STOP-2", recu_le="2026-09-30T09:00:00-04:00")
    (id1, charge1), (id2, charge2) = _retraits_publies()
    assert charge1["lead_ids"] == charge2["lead_ids"] == [premier, second]
    assert id1 != id2 and charge2["signal_id"] == "sms:SM-STOP-2"


# -- un lead ouvert APRÈS le STOP est retiré lui aussi  ---
def test_un_lead_ouvert_apres_le_stop_est_retire_pour_ce_lead_seul_avec_l_heure_du_stop(capacites):
    avant = _lead_id(capacites, "SM-1")
    _stop(capacites)
    apres = _lead_id(capacites, "SM-2", REVETEMENT, recu_le="2026-10-15T10:00:00-04:00")
    assert apres != avant

    (id1, charge1), (id2, charge2) = _retraits_publies()
    assert charge1["lead_ids"] == [avant]
    assert charge2 == {"lead_ids": [apres], "canal": "sms", "horodatage": STOP_LE, "signal_id": "sms:SM-STOP"}
    assert id2 == retrait.identifiant_evenement("sms:SM-STOP", [apres]) and id1 != id2


def test_un_lead_d_un_correspondant_qui_ne_s_est_pas_retire_ne_publie_aucun_retrait(capacites):
    _lead_id(capacites, "SM-A")
    _stop(capacites, "SM-STOP-B", expediteur=AUTRE_NUMERO)  # un autre correspondant, sans lead : rien à publier
    _lead_id(capacites, "SM-A2", REVETEMENT, recu_le="2026-10-15T10:00:00-04:00")
    assert _retraits_publies() == []


def test_un_lead_rejoue_apres_le_stop_ne_publie_pas_un_second_retrait(capacites):
    _stop(capacites)
    message = _sms(REVETEMENT, "SM-2", recu_le="2026-10-15T10:00:00-04:00")
    capacites.appeler("m1_recevoir_message_canal", message)
    capacites.appeler("m1_recevoir_message_canal", message)
    assert len(_retraits_publies()) == 1


# -- atomicité et registre en mémoire  ---
def test_l_alerte_et_la_publication_du_retrait_reussissent_ou_echouent_ensemble(capacites, monkeypatch):
    _lead_id(capacites)
    avant = _lignes()
    publier = evenements.publier

    def panne_pour_le_retrait(type_evenement, *args, **kwargs):
        if type_evenement == "m1.retrait_consentement":
            raise ValueError("bus indisponible")
        return publier(type_evenement, *args, **kwargs)

    with monkeypatch.context() as panne:
        panne.setattr(outils_m1.evenements, "publier", panne_pour_le_retrait)
        reponse = capacites.appeler("m1_recevoir_message_canal", _sms("STOP", "SM-STOP", recu_le=STOP_LE))
    assert reponse["ok"] is False and "bus indisponible" in reponse["details"]
    assert _lignes() == avant and _retraits_publies() == []  # ni signal ni alerte : le STOP pourra être rejoué
    assert _stop(capacites)["retrait_publie"]["leads"] == 1 and len(_retraits_publies()) == 1


def test_avec_le_registre_en_memoire_rien_n_est_publie_mais_la_reponse_compte_les_leads(declarer_services):
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    outils_m1.reinitialiser_registre()
    try:
        outils_m1.recevoir_message_canal(**_sms(GOUTTIERES, "SM-1"))
        reponse = outils_m1.recevoir_message_canal(**_sms("STOP", "SM-STOP", recu_le=STOP_LE))
        assert reponse["retrait_publie"] == {"leads": 1, "evenement_id": None}
    finally:
        outils_m1.reinitialiser_registre()


# -- le schéma du catalogue est fermé  ---
CHARGE_VALIDE = {"lead_ids": ["lead-1"], "canal": "sms", "horodatage": STOP_LE, "signal_id": "sms:SM-1"}


def test_le_type_est_au_catalogue_et_sa_charge_valide_est_acceptee():
    assert "m1.retrait_consentement" in evenements.types_connus()
    assert evenements.schemas.erreurs_charge("m1.retrait_consentement", CHARGE_VALIDE) == []


@pytest.mark.parametrize(("modification", "attendu"), [
    ({"telephone": NUMERO}, "telephone"),  # un contact en clair : refusé par le schéma fermé
    ({"contact": {"telephone": NUMERO}}, "contact"),
    ({"conversation_id": CONVERSATION}, "conversation_id"),
    ({"texte": "STOP"}, "texte"),
    ({"lead_ids": []}, "lead_ids"),  # jamais vide : rien à retirer
    ({"lead_ids": ["lead-1", "lead-1"]}, "lead_ids"),
    ({"lead_ids": [""]}, "lead_ids"),
    ({"lead_ids": "lead-1"}, "lead_ids"),
    ({"canal": "telephone"}, "canal"),
    ({"horodatage": ""}, "horodatage"),
    ({"signal_id": ""}, "signal_id"),
])
def test_le_schema_ferme_refuse_tout_ce_qui_n_est_pas_la_charge_prevue(modification, attendu):
    erreurs = evenements.schemas.erreurs_charge("m1.retrait_consentement", {**CHARGE_VALIDE, **modification})
    assert erreurs and any(attendu in erreur for erreur in erreurs), erreurs


@pytest.mark.parametrize("cle", ["lead_ids", "canal", "horodatage", "signal_id"])
def test_chaque_champ_de_la_charge_est_requis(cle):
    incomplete = {k: v for k, v in CHARGE_VALIDE.items() if k != cle}
    assert any(cle in erreur for erreur in evenements.schemas.erreurs_charge("m1.retrait_consentement", incomplete))


def test_m1_declare_qu_il_publie_le_retrait():
    assert "m1.retrait_consentement" in lire_manifeste(M1).evenements_publie
