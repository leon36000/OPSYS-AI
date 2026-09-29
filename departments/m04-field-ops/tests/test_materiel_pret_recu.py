"""PLAN T4.14-b : M4 consomme `m6.materiel_pret` par le VRAI bus (ADR-0009 §3 ; DEFINITION-PRODUIT §7 M6 « fournit
à M4 : matériel prêt ou à commander », M4.6) et le volet « matériel » de `m4_verifier_preparation` le suit.

Deux niveaux, base SQLite migrée, vrais outils (`executer_atomique`), vrai répartiteur (`evenements.repartir`) :

  1. M4 SEUL reçoit des charges `m6.materiel_pret` fictives (valides au schéma du catalogue : `publier` refuse le
     reste) : la plus grande révision par devis, quel que soit l'ordre ; rejeu ; charge avant le devis ; aucun import
     de M6 ;
  2. M4 ET le VRAI M6 : devis accepté -> M6 réserve (`a_commander`, révision 1) -> réception partielle (`partiel`,
     révision 2) -> réception qui complète (`pret`, révision 3) -> libération (`a_commander`, réservation inactive,
     révision 4) : le volet « matériel » de M4 suit chaque révision.

M4 n'importe rien de M6 : M6 n'est atteint que par son manifeste et ses outils (`charger_departements`). Données
fictives (`fictif: true` au sens d'AGENTS.md : identifiants, quantités, matériaux et personnes de test).
"""

from __future__ import annotations

import ast
import datetime as dt
import json
from pathlib import Path

import m4_field_ops
import pytest
from m4_field_ops import materiel, registre
from sqlalchemy import select

from opsys import contexte, evenements, identite, stockage
from opsys.departements import charger_departements
from opsys.evenements.schemas import erreurs_charge
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS

FICTIF = True
M4, M6 = "m04-field-ops", "m06-material-control"
ACCEPTE_LE = "2026-09-30T10:00:00-04:00"
RECU_LE = "2026-09-15T09:15:00-04:00"
DEBUT = dt.datetime(2026, 9, 30, 11, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
GOUTTIERE, VIS = "gouttiere-5po-fictif", "vis-inox-fictif"
CATALOGUE = {"version": "v1-fictif", "unite_monetaire": "CAD", "postes": {
    GOUTTIERE: {"cout_unitaire": 8.5, "libelle": "Gouttière 5 po"},
    VIS: {"cout_unitaire": 0.35, "libelle": "Vis inox"}}}


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
    yield tmp_path
    stockage.liberer()


def _departements(*ids):
    reels = charger_departements()
    return {i: reels[i] for i in ids}


def _repartir_jusqu_au_repos(*ids, depuis=DEBUT, max_tours=8):
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(max_tours):
        instant = (depuis + dt.timedelta(seconds=100 * tour)).isoformat()
        resume = evenements.repartir(_departements(*ids), maintenant=instant)
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            assert total["echecs"] == 0 and total["quarantaines"] == 0, total
            return total
    raise AssertionError(f"le bus n'a pas atteint le repos : {total}")


def _outils(dep):
    return {o.nom: o for o in charger_departements()[dep].charger_outils()}


def _appeler(dep, nom, arguments, appelant=None):
    outil = _outils(dep)[nom]
    if appelant is None:
        return executer_atomique(outil, arguments)
    with contexte.appele_par_appareil(appelant):
        return executer_atomique(outil, arguments)


def _ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _maillons(dep=M4, registre="principal") -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons(dep, registre))


def _charges_recues() -> list[dict]:
    return [m for m in _maillons() if m["type_entree"] == "materiel_pret_recu"]


def _recu(evenement_id: str) -> dict:
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == evenement_id) & (EVENEMENTS_RECUS.c.consommateur == M4)
        )).mappings().first()
    assert ligne is not None, f"aucun reçu de M4 pour {evenement_id}"
    return dict(ligne)


def _resultat(evenement_id: str) -> dict:
    return codec.decoder(_recu(evenement_id)["resultat"])


# ------------------------------------------------------------------------------------------ charges fictives
def _ligne(materiau, besoin, reservee, unite="pi"):
    return {"materiau_id": materiau, "unite": unite, "quantite_besoin": str(besoin), "quantite_reservee": str(reservee),
            "quantite_manquante": str(besoin - reservee)}


def _charge(devis, revision, statut, *, active=True, chantier=None, reservees=(0, 0)):
    lignes = [_ligne(GOUTTIERE, 100, reservees[0]), _ligne(VIS, 20, reservees[1], "boite")]
    return {
        "evenement_id": f"m6-materiel-pret-{devis}-{revision}", "devis_id": devis, "chantier_id": chantier,
        "revision": revision, "statut": statut, "reservation_active": active, "declencheur": "devis_accepte",
        "horodatage": f"2026-09-30T10:{revision:02d}:00-04:00", "lignes": lignes,
        "lignes_manquantes": [ligne for ligne in lignes if ligne["quantite_manquante"] != "0"],
    }


def _publier(charge, evenement_id=None):
    identifiant = evenement_id or charge["evenement_id"]
    evenements.publier("m6.materiel_pret", M6, charge, evenement_id=identifiant)
    return identifiant


# ------------------------------------------------------------------------------------------ niveau 1 : M4 seul
class TestManifeste:
    def test_m4_consomme_le_type_et_la_fonction_est_branchee_au_vrai_manifeste(self):
        dep = charger_departements()[M4]
        assert "m6.materiel_pret" in dep.evenements_consomme
        assert dep.charger_consommateurs()["m6.materiel_pret"].__name__ == "_recevoir_materiel_pret"
        assert set(dep.evenements_consomme) == set(dep.charger_consommateurs())
        assert evenements.verifier_coherence(charger_departements()) == []

    def test_aucun_module_de_m4_n_importe_m6(self):
        racine = Path(m4_field_ops.__file__).parent
        for chemin in sorted(racine.glob("*.py")):
            for noeud in ast.walk(ast.parse(chemin.read_text(encoding="utf-8"))):
                modules = []
                if isinstance(noeud, ast.Import):
                    modules = [a.name for a in noeud.names]
                elif isinstance(noeud, ast.ImportFrom):
                    modules = [noeud.module or ""]
                for module in modules:
                    assert not module.startswith(("m6_", "m06", "m6.")), (chemin.name, module)


class TestRetenue:
    def test_une_charge_recue_est_rangee_avec_l_heure_de_m6_sans_chantier_ni_detail_des_lignes(self, instance):
        evenement_id = _publier(_charge("DEVIS-A", 1, "a_commander", chantier="CHANTIER-QUE-M4-NE-LIT-PAS"))
        assert _repartir_jusqu_au_repos(M4)["traites"] == 1

        (maillon,) = _charges_recues()
        assert (maillon["devis_id"], maillon["revision"], maillon["statut"]) == ("DEVIS-A", 1, "a_commander")
        assert maillon["horodatage"] == "2026-09-30T10:01:00-04:00", "l'heure du fait de M6, jamais celle de M4"
        assert maillon["evenement_id"] == evenement_id and maillon["reservation_active"] is True
        assert [m["materiau_id"] for m in maillon["lignes_manquantes"]] == [GOUTTIERE, VIS]
        contenu = json.dumps(_maillons(), ensure_ascii=False)
        assert "CHANTIER-QUE-M4-NE-LIT-PAS" not in contenu and "chantier_id" not in contenu
        assert _resultat(evenement_id) == {
            "traite": True, "devis_id": "DEVIS-A", "revision": 1, "ignoree": False, "revision_retenue": 1,
            "statut": "a_commander"}

    def test_les_revisions_dans_l_ordre_donnent_une_charge_par_revision_la_derniere_fait_foi(self, instance):
        for revision, statut, reservees in ((1, "a_commander", (0, 0)), (2, "partiel", (100, 0)),
                                            (3, "pret", (100, 20))):
            _publier(_charge("DEVIS-B", revision, statut, reservees=reservees))
        assert _repartir_jusqu_au_repos(M4)["traites"] == 3
        assert [m["revision"] for m in _charges_recues()] == [1, 2, 3]
        with stockage.transaction():
            retenue = materiel.charge_retenue(registre.Registre(stockage.maillons(M4, "principal")), "DEVIS-B")
        assert retenue["revision"] == 3 and retenue["statut"] == "pret"

    def test_ordre_inverse_la_plus_ancienne_arrivee_apres_la_plus_recente_n_ecrit_rien(self, instance):
        recente = _publier(_charge("DEVIS-C", 3, "pret", reservees=(100, 20)))
        assert _repartir_jusqu_au_repos(M4)["traites"] == 1
        avant = json.dumps(_maillons(), sort_keys=True)

        ancienne = _publier(_charge("DEVIS-C", 1, "a_commander"))
        milieu = _publier(_charge("DEVIS-C", 2, "partiel", reservees=(100, 0)))
        assert _repartir_jusqu_au_repos(M4)["traites"] == 2

        assert json.dumps(_maillons(), sort_keys=True) == avant, "une révision plus ancienne n'écrit rien"
        for identifiant, revision in ((ancienne, 1), (milieu, 2)):
            assert _resultat(identifiant) == {
                "traite": True, "devis_id": "DEVIS-C", "revision": revision, "ignoree": True, "revision_retenue": 3}
        assert _resultat(recente)["ignoree"] is False
        assert [m["revision"] for m in _charges_recues()] == [3]

    def test_la_meme_revision_sous_un_autre_evenement_est_ignoree(self, instance):
        _publier(_charge("DEVIS-D", 2, "partiel", reservees=(100, 0)))
        _repartir_jusqu_au_repos(M4)
        avant = json.dumps(_maillons(), sort_keys=True)

        rejeu = _publier(
            _charge("DEVIS-D", 2, "partiel", reservees=(100, 0)), evenement_id="rejeu-par-un-autre-producteur")
        assert _repartir_jusqu_au_repos(M4)["traites"] == 1
        assert _resultat(rejeu)["ignoree"] is True and json.dumps(_maillons(), sort_keys=True) == avant

    def test_un_evenement_rejoue_par_le_bus_est_un_no_op(self, instance):
        identifiant = _publier(_charge("DEVIS-E", 1, "a_commander"))
        _repartir_jusqu_au_repos(M4)
        avant = json.dumps(_maillons(), sort_keys=True)
        assert _publier(_charge("DEVIS-E", 1, "a_commander"), evenement_id=identifiant) == identifiant
        assert evenements.repartir(_departements(M4), maintenant="2026-09-30T12:00:00-04:00")["livres"] == 0
        assert json.dumps(_maillons(), sort_keys=True) == avant

    def test_chaque_devis_a_sa_propre_retenue(self, instance):
        _publier(_charge("DEVIS-F1", 2, "partiel", reservees=(100, 0)))
        _publier(_charge("DEVIS-F2", 1, "a_commander"))
        _publier(_charge("DEVIS-F1", 1, "a_commander"))
        assert _repartir_jusqu_au_repos(M4)["traites"] == 3
        assert sorted((m["devis_id"], m["revision"]) for m in _charges_recues()) == [("DEVIS-F1", 2), ("DEVIS-F2", 1)]

    def test_la_charge_peut_arriver_avant_le_devis_l_intervention_la_lira_a_sa_naissance(self, instance):
        _publier(_charge("DEVIS-G", 1, "a_commander"))
        assert _repartir_jusqu_au_repos(M4)["traites"] == 1
        assert [m for m in _maillons() if m["type_entree"] == "intervention_inscrite"] == []
        assert [m["devis_id"] for m in _charges_recues()] == ["DEVIS-G"]

    def test_une_charge_dont_la_revision_n_est_pas_un_entier_ecrit_rien_et_leve(self, instance):
        mauvaise = _charge("DEVIS-H", 1, "a_commander")
        mauvaise["revision"] = "1"
        assert erreurs_charge("m6.materiel_pret", mauvaise), "le catalogue la refuse déjà"
        consommateur = charger_departements()[M4].charger_consommateurs()["m6.materiel_pret"]
        with pytest.raises(ValueError, match="revision"), stockage.transaction():
            consommateur(mauvaise)
        assert _charges_recues() == []

    def test_le_catalogue_refuse_une_charge_incomplete_avant_meme_le_bus(self, instance):
        incomplete = _charge("DEVIS-I", 1, "a_commander")
        del incomplete["lignes_manquantes"]
        with pytest.raises(evenements.ChargeInvalide):
            _publier(incomplete)


# ------------------------------------------------------------------------------------------ niveau 2 : M4 et M6
def _lead(lead_id):
    return {
        "schema_version": 2, "lead_id": lead_id, "conversation_id": f"sms-secrete-{lead_id}",
        "contact": {"nom": "Client Fictif", "telephone": "+15145550142", "courriel": f"{lead_id}@exemple-fictif.test"},
        "service": "gouttieres", "ville": "Repentigny", "urgence_declaree": False, "canal": "texte", "source": "sms",
    }


def _devis_accepte(devis_id, lead_id, chantier_id=None):
    charge = {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": chantier_id,
        "lignes": [{"reference_ligne": f"{devis_id}-L{i}", "description": "ligne fictive", "quantite": quantite,
                    "unite": unite, "prix_unitaire": "10.00", "prix_ligne": "10.00",
                    "reference_besoin_materiau": materiau}
                   for i, (materiau, quantite, unite) in enumerate([(GOUTTIERE, "100", "pi"), (VIS, "20", "boite")])],
        "cout_total": "100.00", "prix_total": "135.00", "taux_marge": "0.35", "horodatage_acceptation": ACCEPTE_LE}
    evenements.publier("m3.devis_accepte", "m03-estimation", charge, evenement_id=f"m3-devis-accepte-{devis_id}")


def _reception(po_id, gouttieres, vis, horodatage):
    lignes_demandees = [{"materiau_id": GOUTTIERE, "quantite_demandee": 100.0},
                        {"materiau_id": VIS, "quantite_demandee": 20.0}]
    return _ok(_appeler(M6, "m6_receptionner_commande", {
        "bon_demande": {"po_id": po_id, "chantier_id": "CHANTIER-DEPOT", "horodatage": "2026-10-01T08:00:00-04:00",
                        "lignes_demandees": lignes_demandees},
        "reception_po": {"po_id": po_id, "chantier_id": "CHANTIER-DEPOT", "horodatage": horodatage,
                         "lignes_recues": [{"materiau_id": GOUTTIERE, "quantite_recue": gouttieres},
                                           {"materiau_id": VIS, "quantite_recue": vis}]},
        "catalogue_materiaux": CATALOGUE}))


def _volet_materiel(iid):
    reponse = _appeler(M4, "m4_verifier_preparation", {"intervention_id": iid}, ADMIN)
    verdict = _ok(reponse)["resultat"]
    return verdict["volets"]["materiel"], verdict


class TestAvecLeVraiM6:
    def test_devis_accepte_a_commander_partiel_pret_libere_et_le_volet_suit(self, instance):
        evenements.publier("m1.lead_qualifie", "m01-front-office",
                           {"lead": _lead("LEAD-VRAI"), "horodatage": RECU_LE, "signal_id": "sms:LEAD-VRAI"},
                           evenement_id="m1-lead-qualifie-LEAD-VRAI")
        _devis_accepte("DEVIS-VRAI", "LEAD-VRAI")

        # 1. devis accepté : M4 fait naître l'intervention, M6 réserve (stock nul : a_commander, révision 1)
        assert _repartir_jusqu_au_repos(M4, M6)["traites"] >= 2
        (inscription,) = [m for m in _maillons() if m["type_entree"] == "intervention_inscrite"]
        iid = inscription["intervention_id"]
        (premiere,) = _charges_recues()
        assert (premiere["revision"], premiere["statut"], premiere["reservation_active"]) == (1, "a_commander", True)
        volet, verdict = _volet_materiel(iid)
        assert (volet["statut"], volet["detail"]) == ("manque", "a_commander")
        assert f"{GOUTTIERE} : 100 pi manquantes sur 100" in volet["manque"]
        assert f"{VIS} : 20 boite manquantes sur 20" in volet["manque"]
        assert verdict["pret"] is False and "materiel" in [f["volet"] for f in verdict["a_fournir"]]
        assert _maillons(M6, "bons_commande") == [], "aucun bon de commande n'est créé seul"

        # 2. réception partielle : les gouttières arrivent, pas les vis -> partiel (révision 2)
        assert _reception("PO-VRAI-1", 100.0, 0.0, "2026-10-05T09:00:00-04:00")["accepte"] is True
        _repartir_jusqu_au_repos(M4, M6)
        assert [m["revision"] for m in _charges_recues()] == [1, 2]
        volet, _ = _volet_materiel(iid)
        assert (volet["statut"], volet["detail"]) == ("manque", "partiel")
        assert f"{VIS} : 20 boite manquantes sur 20" in volet["manque"] and GOUTTIERE not in volet["manque"]

        # 3. la réception qui complète -> pret (révision 3) : le volet est ok
        assert _reception("PO-VRAI-2", 0.0, 20.0, "2026-10-06T09:00:00-04:00")["accepte"] is True
        _repartir_jusqu_au_repos(M4, M6)
        assert [(m["revision"], m["statut"]) for m in _charges_recues()] == [(1, "a_commander"), (2, "partiel"),
                                                                            (3, "pret")]
        volet, verdict = _volet_materiel(iid)
        assert volet == {"statut": "ok", "manque": None, "detail": "matériel prêt et réservé (M6, révision 3)"}
        assert "materiel" not in [f["volet"] for f in verdict["a_fournir"]]
        assert verdict["pret"] is False, "la météo n'a pas encore de source : jamais prêt"

        # 4. l'admin libère la réservation : a_commander, réservation inactive (révision 4) : le volet manque de nouveau
        _ok(_appeler(M6, "m6_liberer_reservation", {
            "devis_id": "DEVIS-VRAI", "motif": "le client a annulé le chantier (fictif)",
            "horodatage": "2026-10-07T09:00:00-04:00"}, ADMIN))
        _repartir_jusqu_au_repos(M4, M6)
        derniere = _charges_recues()[-1]
        assert (derniere["revision"], derniere["statut"], derniere["reservation_active"]) == (4, "a_commander", False)
        volet, _ = _volet_materiel(iid)
        assert (volet["statut"], volet["detail"]) == ("manque", "a_commander")
        assert "révision 4" in volet["manque"]

    def test_la_lecture_du_volet_n_ecrit_rien(self, instance):
        evenements.publier("m1.lead_qualifie", "m01-front-office",
                           {"lead": _lead("LEAD-LECT"), "horodatage": RECU_LE, "signal_id": "sms:LEAD-LECT"},
                           evenement_id="m1-lead-qualifie-LEAD-LECT")
        _devis_accepte("DEVIS-LECT", "LEAD-LECT")
        _repartir_jusqu_au_repos(M4, M6)
        (inscription,) = [m for m in _maillons() if m["type_entree"] == "intervention_inscrite"]
        avant = json.dumps(_maillons(), sort_keys=True)
        _volet_materiel(inscription["intervention_id"])
        assert json.dumps(_maillons(), sort_keys=True) == avant
