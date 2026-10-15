from __future__ import annotations

import pytest
from m7_marketing import outils
from m7_marketing.brand import profil_client
from sqlalchemy import update

from opsys import contexte, identite, stockage
from opsys.outils import executer_atomique
from opsys.stockage.schema import PERSONNES

HORODATAGE = "2026-09-30T12:00:00-04:00"
_NOMS = {outil.nom: outil for outil in outils.outils()}
_PROFIL = {
    "name": "Synergy Fictive", "tagline": "Travaux extérieurs", "tone": "professionnel",
    "colors": ["#123456"], "langue": "fr",
}


def _appel(nom, personne="employe", role="employee", **args):
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(personne, role)):
        return executer_atomique(_NOMS[nom], args)


def _metier(reponse):
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    return resultat.get("resultat", resultat)


def _avis(**surcouches):
    return {
        "plateforme": "google_business_profile", "avis_source_id": "review-8841",
        "date_avis": "2026-09-28", "note": 5,
        "texte": "Excellent travail, équipe ponctuelle et soignée.",
        "source_url": "https://business.google.com/reviews/review-8841",
        **surcouches,
    }


def _lire(registre):
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", registre))


def _base(tmp_path, monkeypatch, request):
    request.addfinalizer(stockage.liberer)
    url = f"sqlite:///{tmp_path / 'm7-inbox.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    stockage.migrer(url)
    monkeypatch.setattr(profil_client, "charger_profil_client", lambda: (dict(_PROFIL), None))
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan", "mot-de-passe-proprietaire", ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "employe", "Employé", "mot-de-passe-employe", ["employee"])
        identite.creer_personne(cnx, "gestionnaire", "Gestionnaire", "mot-de-passe-admin", ["admin"])
    return url


def test_import_rejeu_et_export_manuel_apres_decision_vivante_du_proprietaire(tmp_path, monkeypatch, request):
    _base(tmp_path, monkeypatch, request)
    assert outils.calculer_metriques_reputation()["m7_rep_total_avis"] == 0  # aucun chargement implicite de fixture
    donnees = _avis()
    importation = _metier(_appel("m7_importer_avis_manuel", **donnees))
    assert importation["deja_importe"] is False and importation["statut"] == "PROPOSE"
    assert importation["reponse_texte"] and importation["categorie"] == "eloge"
    assert len(_lire("reputation_avis")) == 1

    rejeu = _metier(_appel("m7_importer_avis_manuel", **donnees))
    assert rejeu["deja_importe"] is True and len(_lire("reputation_avis")) == 1
    assert outils.calculer_metriques_reputation()["m7_rep_total_avis"] == 1
    liste = _metier(_appel("m7_lister_inbox_reputation", personne="employe", categorie="eloge"))
    assert len(liste["avis"]) == 1 and liste["avis"][0]["texte"] == donnees["texte"]

    employee_refuse = _metier(_appel(
        "m7_decider_reponse_avis", personne="employe", role="employee", avis_id=importation["avis_id"],
        decision="approuver", horodatage=HORODATAGE,
    ))
    assert employee_refuse["accepte"] is False and employee_refuse["verdict"]["code"] == "REJ-HUMAIN-ROLE-INSUFFISANT"
    assert _lire("reputation_decisions") == []
    employee_export = _metier(_appel(
        "m7_exporter_reponse_avis_manuel", personne="employe", role="employee", avis_id=importation["avis_id"],
    ))
    assert employee_export["accepte"] is False and employee_export["verdict"]["code"] == "REJ-HUMAIN-ROLE-INSUFFISANT"

    admin_autre_refuse = _metier(_appel(
        "m7_decider_reponse_avis", personne="gestionnaire", role="admin", avis_id=importation["avis_id"],
        decision="approuver", horodatage=HORODATAGE,
    ))
    assert (
        admin_autre_refuse["accepte"] is False
        and admin_autre_refuse["verdict"]["code"] == "REJ-HUMAIN-ROLE-INSUFFISANT"
    )
    assert _lire("reputation_decisions") == []

    approuve = _metier(_appel(
        "m7_decider_reponse_avis", personne="nathan", role="admin", avis_id=importation["avis_id"],
        decision="approuver", horodatage=HORODATAGE,
    ))
    assert approuve["avis_id"] == importation["avis_id"] and approuve["par"] == "nathan"
    assert _lire("reputation_decisions")[0]["empreinte_reponse"] == _lire("reputation_avis")[0]["reponse_empreinte"]

    paquet = _metier(_appel(
        "m7_exporter_reponse_avis_manuel", personne="nathan", role="admin", avis_id=importation["avis_id"],
    ))
    assert paquet["mode"] == "copie_manuelle"
    assert "aucune publication" in paquet["instruction"]
    rejeu_export = _metier(_appel(
        "m7_exporter_reponse_avis_manuel", personne="nathan", role="admin", avis_id=importation["avis_id"],
    ))
    assert rejeu_export["deja_exporte"] is True
    assert len(_lire("reputation_exports")) == 1


def test_export_revalide_identite_owner_active_au_point_deffet(tmp_path, monkeypatch, request):
    _base(tmp_path, monkeypatch, request)
    importation = _metier(_appel("m7_importer_avis_manuel", **_avis()))
    _metier(_appel(
        "m7_decider_reponse_avis", personne="nathan", role="admin", avis_id=importation["avis_id"],
        decision="approuver", horodatage=HORODATAGE,
    ))
    with stockage.transaction() as cnx:
        cnx.execute(update(PERSONNES).where(PERSONNES.c.identifiant == "nathan").values(actif=False))
    reponse = _metier(_appel(
        "m7_exporter_reponse_avis_manuel", personne="nathan", role="admin", avis_id=importation["avis_id"],
    ))
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-HUMAIN-IDENTITE-INVALIDE"
    assert _lire("reputation_exports") == []


def test_rejeu_avec_contenu_different_est_conflit_sans_mutation(tmp_path, monkeypatch, request):
    _base(tmp_path, monkeypatch, request)
    premier = _metier(_appel("m7_importer_avis_manuel", **_avis()))
    avant = _lire("reputation_avis")
    conflit = _metier(_appel("m7_importer_avis_manuel", **_avis(texte="Avis modifié", note=1)))
    assert conflit["accepte"] is False and conflit["verdict"]["code"] == "CONFLIT-AVIS-SOURCE"
    assert _lire("reputation_avis") == avant and len(avant) == 1
    assert premier["avis_id"] == avant[0]["avis_id"]


def test_plainte_revue_en_privee_et_redaction_employee_aucun_export(tmp_path, monkeypatch, request):
    _base(tmp_path, monkeypatch, request)
    plainte = _avis(avis_source_id="complaint-77", note=1, texte="Plainte : demande de remboursement urgente.")
    importation = _metier(_appel("m7_importer_avis_manuel", **plainte))
    assert importation["visibilite"] == "privee" and importation["reponse_texte"] is None
    vue_employe = _metier(_appel("m7_lister_inbox_reputation", personne="employe"))["avis"]
    assert vue_employe == []  # la plainte n'apparaît même pas dans la liste employé
    vue_admin = _metier(_appel("m7_lister_inbox_reputation", personne="nathan", role="admin"))["avis"][0]
    assert vue_admin["texte"] == plainte["texte"]

    decidee = _metier(_appel(
        "m7_decider_reponse_avis", personne="nathan", role="admin", avis_id=importation["avis_id"],
        decision="approuver", horodatage=HORODATAGE,
    ))
    assert decidee["statut"] == "APPROUVE_PRIVE"
    refuse = _metier(_appel(
        "m7_exporter_reponse_avis_manuel", personne="nathan", role="admin", avis_id=importation["avis_id"],
    ))
    assert refuse["accepte"] is False and refuse["verdict"]["code"] == "REJ-AVIS-PRIVE"
    assert _lire("reputation_exports") == []


def test_import_exige_identite_active_et_source_complete(tmp_path, monkeypatch, request):
    _base(tmp_path, monkeypatch, request)
    no_source = dict(_avis(source_url=""))
    reponse = _metier(_appel("m7_importer_avis_manuel", **no_source))
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-AVIS-INVALIDE"
    assert _lire("reputation_avis") == []

    with contexte.appele_par_appareil(contexte.IdentiteAppelante("absent", "employee")):
        absent = executer_atomique(_NOMS["m7_importer_avis_manuel"], _avis())
    assert absent["ok"] is True and absent["resultat"]["accepte"] is False
    assert absent["resultat"]["verdict"]["code"] == "REJ-IDENTITE-REQUIS"
    assert _lire("reputation_avis") == []


@pytest.mark.parametrize("source_b", ["review-8841", "autre-avis-fictif"])
def test_import_interpose_refuse_a_et_annule_transaction_avant_reprise(
    tmp_path, monkeypatch, request, source_b,
):
    """Fictif : deux vrais outils dans la même transaction, sans appareil installé."""
    from opsys.stockage.maillons import EcritureConcurrente, MaillonsDurables

    _base(tmp_path, monkeypatch, request)
    avant = _lire("reputation_avis")
    original = MaillonsDurables.append
    observations = []
    arme = True

    def interposer(self, maillon, *, rang_attendu=None):
        nonlocal arme
        if arme and (self.departement, self.registre) == ("m07-marketing", "reputation_avis"):
            arme = False
            cnx = stockage.connexion_courante()
            b = _metier(_appel("m7_importer_avis_manuel", **_avis(avis_source_id=source_b)))
            assert b["deja_importe"] is False
            assert stockage.connexion_courante() is cnx
            assert len(_lire("reputation_avis")) == 1
            observations.append(b["avis_id"])
        return original(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", interposer)
    with pytest.raises(EcritureConcurrente, match="rang attendu"):
        _appel("m7_importer_avis_manuel", **_avis())
    stockage.liberer()
    assert len(observations) == 1
    assert _lire("reputation_avis") == avant == []
    assert outils.calculer_metriques_reputation()["m7_rep_total_avis"] == 0

    monkeypatch.setattr(MaillonsDurables, "append", original)
    b = _metier(_appel("m7_importer_avis_manuel", **_avis(avis_source_id=source_b)))
    assert b["deja_importe"] is False
    a = _metier(_appel("m7_importer_avis_manuel", **_avis()))
    assert a["deja_importe"] is (source_b == "review-8841")
    apres = _lire("reputation_avis")
    assert len(apres) == (1 if source_b == "review-8841" else 2)
    assert len({avis["avis_id"] for avis in apres}) == len(apres)
    assert outils.calculer_metriques_reputation()["m7_rep_total_avis"] == len(apres)
    assert _metier(_appel("m7_importer_avis_manuel", **_avis()))["deja_importe"] is True
    assert _lire("reputation_avis") == apres


def test_import_panne_apres_sql_est_annule_et_rejouable(tmp_path, monkeypatch, request):
    """Fictif : aucun succès ne survit à la panne d'une transaction outil."""
    from opsys.stockage.maillons import MaillonsDurables

    _base(tmp_path, monkeypatch, request)
    original = MaillonsDurables.append
    observations = []

    def panne(self, maillon, *, rang_attendu=None):
        original(self, maillon, rang_attendu=rang_attendu)
        if (self.departement, self.registre) == ("m07-marketing", "reputation_avis"):
            observations.append(len(_lire("reputation_avis")))
            raise RuntimeError("panne fictive après SQL")

    monkeypatch.setattr(MaillonsDurables, "append", panne)
    with pytest.raises(RuntimeError, match="panne fictive après SQL"):
        _appel("m7_importer_avis_manuel", **_avis())
    assert observations == [1]
    stockage.liberer()
    assert _lire("reputation_avis") == []
    assert outils.calculer_metriques_reputation()["m7_rep_total_avis"] == 0
    monkeypatch.setattr(MaillonsDurables, "append", original)
    assert _metier(_appel("m7_importer_avis_manuel", **_avis()))["deja_importe"] is False
    apres = _lire("reputation_avis")
    assert len(apres) == 1
    assert _metier(_appel("m7_importer_avis_manuel", **_avis()))["deja_importe"] is True
    assert _lire("reputation_avis") == apres
