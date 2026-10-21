"""Le STOP de M1 arrive par le bus et devient un retrait du consentement marketing (PLAN T4.17-c, Loi 25).

M7 consomme `m1.retrait_consentement` : les `lead_id` que M1 avait ouverts pour le correspondant qui a écrit STOP.
Il inscrit UN retrait par lead au registre `retraits_consentement_marketing`, sans `wct_id`, sans contact : tout
chantier de ces leads est bloqué, celui déjà reçu comme celui qui arrivera, y compris un paquet déjà exporté.

Ce fichier prouve M7 seul, avec la charge que M1 publie (`tests/test_stop_retire_consentement_marketing.py`, à la
racine, la prouve de bout en bout par le vrai bus). Données fictives.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m7_marketing import outils
from m7_marketing.brand import profil_client
from m7_marketing.usine import service
from m7_marketing.usine.retrait import CANAUX_RETRAIT, construire_retrait_de_lead, retrait_applicable

from opsys import contexte, identite, stockage
from opsys.departements import lire_manifeste
from opsys.outils import executer_atomique

FICTIF = True
HORODATAGE = "2026-09-29T10:00:00-04:00"
STOP = "2026-09-30T08:15:00-04:00"
_OUTILS = {o.nom: o for o in outils.outils()}
RACINE_M7 = Path(__file__).resolve().parents[2]


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan fictif", "mot-de-passe-de-test-1234", ["nathan_owner", "admin"])
    yield url
    stockage.liberer()


@pytest.fixture
def brand_configure(monkeypatch, profil):
    monkeypatch.setattr(profil_client, "charger_profil_client", lambda: (dict(profil), None))
    return profil


def _charge_stop(*lead_ids, canal="sms", horodatage=STOP, signal_id="sms:SM-STOP-1"):
    """La charge que M1 publie (`m1_front_office.retrait.charge`) : leads, canal du core, heure et signal du STOP."""
    return {"lead_ids": list(lead_ids), "canal": canal, "horodatage": horodatage, "signal_id": signal_id}


def _recevoir_stop(charge):
    with stockage.transaction():
        return outils.consommateurs()["m1.retrait_consentement"](dict(charge))


def _recevoir_wct(charge):
    with stockage.transaction():
        return outils.consommateurs()["m4.travaux_termines"](dict(charge))


def _appeler(nom, *, appareil=None, **arguments):
    if appareil is None:
        return executer_atomique(_OUTILS[nom], arguments)
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(*appareil)):
        return executer_atomique(_OUTILS[nom], arguments)


def _metier(reponse):
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _lire(nom):
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", nom))


def _contenus(**filtres):
    return _metier(_appeler("m7_lister_contenus_chantier", limite=8, **filtres))["contenus"]


def _id(plateforme, wct_id="wct-usine-1"):
    (contenu,) = [c for c in _contenus(wct_id=wct_id) if c["plateforme"] == plateforme]
    return contenu["contenu_id"]


# -- le consommateur est déclaré, au manifeste et au code --------------------------------------------------------------
def test_m7_declare_et_consomme_le_stop_de_m1():
    manifeste = lire_manifeste(RACINE_M7)
    assert "m1.retrait_consentement" in manifeste.evenements_consomme
    assert "m01-front-office" in manifeste.dependances
    assert set(outils.consommateurs()) == set(manifeste.evenements_consomme)


# -- un retrait par lead, sans contact ni chantier ------------------------------------------------------------
def test_le_stop_inscrit_un_retrait_par_lead_sans_wct_ni_contact(base_durable):
    resume = _recevoir_stop(_charge_stop("lead-a", "lead-b"))
    assert resume["traite"] is True and resume["retraits_ecrits"] == 2 and resume["deja_enregistres"] == 0
    a, b = _lire("retraits_consentement_marketing")
    assert (a["lead_id"], b["lead_id"]) == ("lead-a", "lead-b")
    assert a["wct_id"] is None and b["wct_id"] is None
    assert a["retrait_id"] != b["retrait_id"]
    assert (a["canal"], a["source"], a["enregistre_par"], a["horodatage"]) == (
        "sms", "bus:m1.retrait_consentement", "bus:m1.retrait_consentement", STOP)
    # Le registre ne devient pas un second dossier de renseignements personnels : ni contact, ni texte, ni conversation.
    assert set(a) == {"retrait_id", "wct_id", "lead_id", "canal", "enregistre_par", "source", "horodatage"}


def test_le_stop_est_idempotent_et_le_premier_retrait_fait_foi(base_durable):
    _recevoir_stop(_charge_stop("lead-a", horodatage=STOP))
    encore = _recevoir_stop(_charge_stop("lead-a", canal="courriel", horodatage="2026-10-02T09:00:00-04:00"))
    assert encore["retraits_ecrits"] == 0 and encore["deja_enregistres"] == 1
    (maillon,) = _lire("retraits_consentement_marketing")
    assert (maillon["canal"], maillon["horodatage"]) == ("sms", STOP)


def test_un_lead_en_double_dans_la_charge_n_ecrit_qu_un_retrait(base_durable):
    resume = _recevoir_stop({**_charge_stop("lead-a"), "lead_ids": ["lead-a", "lead-a"]})
    assert resume["retraits_ecrits"] == 1
    assert len(_lire("retraits_consentement_marketing")) == 1


# -- ce que le retrait bloque ---------------------------------------------------------------------------------
def test_le_stop_bloque_tout_contenu_du_lead_y_compris_un_paquet_deja_exporte(
    base_durable, brand_configure, charge,
):
    _recevoir_wct(charge)
    facebook, instagram = _id("facebook"), _id("instagram")
    args = {"appareil": ("nathan", "admin"), "horodatage": HORODATAGE}
    _metier(_appeler("m7_decider_contenu", contenu_id=facebook, decision="approuver", **args))
    _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=facebook, horodatage=HORODATAGE))
    with stockage.transaction():
        assert len(outils.attentes()) == 4

    resume = _recevoir_stop(_charge_stop(charge["lead_id"]))
    assert len(resume["contenus_bloques"]) == 5 and resume["contenus_deja_exportes"] == [facebook]
    assert resume["a_faire"] == ["retirer à la main les publications déjà faites avec ces paquets exportés"]

    assert {c["approval_status"] for c in _contenus(wct_id="wct-usine-1")} == {"CONSENTEMENT_RETIRE"}
    with stockage.transaction():
        assert outils.attentes() == []
    decision = _metier(_appeler("m7_decider_contenu", contenu_id=instagram, decision="approuver", **args))
    assert decision["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE"
    export = _metier(_appeler("m7_exporter_paquet_manuel", contenu_id=facebook, horodatage=HORODATAGE))
    assert export["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE"  # approuvé, exporté une fois : bloqué quand même
    reproposition = _metier(_appeler("m7_proposer_contenus_chantier", wct_id="wct-usine-1"))
    assert reproposition["statut"] == "consentement_retire" and len(_lire("contenus_chantier")) == 5


def test_le_stop_bloque_un_chantier_du_lead_pas_encore_arrive(base_durable, brand_configure, fabriquer_charge):
    _recevoir_stop(_charge_stop("lead-usine-1"))
    arrive = _recevoir_wct(fabriquer_charge())
    assert arrive["contenus"]["statut"] == "consentement_retire" and arrive["contenus"]["crees"] == 0
    assert _lire("contenus_chantier") == []


def test_le_stop_bloque_tous_les_chantiers_du_lead_et_pas_ceux_d_un_autre_client(
    base_durable, brand_configure, fabriquer_charge,
):
    _recevoir_wct(fabriquer_charge())
    _recevoir_wct(fabriquer_charge(wct_id="wct-usine-1-bis", horodatage_completion="2026-10-05T14:00:00-04:00"))
    autre = _recevoir_wct(fabriquer_charge(wct_id="wct-usine-3", lead_id="lead-usine-3"))
    assert autre["contenus"]["crees"] == 5

    resume = _recevoir_stop(_charge_stop("lead-usine-1"))
    assert len(resume["contenus_bloques"]) == 10
    assert {c["approval_status"] for c in _contenus(wct_id="wct-usine-1-bis")} == {"CONSENTEMENT_RETIRE"}
    assert {c["approval_status"] for c in _contenus(wct_id="wct-usine-3")} == {"PROPOSE"}


def test_le_stop_ne_bloque_pas_un_lead_qu_il_ne_nomme_pas_meme_au_prefixe_pres(
    base_durable, brand_configure, fabriquer_charge,
):
    _recevoir_stop(_charge_stop("lead-usine-1"))
    proche = _recevoir_wct(fabriquer_charge(wct_id="wct-usine-9", lead_id="lead-usine-10"))
    assert proche["contenus"]["crees"] == 5  # « lead-usine-10 » n'est pas « lead-usine-1 »
    _recevoir_stop(_charge_stop("lead-usine-20", signal_id="sms:SM-STOP-2"))
    court = _recevoir_wct(fabriquer_charge(wct_id="wct-usine-8", lead_id="lead-usine-2"))
    assert court["contenus"]["crees"] == 5  # ni dans l'autre sens : « lead-usine-2 » n'est pas « lead-usine-20 »


def test_le_stop_d_un_lead_bloque_aussi_les_opportunites_que_m2_en_tire_pour_un_client_qui_revient(
    base_durable, brand_configure, fabriquer_charge,
):
    """M2 ouvre `<lead d'origine>~opp~<wct_id>` pour un client qui revient : le chantier suivant le porte."""
    _recevoir_stop(_charge_stop("lead-usine-1"))
    suivant = _recevoir_wct(fabriquer_charge(wct_id="wct-2", lead_id="lead-usine-1~opp~wct-1"))
    assert suivant["contenus"]["statut"] == "consentement_retire" and suivant["contenus"]["crees"] == 0
    autre_client = _recevoir_wct(fabriquer_charge(wct_id="wct-3", lead_id="lead-usine-10~opp~wct-9"))
    assert autre_client["contenus"]["crees"] == 5  # « lead-usine-10 » n'est pas « lead-usine-1 »


def test_le_stop_d_une_opportunite_bloque_le_lead_d_origine_et_ses_autres_opportunites(base_durable):
    _recevoir_stop(_charge_stop("lead-a~opp~wct-1"))
    retraits = _lire("retraits_consentement_marketing")
    for lead in ("lead-a", "lead-a~opp~wct-1", "lead-a~opp~wct-2"):
        assert retrait_applicable("wct-x", lead, retraits) is not None, lead
    for lead in ("lead-b", "lead-ab", "lead-a2~opp~wct-1", "~opp~wct-1", ""):
        assert retrait_applicable("wct-x", lead, retraits) is None, lead


def test_un_retrait_de_lead_se_lit_comme_un_retrait_de_chantier_par_retrait_applicable(base_durable):
    _recevoir_stop(_charge_stop("lead-a"))
    retraits = _lire("retraits_consentement_marketing")
    assert retrait_applicable("wct-quelconque", "lead-a", retraits) is not None
    assert retrait_applicable("wct-quelconque", "lead-b", retraits) is None
    assert retrait_applicable("wct-quelconque", None, retraits) is None  # sans lead, un WCT n'est pas couvert
    assert retrait_applicable(None, "lead-a", retraits) is not None


def test_le_retrait_de_marketing_ne_touche_pas_la_demande_d_avis_un_autre_consentement_limite_documentee(
    base_durable, brand_configure, fabriquer_charge,
):
    """Décision de T1.5-d, inchangée : la demande d'avis naît de `consentement_demande_avis`, un consentement distinct.
    Le STOP la laisse donc naître EN BROUILLON (rien ne part sans approbation humaine). À trancher (GATE Nathan)."""
    _recevoir_stop(_charge_stop("lead-usine-1"))
    resume = _recevoir_wct(fabriquer_charge(consentement_demande_avis=True))
    assert resume["brouillon_cree"] is True and resume["contenus"]["statut"] == "consentement_retire"


# -- fail-closed : un retrait n'est jamais ignoré en silence ---------------------------------------------------
@pytest.mark.parametrize("charge_mauvaise", [
    {**_charge_stop("lead-a"), "lead_ids": []},
    {**_charge_stop("lead-a"), "lead_ids": None},
    {**_charge_stop("lead-a"), "lead_ids": ["lead-a", "  "]},
    {**_charge_stop("lead-a"), "lead_ids": ["lead-a", 7]},
    _charge_stop("lead-a", canal="pigeon"),
    _charge_stop("lead-a", horodatage="tôt"),
    _charge_stop("lead-a", horodatage="2026-09-30T08:15:00"),  # sans fuseau
])
def test_une_charge_illisible_leve_et_n_ecrit_rien(base_durable, charge_mauvaise):
    with pytest.raises(ValueError, match="REJ-RETRAIT-INVALIDE|REJ-HORODATAGE-INVALIDE"), stockage.transaction():
        outils.consommateurs()["m1.retrait_consentement"](dict(charge_mauvaise))
    assert _lire("retraits_consentement_marketing") == []


def test_un_lead_illisible_au_milieu_ne_laisse_pas_les_autres_a_moitie_inscrits(base_durable):
    """La validation précède la première écriture : l'échec est constaté DANS la transaction, avant tout retour arrière
    (celle du répartiteur annulerait de toute façon ; ici, on prouve que M7 n'a rien écrit du tout)."""
    with stockage.transaction():
        with pytest.raises(ValueError, match="REJ-RETRAIT-INVALIDE"):
            outils.consommateurs()["m1.retrait_consentement"](_charge_stop("lead-a", "lead-b", ""))
        assert list(stockage.maillons("m07-marketing", "retraits_consentement_marketing")) == []


def test_construire_retrait_de_lead_valide_chaque_champ_et_reste_deterministe():
    source = "bus:m1.retrait_consentement"
    un, verdict = construire_retrait_de_lead("lead-a", "sms", source, source, STOP)
    assert verdict is None
    assert construire_retrait_de_lead(" lead-a ", "sms", source, source, STOP)[0]["retrait_id"] == un["retrait_id"]
    assert construire_retrait_de_lead("lead-b", "sms", source, source, STOP)[0]["retrait_id"] != un["retrait_id"]
    for canal in CANAUX_RETRAIT:
        assert construire_retrait_de_lead("lead-a", canal, source, source, STOP)[1] is None
    assert construire_retrait_de_lead("", "sms", source, source, STOP)[1]["code"] == "REJ-RETRAIT-INVALIDE"
    assert construire_retrait_de_lead("lead-a", "pigeon", source, source, STOP)[1]["code"] == "REJ-RETRAIT-INVALIDE"
    assert construire_retrait_de_lead("lead-a", "sms", source, source, "tôt")[1]["code"] == "REJ-HORODATAGE-INVALIDE"
    # Un retrait de lead et un retrait de chantier ne se confondent pas : autre identifiant, autre clé.
    assert service.REGISTRE_RETRAITS == ("m07-marketing", "retraits_consentement_marketing")
