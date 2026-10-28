"""PLAN T4.6 (M2.11) : `m2_lister_leads` par le VRAI outil, comme en production.

Le vrai `outils()` de M2, le registre durable adossé à une base SQLite migrée, `executer_atomique` (la transaction
et la validation des arguments d'un appel réel), de vraies personnes (`opsys.identite`). L'identité d'un appel
d'appareil est celle que `Capacites.appeler` et `serveur_mcp.appeler_outil` posent (`contexte.appele_par_appareil`) :
la porte d'appareil complète (jeton, `_meta`, moteur HTTP) est prouvée par `tests/e2e/test_liste_leads_vendeur.py`.

Ce qui est prouvé ici : le vendeur ne voit que ses leads (par l'identité confirmée en base, jamais par un argument),
l'admin et l'agent voient tout, un employé ou une identité non confirmée est refusé sans rien écrire, les seuils
viennent de `department.yaml` (vides : « seuil à configurer », jamais une valeur inventée), les faits de M3 sont lus
au registre durable, et la sortie tient sous la limite du socle. Données fictives.
"""

from __future__ import annotations

import json

import pytest
import yaml
from m2_revenue_crm import acces, liste_leads, outils, segments, statuts
from sqlalchemy import select

from opsys import contexte, identite, jetons, stockage
from opsys.outils import Autonomie, executer_atomique
from opsys.stockage.schema import META

FICTIF = True

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
VENDEUR_UN = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
VENDEUR_DEUX = contexte.IdentiteAppelante(personne="vendeur.deux", role="seller")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")

CODE_INVALIDE = "REJ-IDENTITE-APPAREIL-INVALIDE"
H0 = "2026-09-01T09:00:00-04:00"
H1 = "2026-09-01T09:05:00-04:00"
H2 = "2026-09-29T12:00:00-04:00"
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}
LIMITE_SORTIE = jetons.LIMITE_SORTIE_DEFAUT


# -- installation -----------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m2-liste.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    outils.utiliser_stockage_durable()
    try:
        yield url
    finally:
        outils.reinitialiser_registre()
        stockage.liberer()


@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", "mot-de-passe-vendeur-un-1", ["seller"])
        identite.creer_personne(cnx, "vendeur.deux", "Vendeur Deux", "mot-de-passe-vendeur-deux", ["seller"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(
            cnx, "ancien.vendeur", "Ancien Vendeur", "mot-de-passe-ancien-123", ["seller"], actif=False)


@pytest.fixture
def par_nom(personnes):
    return {o.nom: o for o in outils.outils()}


def _contrat(lead_id: str, *, urgence: bool = False) -> dict:
    return {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": f"Client {lead_id}", "courriel": f"{lead_id}@example.test"},
        "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": urgence, "canal": "telephone",
    }


def _ingerer_et_qualifier(lead_id: str, owner: str | None, *, urgence: bool = False, horodatage: str = H0) -> None:
    """Préparation par la voie des agents (sans identité d'appareil)."""
    assert outils.ingerer_lead(_contrat(lead_id, urgence=urgence), horodatage)["accepte"] is True
    if owner is not None:
        reponse = outils.transitionner_statut(lead_id, "qualifie", H1, owner=owner, prochaine_action=ACTION)
        assert reponse["accepte"] is True, reponse


@pytest.fixture
def leads(personnes):
    """Deux leads à chaque vendeur (un urgent chacun), un lead `nouveau` sans propriétaire, un lead dont
    `owner` est un nom (texte libre) : à personne."""
    _ingerer_et_qualifier("lead-un1", "vendeur.un", urgence=True, horodatage="2026-09-01T09:00:00-04:00")
    _ingerer_et_qualifier("lead-un2", "vendeur.un", horodatage="2026-09-01T09:01:00-04:00")
    _ingerer_et_qualifier("lead-deux1", "vendeur.deux", horodatage="2026-09-01T09:02:00-04:00")
    _ingerer_et_qualifier("lead-deux2", "vendeur.deux", urgence=True, horodatage="2026-09-01T09:03:00-04:00")
    _ingerer_et_qualifier("lead-nouveau", None, horodatage="2026-09-01T09:04:00-04:00")
    _ingerer_et_qualifier("lead-orphelin", "Alice", horodatage="2026-09-01T09:05:00-04:00")


def _appeler(par_nom, arguments, identite_appelante=None):
    if identite_appelante is None:
        return executer_atomique(par_nom["m2_lister_leads"], arguments)
    with contexte.appele_par_appareil(identite_appelante):
        return executer_atomique(par_nom["m2_lister_leads"], arguments)


def _page(reponse: dict) -> dict:
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _verdict(reponse: dict) -> dict:
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def _ids(page: dict) -> list[str]:
    return [lead["lead_id"] for lead in page["leads"]]


def _instantane_base() -> dict:
    with stockage.transaction() as cnx:
        return {
            nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
            for nom, table in META.tables.items()
        }


def _installer_seuils(monkeypatch, tmp_path, segments_config) -> None:
    """Le `department.yaml` de M2 dont seul le bloc `segments` change : M2 le relit à chaque appel."""
    reel = yaml.safe_load(outils._MANIFESTE.read_text(encoding="utf-8"))
    manifeste = {**reel, "configuration": {**reel["configuration"], "segments": segments_config}}
    chemin = tmp_path / "department-m2-seuils.yaml"
    chemin.write_text(yaml.safe_dump(manifeste, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(outils, "_MANIFESTE", chemin)


# ---------------------------------------------------------------------------------------------------------
# La déclaration de l'outil
# ---------------------------------------------------------------------------------------------------------
def test_l_outil_est_une_lecture_ouverte_au_vendeur_et_a_l_admin_seulement(par_nom):
    outil = par_nom["m2_lister_leads"]
    assert outil.autonomie is Autonomie.T0
    assert outil.roles_appareil == acces.ROLES_LEADS == frozenset({"seller", "admin"})
    assert "employee" not in outil.roles_appareil
    assert outil.fonction is outils.lister_leads
    assert len(outil.description) <= 1024


def test_le_schema_exige_l_horodatage_et_enumere_les_statuts_et_les_segments(par_nom):
    schema = par_nom["m2_lister_leads"].parametres
    assert schema["required"] == ["horodatage"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"statut", "segment", "decalage", "limite", "horodatage", "recherche"}
    assert schema["properties"]["recherche"]["type"] == ["string", "null"]
    assert schema["properties"]["recherche"]["maxLength"] == 120
    assert schema["properties"]["statut"]["enum"] == [*statuts.STATUTS, None]
    assert schema["properties"]["segment"]["enum"] == [*segments.SEGMENTS, None]
    assert schema["properties"]["limite"]["maximum"] == liste_leads.LIMITE_MAX
    assert schema["properties"]["decalage"]["minimum"] == 0
    assert "montant" not in json.dumps(schema).lower()


def test_la_borne_de_sortie_laisse_la_place_de_l_enveloppe_du_socle():
    assert outils.BUDGET_SORTIE == LIMITE_SORTIE - 100


@pytest.mark.parametrize("arguments", [
    {}, {"horodatage": H2, "lead_id": "lead-un1"}, {"horodatage": H2, "limite": True},
    {"horodatage": H2, "decalage": "0"}, {"horodatage": H2, "statut": "inconnu"}, {"horodatage": H2, "segment": "x"},
    {"horodatage": 5},
])
def test_des_arguments_hors_schema_sont_refuses_avant_l_outil(par_nom, leads, arguments):
    reponse = _appeler(par_nom, arguments, ADMIN)
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", reponse


# ---------------------------------------------------------------------------------------------------------
# Qui voit quoi
# ---------------------------------------------------------------------------------------------------------
def test_le_vendeur_ne_voit_que_ses_leads(par_nom, leads):
    page = _page(_appeler(par_nom, {"horodatage": H2}, VENDEUR_UN))
    assert _ids(page) == ["lead-un1", "lead-un2"]
    assert page["total"] == 2
    assert {lead["proprietaire"] for lead in page["leads"]} == {"vendeur.un"}
    texte = json.dumps(page, ensure_ascii=False)
    for invisible in ("lead-deux1", "lead-deux2", "lead-nouveau", "lead-orphelin", "vendeur.deux", "Alice"):
        assert invisible not in texte


def test_l_autre_vendeur_voit_les_siens_et_pas_ceux_du_premier(par_nom, leads):
    page = _page(_appeler(par_nom, {"horodatage": H2}, VENDEUR_DEUX))
    assert _ids(page) == ["lead-deux1", "lead-deux2"]
    assert "lead-un1" not in json.dumps(page)


def test_l_admin_voit_tous_les_leads_dont_le_nouveau_et_celui_d_un_nom_libre(par_nom, leads):
    page = _page(_appeler(par_nom, {"horodatage": H2}, ADMIN))
    assert _ids(page) == ["lead-un1", "lead-un2", "lead-deux1", "lead-deux2", "lead-nouveau", "lead-orphelin"]
    assert page["total"] == 6
    par_id = {lead["lead_id"]: lead for lead in page["leads"]}
    assert par_id["lead-nouveau"]["proprietaire"] is None
    assert par_id["lead-orphelin"]["proprietaire"] == "Alice"


def test_sans_identite_d_appareil_la_voie_des_agents_voit_tout_comme_avant(par_nom, leads):
    assert _ids(_page(_appeler(par_nom, {"horodatage": H2}))) == [
        "lead-un1", "lead-un2", "lead-deux1", "lead-deux2", "lead-nouveau", "lead-orphelin"]


def test_un_argument_ne_peut_pas_designer_un_autre_vendeur(par_nom, leads):
    """Aucun paramètre ne désigne une personne : le schéma refuse `owner`, `proprietaire` et `vendeur`."""
    for cle in ("owner", "proprietaire", "vendeur", "personne"):
        reponse = _appeler(par_nom, {"horodatage": H2, cle: "vendeur.deux"}, VENDEUR_UN)
        assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"


def test_le_filtre_par_segment_reste_dans_les_leads_du_vendeur(par_nom, leads):
    assert _ids(_page(_appeler(par_nom, {"horodatage": H2, "segment": "hot_lead"}, VENDEUR_UN))) == ["lead-un1"]
    assert _ids(_page(_appeler(par_nom, {"horodatage": H2, "segment": "hot_lead"}, VENDEUR_DEUX))) == ["lead-deux2"]
    assert _ids(_page(_appeler(par_nom, {"horodatage": H2, "segment": "hot_lead"}, ADMIN))) == [
        "lead-un1", "lead-deux2"]


def test_le_filtre_par_statut_reste_dans_les_leads_du_vendeur(par_nom, leads):
    assert _ids(_page(_appeler(par_nom, {"horodatage": H2, "statut": "nouveau"}, VENDEUR_UN))) == []
    assert _ids(_page(_appeler(par_nom, {"horodatage": H2, "statut": "nouveau"}, ADMIN))) == ["lead-nouveau"]
    assert _ids(_page(_appeler(par_nom, {"horodatage": H2, "statut": "qualifie"}, VENDEUR_UN))) == [
        "lead-un1", "lead-un2"]


def test_un_vendeur_sans_lead_recoit_une_page_vide_pas_un_refus(par_nom, personnes):
    page = _page(_appeler(par_nom, {"horodatage": H2}, VENDEUR_UN))
    assert page["leads"] == [] and page["total"] == 0 and page["suivant"] is None


@pytest.fixture(params=[
    pytest.param(contexte.IdentiteAppelante(personne="inconnu.fictif", role="seller"), id="personne-inconnue"),
    pytest.param(contexte.IdentiteAppelante(personne="ancien.vendeur", role="seller"), id="personne-desactivee"),
    pytest.param(contexte.IdentiteAppelante(personne="vendeur.un", role="admin"), id="role-jamais-porte"),
    pytest.param(MARC, id="employe-sans-portee"),
])
def identite_invalide(request):
    return request.param


def test_une_identite_non_confirmee_ou_un_employe_est_refuse_sans_rien_ecrire(par_nom, leads, identite_invalide):
    avant = _instantane_base()
    verdict = _verdict(_appeler(par_nom, {"horodatage": H2}, identite_invalide))
    assert verdict["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


def test_hors_transaction_l_identite_n_est_pas_verifiable_donc_refusee(par_nom, leads):
    avant = _instantane_base()
    with contexte.appele_par_appareil(VENDEUR_UN):
        reponse = par_nom["m2_lister_leads"].fonction(horodatage=H2)
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


def test_un_role_retire_depuis_l_appairage_est_refuse_avec_le_meme_jeton(par_nom, leads):
    assert _page(_appeler(par_nom, {"horodatage": H2}, VENDEUR_UN))["total"] == 2
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "vendeur.un", "seller")
        identite.ajouter_role(cnx, "vendeur.un", "employee")
    assert _verdict(_appeler(par_nom, {"horodatage": H2}, VENDEUR_UN))["code"] == CODE_INVALIDE


def test_lister_ne_change_rien_a_la_base_ni_pour_l_admin_ni_pour_le_vendeur(par_nom, leads):
    avant = _instantane_base()
    for appelante in (ADMIN, VENDEUR_UN, None):
        _page(_appeler(par_nom, {"horodatage": H2}, appelante))
        _page(_appeler(par_nom, {"horodatage": H2, "segment": "hot_lead", "limite": 1}, appelante))
    assert _instantane_base() == avant


def test_les_refus_de_filtre_et_de_pagination_ne_changent_rien_non_plus(par_nom, leads):
    avant = _instantane_base()
    for arguments, code in (
        ({"horodatage": H2, "segment": "needs_photos"}, "REJ-SEGMENT-NON-CALCULABLE"),
        ({"horodatage": H2, "segment": "dormant_lead"}, "REJ-SEGMENT-NON-CALCULABLE"),
        ({"horodatage": H2, "limite": 0}, "REJ-PAGINATION-INVALIDE"),
        ({"horodatage": H2, "decalage": -1}, "REJ-PAGINATION-INVALIDE"),
        ({"horodatage": "hier"}, "REJ-HORODATAGE-INVALIDE"),
    ):
        assert _verdict(_appeler(par_nom, arguments, VENDEUR_UN))["code"] == code
    assert _instantane_base() == avant


def test_l_identite_est_verifiee_avant_les_arguments(par_nom, leads):
    """Un employé qui envoie en plus un argument invalide reçoit le refus d'identité, pas un détail de schéma
    métier : rien ne fuit à qui n'a aucune portée."""
    verdict = _verdict(_appeler(par_nom, {"horodatage": H2, "limite": 3, "segment": "needs_photos"}, MARC))
    assert verdict["code"] == CODE_INVALIDE


# ---------------------------------------------------------------------------------------------------------
# Les seuils de department.yaml
# ---------------------------------------------------------------------------------------------------------
def test_le_department_yaml_livre_ses_seuils_vides_jamais_une_valeur_inventee():
    reel = yaml.safe_load(outils._MANIFESTE.read_text(encoding="utf-8"))
    assert reel["configuration"]["segments"] == {}
    seuils = outils._seuils_segments()
    assert {cle: seuil["etat"] for cle, seuil in seuils.items()} == {
        "jours_inactivite_dormant": "a_configurer", "jours_soumission_perimee": "a_configurer"}
    assert all(seuil["valeur"] is None for seuil in seuils.values())


def test_avec_le_manifeste_livre_dormant_et_devis_perime_sont_refuses_seuil_a_configurer(par_nom, leads):
    for segment in ("dormant_lead", "quote_stale"):
        verdict = _verdict(_appeler(par_nom, {"horodatage": "2030-01-01T12:00:00-04:00", "segment": segment}, ADMIN))
        assert verdict["code"] == "REJ-SEGMENT-NON-CALCULABLE"
        assert "seuil à configurer" in verdict["detail"]
    # Et la liste, elle, ne déclare aucun lead dormant, même cinq ans plus tard : elle le dit non calculable.
    page = _page(_appeler(par_nom, {"horodatage": "2030-01-01T12:00:00-04:00"}, ADMIN))
    assert all(s["segment"] != "dormant_lead" for lead in page["leads"] for s in lead["segments"])
    assert "dormant_lead" in [n["segment"] for n in page["segments_non_calculables"]]


def test_un_seuil_configure_rend_dormant_calculable_et_se_relit_a_chaque_appel(par_nom, leads, monkeypatch, tmp_path):
    _installer_seuils(monkeypatch, tmp_path, {"jours_inactivite_dormant": 30})
    page = _page(_appeler(par_nom, {"horodatage": "2026-10-15T12:00:00-04:00", "segment": "dormant_lead"}, ADMIN))
    assert _ids(page) == ["lead-un1", "lead-un2", "lead-deux1", "lead-deux2", "lead-nouveau", "lead-orphelin"]
    tot = _page(_appeler(par_nom, {"horodatage": "2026-09-20T12:00:00-04:00", "segment": "dormant_lead"}, ADMIN))
    assert tot["leads"] == []
    _installer_seuils(monkeypatch, tmp_path, {"jours_inactivite_dormant": 90})
    assert _page(_appeler(par_nom, {"horodatage": "2026-10-15T12:00:00-04:00", "segment": "dormant_lead"},
                          ADMIN))["leads"] == []


@pytest.mark.parametrize("configuration", [
    {"jours_inactivite_dormant": 0}, {"jours_inactivite_dormant": "trente"}, {"jours_inactivite_dormant": True},
    {"jours_inactivite_dormant": 2.5}, ["trente"],
])
def test_un_seuil_invalide_est_refuse_comme_invalide_pas_comme_absent(
        par_nom, leads, monkeypatch, tmp_path, configuration):
    _installer_seuils(monkeypatch, tmp_path, configuration)
    verdict = _verdict(_appeler(par_nom, {"horodatage": H2, "segment": "dormant_lead"}, ADMIN))
    assert verdict["code"] == "REJ-SEGMENT-NON-CALCULABLE"
    assert "seuil invalide" in verdict["detail"]
    assert "seuil à configurer" not in verdict["detail"]


@pytest.mark.parametrize("contenu", ["", "configuration:\n", "configuration: {}\n", "autre: 1\n"])
def test_un_manifeste_sans_bloc_segments_donne_seuil_a_configurer(par_nom, leads, monkeypatch, tmp_path, contenu):
    chemin = tmp_path / "vide.yaml"
    chemin.write_text(contenu, encoding="utf-8")
    monkeypatch.setattr(outils, "_MANIFESTE", chemin)
    verdict = _verdict(_appeler(par_nom, {"horodatage": H2, "segment": "dormant_lead"}, ADMIN))
    assert "seuil à configurer" in verdict["detail"]


def test_une_configuration_illisible_donne_seuil_invalide(par_nom, leads, monkeypatch, tmp_path):
    chemin = tmp_path / "casse.yaml"
    chemin.write_text("configuration: 12\n", encoding="utf-8")
    monkeypatch.setattr(outils, "_MANIFESTE", chemin)
    verdict = _verdict(_appeler(par_nom, {"horodatage": H2, "segment": "dormant_lead"}, ADMIN))
    assert "seuil invalide" in verdict["detail"]


# ---------------------------------------------------------------------------------------------------------
# Les faits de M3, lus au registre durable
# ---------------------------------------------------------------------------------------------------------
def _recevoir_devis_sans_reponse(lead_id: str, devis_id: str, statut: str, horodatage_devis: str) -> None:
    """Le consommateur réel de M2 écrit le fait au registre durable `relances_devis_recues`."""
    charge = {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "statut": statut,
        "horodatage_devis": horodatage_devis, "horodatage_reference": "2026-09-20T12:00:00-04:00",
        "delai_relance_jours": 7,
    }
    with stockage.transaction():
        outils._recevoir_devis_sans_reponse(charge)


def test_un_devis_envoye_sans_reponse_rend_le_lead_du_vendeur_perime_et_pas_celui_de_l_autre(
        par_nom, leads, monkeypatch, tmp_path):
    _installer_seuils(monkeypatch, tmp_path, {"jours_soumission_perimee": 14})
    _recevoir_devis_sans_reponse("lead-un1", "devis-1", "envoye", "2026-08-01T12:00:00-04:00")
    _recevoir_devis_sans_reponse("lead-deux1", "devis-2", "brouillon", "2026-08-01T12:00:00-04:00")

    un = _page(_appeler(par_nom, {"horodatage": H2, "segment": "quote_stale"}, VENDEUR_UN))
    assert _ids(un) == ["lead-un1"]
    segment = next(s for s in un["leads"][0]["segments"] if s["segment"] == "quote_stale")
    assert segment["regle"] == "devis_envoye_sans_reponse_perime"
    assert segment["donnee"]["devis_id"] == "devis-1"
    assert segment["donnee"]["jours_ecoules"] == 59 and segment["donnee"]["seuil_jours"] == 14
    assert _ids(_page(_appeler(par_nom, {"horodatage": H2, "segment": "quote_stale"}, VENDEUR_DEUX))) == []
    assert _ids(_page(_appeler(par_nom, {"horodatage": H2, "segment": "quote_stale"}, ADMIN))) == ["lead-un1"]


def test_l_ecriture_du_systeme_de_la_relance_ne_reveille_pas_un_lead_dormant(par_nom, leads, monkeypatch, tmp_path):
    _installer_seuils(monkeypatch, tmp_path, {"jours_inactivite_dormant": 30})
    _recevoir_devis_sans_reponse("lead-un1", "devis-1", "envoye", "2026-09-05T12:00:00-04:00")  # interaction system:m3
    page = _page(_appeler(par_nom, {"horodatage": "2026-10-20T12:00:00-04:00", "segment": "dormant_lead"}, VENDEUR_UN))
    assert "lead-un1" in _ids(page)
    lead = next(item for item in page["leads"] if item["lead_id"] == "lead-un1")
    assert lead["derniere_activite"] == H1  # la qualification, pas l'interaction système du 20 septembre


def test_registre_en_memoire_les_faits_de_m3_n_existent_pas_quote_stale_est_non_calculable(
        par_nom, monkeypatch, tmp_path):
    _installer_seuils(monkeypatch, tmp_path, {"jours_soumission_perimee": 14})
    outils.reinitialiser_registre()
    assert outils._devis_sans_reponse_recus() is None
    reponse = outils.lister_leads(H2, segment="quote_stale")
    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-SEGMENT-NON-CALCULABLE"
    assert "relances_devis_recues" in reponse["verdict"]["detail"]


def test_registre_durable_les_faits_de_m3_sont_lus_vides_quand_rien_n_est_recu(par_nom, leads):
    assert outils._devis_sans_reponse_recus() == []


# ---------------------------------------------------------------------------------------------------------
# Pagination et taille de sortie, par l'enveloppe réelle du socle
# ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def quarante_leads(personnes):
    for i in range(40):
        _ingerer_et_qualifier(f"lead-{i:03d}", "vendeur.un", urgence=(i % 4 == 0),
                              horodatage=f"2026-09-01T09:{i:02d}:00-04:00")
    for i in range(5):
        _ingerer_et_qualifier(f"lead-autre-{i}", "vendeur.deux", horodatage=f"2026-09-02T09:{i:02d}:00-04:00")


def test_le_vendeur_lit_ses_quarante_leads_page_par_page_sans_doublon_ni_trou_et_sans_troncature(
        par_nom, quarante_leads):
    lus: list[str] = []
    decalage = 0
    pages = 0
    while True:
        reponse = _appeler(par_nom, {"horodatage": H2, "limite": 50, "decalage": decalage}, VENDEUR_UN)
        assert len(json.dumps(reponse, ensure_ascii=False)) <= LIMITE_SORTIE, "la sortie serait tronquée"
        page = _page(reponse)
        lus += _ids(page)
        pages += 1
        assert page["total"] == 40
        if page["suivant"] is None:
            break
        decalage = page["suivant"]
        assert pages < 50
    assert pages > 1, "40 leads tiennent en une page : la borne de sortie n'est pas exercée"
    assert lus == [f"lead-{i:03d}" for i in range(40)]
    assert not any("autre" in lead_id for lead_id in lus)


def test_la_page_de_l_admin_tient_aussi_sous_la_limite_avec_les_segments_les_regles_et_les_manques(
        par_nom, quarante_leads):
    reponse = _appeler(par_nom, {"horodatage": H2, "limite": 50}, ADMIN)
    page = _page(reponse)
    assert len(json.dumps(reponse, ensure_ascii=False)) <= LIMITE_SORTIE
    assert page["regles"] and page["segments_non_calculables"]
    assert page["total"] == 45


def test_deux_lectures_du_meme_etat_rendent_la_meme_reponse(par_nom, leads):
    premiere = _appeler(par_nom, {"horodatage": H2}, VENDEUR_UN)
    seconde = _appeler(par_nom, {"horodatage": H2}, VENDEUR_UN)
    assert premiere == seconde


def test_la_page_dit_quand_elle_en_montre_moins_que_le_total(par_nom, quarante_leads):
    page = _page(_appeler(par_nom, {"horodatage": H2, "limite": 50}, VENDEUR_UN))
    assert page["affichees"] < 40
    assert page["reste"] == 40 - page["affichees"]
    assert page["suivant"] == page["affichees"]
    assert f"decalage={page['suivant']}" in page["message"]
