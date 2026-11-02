"""`m5_constater_cash_libre_planifie` (T1, N2, agent seulement) : la variante PLANIFIÉE du constat du cash libre.

Chantier C1 de l'analyse M8. `m5_constater_cash_libre` (N3, droit d'appareil admin) ne peut être ni appelé par le
planificateur ni déclaré comme constat planifié. La variante partage son code d'écriture (`_constater_cash_libre`) mais
diffère par ce que le N3 protège : elle n'est déclenchée que par le planificateur durable, ne rend aucun montant, n'a
aucun droit d'appareil. Ce fichier prouve, sur le VRAI socle (base SQLite migrée, registres durables, vrai bus) :
- le contrat (T1/N2, aucun droit d'appareil, aucune zone de saisie de montant) et l'étanchéité avec l'outil N3 ;
- le refus de tout appelant qui n'est pas le planificateur (agent, appareil admin, transport MCP, département appelant),
  AVANT la lecture de tout registre ;
- la publication, la trace, la réponse sans montant, la règle « un constat par jour et par version » PARTAGÉE avec
  l'outil à la demande, le non-calculable publié tel quel, l'absence d'écriture hors du registre de constats et du bus ;
- la garde anti-décaissement sur le nouveau code.

Personnes, montants et identifiants fictifs (AGENTS.md). Cas de référence : cash libre 27861.98.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
from m5_financecore import analyse, conformite, constat_cash_libre, taux_fiscaux
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION
from sqlalchemy import select

from opsys import contexte, evenements, identite, service_acteur_systeme, stockage
from opsys.evenements.schemas import erreurs_charge
from opsys.outils import Niveau, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS, META

FICTIF = True
_RACINE_M5 = Path(__file__).resolve().parents[1]
_PAQUET = _RACINE_M5 / "src" / "m5_financecore"
DEPARTEMENT = "m05-financecore"
TYPE = "m5.cash_libre_constate"
PLANIFIE = "m5_constater_cash_libre_planifie"
A_LA_DEMANDE = "m5_constater_cash_libre"
JOUR = "2026-09-29"
LENDEMAIN = "2026-09-30"
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
CONFIDENCES = ("27861.98", "37654.33", "1981.69", "459.91", "4200.00", "1350.75", "800.00", "Marc Tremblay",
               "brouillon de paie", "estimation du CPA", "relevé du prêt")


def _charger_aides():
    """Les aides du cas de référence du constat à la demande (mêmes registres, mêmes montants calculés à la main)."""
    chemin = Path(__file__).with_name("test_constat_cash_libre_outils.py")
    spec = importlib.util.spec_from_file_location("aides_constat_cash_libre_a_la_demande", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AIDES = _charger_aides()


# ------------------------------------------------------------------------------------------------ installation
@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-constat-planifie.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
    yield url
    stockage.liberer()


@pytest.fixture
def par_nom():
    return {o.nom: o for o in m5_outils.outils()}


@pytest.fixture
def declare(tmp_path, monkeypatch):
    def _declarer(configuration):
        import yaml

        manifeste = tmp_path / "department.yaml"
        manifeste.write_text(yaml.safe_dump({"configuration": configuration}, allow_unicode=True), encoding="utf-8")
        monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    return _declarer


@pytest.fixture
def cas_fictif(declare):
    taux, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    declare(AIDES.CONFIGURATION_COMPLETE)
    AIDES._peupler_mouvements()
    AIDES._peupler_factures_clients(taux)
    AIDES._peupler_a_payer(taux)


@pytest.fixture
def registre_interdit(monkeypatch):
    """Un refus arrive AVANT toute lecture : ouvrir le registre des mouvements échoue le test."""
    appels = []

    def ouvrir(*args, **kwargs):
        appels.append(args)
        raise AssertionError("le registre des mouvements a été ouvert avant le refus")

    monkeypatch.setattr(m5_outils, "_registre_mouvements", ouvrir)
    return appels


def _par_le_planificateur(par_nom, jour=JOUR, outil=PLANIFIE):
    """Un appel DANS un tour du planificateur (l'acteur système opaque est ouvert), comme `appeler_outil` le fait."""
    with service_acteur_systeme.contexte_planificateur():
        return executer_atomique(par_nom[outil], {"aujourd_hui": jour})


def _corps(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _code_refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    assert set(reponse["resultat"]) == {"accepte", "verdict"}, "un refus ne rend ni constat ni montant"
    return reponse["resultat"]["verdict"]["code"]


def _a_la_demande(par_nom, jour=JOUR):
    with contexte.appele_par_appareil(ADMIN):
        return _corps(executer_atomique(par_nom[A_LA_DEMANDE], {"aujourd_hui": jour}))


def _publies():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge)
                             .where(EVENEMENTS_SORTANTS.c.type_evenement == TYPE)).all()
    return sorted(((ligne.evenement_id, codec.decoder(ligne.charge)) for ligne in lignes),
                  key=lambda paire: paire[1]["sequence"])


def _traces():
    with stockage.transaction():
        return list(stockage.maillons(DEPARTEMENT, "constats_cash_libre"))


def _instantane_base():
    with stockage.transaction() as cnx:
        return {nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
                for nom, table in META.tables.items()}


# ===================================================================================================== le contrat
def test_la_variante_est_n2_agent_seulement_sans_zone_de_montant_et_l_outil_a_la_demande_reste_n3(par_nom):
    variante, a_la_demande = par_nom[PLANIFIE], par_nom[A_LA_DEMANDE]

    assert variante.autonomie.value == "T1" and variante.niveau_effectif is Niveau.N2
    assert variante.roles_appareil == frozenset() and variante.frontiere_humaine is False
    assert set(variante.parametres["properties"]) == {"aujourd_hui"}
    assert variante.parametres["required"] == ["aujourd_hui"] and variante.parametres["additionalProperties"] is False
    assert len(variante.description) <= 1024
    for morceau in ("PLANIFIÉE", "planificateur", "AUCUN montant", "deja_constate", "Aucun paiement",
                    "Analyse préparatoire"):
        assert morceau in variante.description, morceau
    assert PLANIFIE in analyse.SORTIES_D_ANALYSE
    # l'outil à la demande n'a bougé ni de niveau ni de droit d'appareil ni de paramètres (rien n'est élargi)
    assert a_la_demande.autonomie.value == "T1" and a_la_demande.niveau_effectif is Niveau.N3
    assert a_la_demande.roles_appareil == frozenset({"admin"})
    assert set(a_la_demande.parametres["properties"]) == {"aujourd_hui", "role", "autorise_couts"}


def test_les_seuls_outils_t3_restent_les_deux_d_avant_et_aucun_n_est_n2_avec_droit_d_appareil_sur_ce_constat(par_nom):
    assert {nom for nom, o in par_nom.items() if o.autonomie.value == "T3"} == {
        "m5_enregistrer_mouvement", "m5_enregistrer_paiement_facture"}
    assert [nom for nom, o in par_nom.items() if "cash_libre" in nom and o.niveau_effectif is Niveau.N2
            and o.roles_appareil] == []


def test_le_manifeste_declare_le_constat_et_la_description_ne_promet_ni_paiement_ni_remise(par_nom):
    description = par_nom[PLANIFIE].description
    import re

    assert not re.search(r"\b(paye|payer|remet|virer|verse)\b", description.replace("comptes à payer", ""))
    assert TYPE in evenements.types_connus()


# ====================================================== le planificateur seul : tout autre appelant est refusé d'abord
def test_sans_planificateur_la_variante_est_refusee_avant_toute_lecture(par_nom, cas_fictif, registre_interdit):
    avant = _instantane_base()

    reponse = executer_atomique(par_nom[PLANIFIE], {"aujourd_hui": JOUR})

    assert _code_refus(reponse) == "REJ-CONSTAT-PLANIFICATEUR-SEULEMENT"
    assert _instantane_base() == avant and registre_interdit == []


def test_un_appareil_admin_est_refuse_meme_sous_le_nom_du_planificateur(par_nom, cas_fictif, registre_interdit):
    avant = _instantane_base()

    with contexte.appele_par_appareil(ADMIN):
        assert _code_refus(executer_atomique(par_nom[PLANIFIE], {"aujourd_hui": JOUR})) == (
            "REJ-CONSTAT-PLANIFICATEUR-SEULEMENT")

    assert _instantane_base() == avant and registre_interdit == []


def test_une_identite_d_appareil_ouverte_pendant_le_tour_ferme_l_acteur_systeme(par_nom, cas_fictif, registre_interdit):
    """Le planificateur est un acteur `hors requête et hors identité d'appel` : poser une identité pendant son tour le
    rend inopérant (même garde que `verifier_planificateur`)."""
    with service_acteur_systeme.contexte_planificateur(), contexte.appele_par_appareil(ADMIN):
        reponse = executer_atomique(par_nom[PLANIFIE], {"aujourd_hui": JOUR})

    assert _code_refus(reponse) == "REJ-CONSTAT-PLANIFICATEUR-SEULEMENT" and registre_interdit == []


def test_un_departement_appelant_ou_le_transport_mcp_ne_valent_pas_le_planificateur(par_nom, cas_fictif,
                                                                                    registre_interdit):
    with contexte.appeler_en_tant_que("m02-revenue-crm"):
        assert _code_refus(executer_atomique(par_nom[PLANIFIE], {"aujourd_hui": JOUR})) == (
            "REJ-CONSTAT-PLANIFICATEUR-SEULEMENT")
    with contexte.transport_mcp():
        assert _code_refus(executer_atomique(par_nom[PLANIFIE], {"aujourd_hui": JOUR})) == (
            "REJ-CONSTAT-PLANIFICATEUR-SEULEMENT")
    assert registre_interdit == [] and _publies() == [] and _traces() == []


def test_l_acteur_systeme_du_reconciliateur_n_est_pas_celui_du_planificateur(par_nom, cas_fictif, registre_interdit):
    with service_acteur_systeme.contexte_reconciliateur():
        reponse = executer_atomique(par_nom[PLANIFIE], {"aujourd_hui": JOUR})

    assert _code_refus(reponse) == "REJ-CONSTAT-PLANIFICATEUR-SEULEMENT" and registre_interdit == []


def test_apres_le_tour_l_acteur_est_ferme_et_la_variante_est_de_nouveau_refusee(par_nom, cas_fictif):
    _corps(_par_le_planificateur(par_nom))

    assert _code_refus(executer_atomique(par_nom[PLANIFIE], {"aujourd_hui": LENDEMAIN})) == (
        "REJ-CONSTAT-PLANIFICATEUR-SEULEMENT")
    assert len(_publies()) == 1


# =============================================================================================== la publication
def test_le_planificateur_publie_le_constat_avec_sa_trace_et_une_reponse_sans_montant(par_nom, cas_fictif):
    avant = _instantane_base()

    corps = _corps(_par_le_planificateur(par_nom))

    assert set(corps) == {"deja_constate", "publie", "constat", "mention"} and corps["mention"] == MENTION
    assert (corps["deja_constate"], corps["publie"]) == (False, True)
    assert set(corps["constat"]) == {
        "evenement_id", "sequence", "date_reference", "version_donnees", "statut", "manque"}
    assert (corps["constat"]["sequence"], corps["constat"]["date_reference"], corps["constat"]["statut"]) == (
        1, JOUR, "CALCULE")
    assert corps["constat"]["manque"] == []
    texte = json.dumps(corps, ensure_ascii=False)
    for interdit in CONFIDENCES + ("cash_libre_cad", "montant", "lecture", "reserves"):
        assert interdit not in texte, interdit
    ((evenement_id, charge),) = _publies()
    assert evenement_id == charge["evenement_id"] == corps["constat"]["evenement_id"]
    assert erreurs_charge(TYPE, charge) == [] and charge["cash_libre_cad"] == "27861.98"
    assert _traces() == [constat_cash_libre.construire_trace(charge)]
    changees = {nom for nom, lignes in avant.items() if lignes != _instantane_base()[nom]}
    assert changees == {"registres_maillons", "evenements_sortants"}, "aucun mouvement, aucune facture, aucun paiement"


def test_la_variante_et_l_outil_a_la_demande_publient_la_meme_charge(par_nom, cas_fictif):
    """Un seul code d'écriture : la charge du bus est la même, à l'identifiant et au rang près."""
    _corps(_par_le_planificateur(par_nom))
    ((_, planifiee),) = _publies()
    ma_charge = {k: v for k, v in planifiee.items()}

    reference = _a_la_demande(par_nom, LENDEMAIN)

    assert reference["publie"] is True
    _, secondes = _publies()
    meme = {k: v for k, v in secondes[1].items() if k not in ("evenement_id", "sequence", "date_reference")}
    assert meme == {k: v for k, v in ma_charge.items() if k not in ("evenement_id", "sequence", "date_reference")}


def test_un_constat_par_jour_et_par_version_partage_entre_la_variante_et_l_outil_a_la_demande(par_nom, cas_fictif):
    premier = _corps(_par_le_planificateur(par_nom))["constat"]["evenement_id"]

    deuxieme = _corps(_par_le_planificateur(par_nom))
    assert (deuxieme["deja_constate"], deuxieme["publie"]) == (True, False)
    assert deuxieme["constat"]["evenement_id"] == premier
    sur_demande = _a_la_demande(par_nom)
    assert (sur_demande["deja_constate"], sur_demande["publie"]) == (True, False)
    assert sur_demande["constat"]["evenement_id"] == premier
    assert len(_publies()) == 1 and len(_traces()) == 1

    # l'inverse, un autre jour : l'admin d'abord, puis le planificateur
    autre = _a_la_demande(par_nom, LENDEMAIN)
    assert autre["publie"] is True and autre["constat"]["sequence"] == 2
    suite = _corps(_par_le_planificateur(par_nom, LENDEMAIN))
    assert (suite["deja_constate"], suite["publie"]) == (True, False)
    assert [c["sequence"] for _, c in _publies()] == [1, 2]


def test_un_autre_jour_avec_les_memes_donnees_publie_un_nouveau_constat(par_nom, cas_fictif):
    _corps(_par_le_planificateur(par_nom))

    suite = _corps(_par_le_planificateur(par_nom, LENDEMAIN))

    assert (suite["publie"], suite["constat"]["sequence"], suite["constat"]["date_reference"]) == (
        True, 2, LENDEMAIN)


def test_une_donnee_qui_change_le_meme_jour_publie_un_nouveau_constat(par_nom, cas_fictif):
    from decimal import Decimal

    from m5_financecore import registre

    _corps(_par_le_planificateur(par_nom))
    with stockage.transaction():
        reg = m5_outils._registre_mouvements(None)
        registre.enregistrer_mouvement({"montant": Decimal("-100.00"), "type_mouvement": "DECAISSEMENT",
                                        "horodatage": "2026-09-29T08:00:00-04:00", "classe_retention": "STANDARD",
                                        "source": "test-fictif"}, reg)

    suite = _corps(_par_le_planificateur(par_nom))

    assert (suite["publie"], suite["constat"]["sequence"]) == (True, 2)
    assert [c["cash_libre_cad"] for _, c in _publies()] == ["27861.98", "27761.98"]


def test_un_cash_libre_non_calculable_est_publie_tel_quel_jamais_un_zero(par_nom, declare):
    declare({})

    corps = _corps(_par_le_planificateur(par_nom))

    assert corps["publie"] is True and corps["constat"]["statut"] == "NON_CALCULABLE"
    assert corps["constat"]["manque"], "ce qui manque est dit, par composante et par code"
    ((_, charge),) = _publies()
    assert charge["cash_libre_cad"] is None and charge["statut"] == "NON_CALCULABLE" and charge["manque"]
    assert erreurs_charge(TYPE, charge) == []


# ========================================================================================== refus et abus
@pytest.mark.parametrize("jour", ["2026-9-29", "29/09/2026", "20260929", "2026-02-30", "aujourd'hui", ""])
def test_une_date_illisible_est_refusee_avant_toute_lecture(par_nom, cas_fictif, registre_interdit, jour):
    avant = _instantane_base()

    assert _code_refus(_par_le_planificateur(par_nom, jour)) == "REJ-CONSTAT-DATE-INVALIDE"

    assert _instantane_base() == avant and registre_interdit == []


def test_le_schema_refuse_un_montant_un_role_ou_un_droit_glisses_dans_les_arguments(par_nom, cas_fictif):
    with service_acteur_systeme.contexte_planificateur():
        for arguments in ({}, {"aujourd_hui": None}, {"aujourd_hui": JOUR, "autorise_couts": True},
                          {"aujourd_hui": JOUR, "role": "admin"}, {"aujourd_hui": JOUR, "cash_libre": "99999.00"},
                          {"aujourd_hui": 20260929}):
            reponse = executer_atomique(par_nom[PLANIFIE], arguments)
            assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", arguments
    assert _publies() == [] and _traces() == []


def test_hors_du_stockage_durable_la_variante_est_refusee_avant_toute_lecture(par_nom, cas_fictif, registre_interdit):
    m5_outils.reinitialiser_stockage_mouvements()
    avant = _instantane_base()

    assert _code_refus(_par_le_planificateur(par_nom)) == "REJ-CONSTAT-STOCKAGE-NON-DURABLE"

    assert _instantane_base() == avant and registre_interdit == []


def test_la_publication_qui_echoue_annule_aussi_la_trace(par_nom, cas_fictif, monkeypatch):
    avant = _instantane_base()
    vraie = constat_cash_libre.charge_evenement
    monkeypatch.setattr(constat_cash_libre, "charge_evenement",
                        lambda resultat, jour, sequence: {**vraie(resultat, jour, sequence), "devise": "USD"})

    with service_acteur_systeme.contexte_planificateur():
        reponse = executer_atomique(par_nom[PLANIFIE], {"aujourd_hui": JOUR})

    assert reponse["ok"] is False and "charge invalide" in reponse["details"]
    assert _traces() == [] and _publies() == [] and _instantane_base() == avant


def test_le_journal_et_les_erreurs_d_un_refus_ne_portent_aucun_montant(par_nom, cas_fictif):
    refus = [executer_atomique(par_nom[PLANIFIE], {"aujourd_hui": JOUR}), _par_le_planificateur(par_nom, "nimporte")]

    texte = json.dumps(refus, ensure_ascii=False)
    for interdit in CONFIDENCES:
        assert interdit not in texte, interdit


# ============================================================================== la garde anti-décaissement
_FICHIERS = sorted(p.stem for p in _PAQUET.glob("*.py"))


def _sur_les_vrais_fichiers(tmp_path, modifier):
    for nom in _FICHIERS:
        texte = (_PAQUET / f"{nom}.py").read_text(encoding="utf-8")
        (tmp_path / f"{nom}.py").write_text(modifier(nom, texte), encoding="utf-8")
    return conformite.verifier_aucun_decaissement(tmp_path)


def test_le_vrai_paquet_reste_conforme_et_la_variante_est_dans_la_portee_de_la_garde():
    assert conformite.verifier_aucun_decaissement(_PAQUET) == (True, "")
    assert "constater_cash_libre_planifie" in conformite._SURVEILLE_EN_LECTURE_SEULE["outils"]
    source = (_PAQUET / "outils.py").read_text(encoding="utf-8")
    import re

    assert re.search(r"^def constater_cash_libre_planifie\(", source, re.MULTILINE)


@pytest.mark.parametrize("glisse", [
    "geste = enregistrer_mouvement",
    "geste = enregistrer_paiement_facture",
    "geste = []\n    geste.append(1)",
], ids=["ecriture_mouvement", "paiement", "append"])
def test_un_decaissement_ou_une_ecriture_glisse_dans_la_variante_est_attrape(tmp_path, glisse):
    ancre = ('    constat = _constater_cash_libre(_registre_mouvements(None), jour)\n    return {\n'
             '        "accepte": True,')

    def modifier(nom, texte):
        if nom != "outils":
            return texte
        assert texte.count(ancre) == 1
        return texte.replace(ancre, f"    {glisse}\n" + ancre, 1)

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "constater_cash_libre_planifie()" in detail, detail
