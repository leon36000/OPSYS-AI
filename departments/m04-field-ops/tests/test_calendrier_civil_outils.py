"""CRM-01 : vraie chaîne SQLite, outils, identité active. Données fictives uniquement."""
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops.outils import outils

from opsys import identite, stockage

_spec = importlib.util.spec_from_file_location(
    "fixture_calendrier_sql", Path(__file__).with_name("test_cedule_tournees_outils.py"))
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)
instance, par_nom, interventions = aide.instance, aide.par_nom, aide.interventions
FICTIF = True


def _dates(par_nom, plan, revision=0, acteur=aide.ADMIN):
    return aide._appeler(par_nom, "m4_confirmer_dates_cedule", {
        "plan_id": plan, "calendrier": {"0": "2030-06-03"}, "revision_attendue": revision}, acteur)


def test_appliquer_dater_rouvrir_sql_et_refuser_revision_perimee(par_nom, interventions):
    plan = aide._resultat(aide._proposer(par_nom, interventions))["plan_id"]
    aide._resultat(aide._appliquer(par_nom, plan))
    confirmation = aide._resultat(_dates(par_nom, plan))
    assert confirmation["revision"] == 1
    stockage.liberer()
    outils_rouverts = {o.nom: o for o in outils()}
    semaine = aide._resultat(aide._appeler(outils_rouverts, "m4_lire_cedule_semaine",
                                         {"debut_semaine": "2030-06-03"}, aide.ADMIN))
    assert len(semaine["interventions"]) == len(interventions) == 6
    assert all(ligne["source_ligne_id"] == confirmation["ligne_id"] and ligne["confirme_le"] == aide.RECU_LE.isoformat()
               for ligne in semaine["interventions"])
    avant = aide._maillons()
    assert aide._code_refus(_dates(outils_rouverts, plan)) == "REJ-CONTRAT-INVALIDE"
    assert aide._maillons() == avant
    assert aide._resultat(_dates(outils_rouverts, plan, 1))["revision"] == 2


@pytest.mark.parametrize("acteur", [None, aide.MARC, aide.VENDEUR, aide.FANTOME])
def test_non_admin_ou_inconnu_refuse_sans_ecriture(par_nom, acteur):
    avant = aide._maillons()
    assert aide._code_refus(_dates(par_nom, "inexistant", acteur=acteur)) in {
        "REJ-HUMAIN-REQUIS", "REJ-IDENTITE-APPAREIL-INVALIDE"}
    assert aide._code_refus(aide._appeler(par_nom, "m4_lire_cedule_semaine",
                                        {"debut_semaine": "2030-06-03"}, acteur)) in {
        "REJ-HUMAIN-REQUIS", "REJ-IDENTITE-APPAREIL-INVALIDE"}
    assert aide._maillons() == avant


def test_role_revoque_refuse(par_nom, interventions):
    plan = aide._resultat(aide._proposer(par_nom, interventions))["plan_id"]
    aide._resultat(aide._appliquer(par_nom, plan))
    aide._resultat(_dates(par_nom, plan))
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, aide.ADMIN.personne, "admin")
    avant = aide._maillons()
    assert aide._code_refus(_dates(par_nom, plan, 1)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert aide._maillons() == avant


def test_recu_idempotent_revalide_identite_sql(par_nom, interventions):
    from opsys import contexte, idempotence
    from opsys.capacites import Capacites
    from opsys.departements import charger_departements

    plan = aide._resultat(aide._proposer(par_nom, interventions))["plan_id"]
    aide._resultat(aide._appliquer(par_nom, plan))
    caps = Capacites(charger_departements(), stockage.transaction, filtre={"m04-field-ops"},
                     appelant="m04-field-ops", memoire=False)
    args = {"plan_id": plan, "calendrier": {"0": "2030-06-03"}, "revision_attendue": 0}
    meta = idempotence.Meta("dates-rejeu-fictif", "appareil-fictif", aide.HORODATAGE)
    acteur = contexte.IdentiteAppelante(aide.ADMIN.personne, "admin", source="appareil")
    with contexte.appele_par_appareil(acteur):
        premier = caps.appeler("m4_confirmer_dates_cedule", args, meta)
        assert premier.get("resultat", {}).get("accepte") is True, premier
        assert caps.appeler("m4_confirmer_dates_cedule", args, meta).get("rejoue") is True
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, aide.ADMIN.personne, "admin")
    with contexte.appele_par_appareil(acteur):
        refuse = caps.appeler("m4_confirmer_dates_cedule", args, meta)
        assert refuse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE", refuse
    assert len([m for m in aide._maillons() if m["type_entree"] == "cedule_datee"]) == 1


def test_confirmation_refuse_registre_injecte_meme_sous_transaction(par_nom):
    from m4_field_ops.registre import Registre

    injecte = Registre()
    par_nom = {o.nom: o for o in outils(injecte)}
    assert aide._code_refus(_dates(par_nom, "inexistant")) == "REJ-FRONTIERE-VIOLEE"
    assert injecte.lire() == []


def test_deux_confirmations_concurrentes_ne_perdent_pas_la_revision(par_nom, interventions):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    plan = aide._resultat(aide._proposer(par_nom, interventions))["plan_id"]
    aide._resultat(aide._appliquer(par_nom, plan))
    barriere = Barrier(2)

    def tentative():
        barriere.wait(timeout=5)
        return _dates(par_nom, plan)

    with ThreadPoolExecutor(max_workers=2) as pool:
        appels = [pool.submit(tentative) for _ in range(2)]
        reponses = [a.result(timeout=10) for a in appels]
    assert sum(r["resultat"]["accepte"] for r in reponses) == 1, reponses
    refuse = next(r for r in reponses if not r["resultat"]["accepte"])
    assert "revision périmée" in refuse["resultat"]["verdict"]["detail"]
    assert len([m for m in aide._maillons() if m["type_entree"] == "cedule_datee"]) == 1
