"""PLAN T4.7 (M3.14), par `Capacites` : la revue et l'envoi d'un devis par approbation N4 du propriétaire.

Le VRAI socle (`Capacites`, `approbations`, `approbations_appareil`, `identite`, le bus) sur le VRAI manifeste de M3
(mode `ombre`, N4 = `nathan_owner`), base SQLite temporaire migrée. On prouve, de bout en bout :

- le vendeur DEMANDE : le socle met la demande en file, l'outil ne s'exécute pas, le devis reste `brouillon` ;
- l'attente de la file du propriétaire PORTE LES MOTIFS de la revue (alerte rouge d'abord) ;
- un `admin` qui n'est pas le propriétaire, un gestionnaire, la finance, le vendeur ne peuvent pas décider, ni par la
  console (`approbations.decider`) ni par l'app (`approbations_appareil`) ;
- le propriétaire approuve : le devis passe `envoye` UNE fois, à l'instant de la décision, et `m3.devis_envoye` est
  publié (sans coût ni marge, validé par son JSON Schema) ; le rejeu ne fait rien ;
- l'outil ne s'exécute JAMAIS hors d'une décision (mode `autonome`, appel direct, décision d'un autre rôle).

Aucun outil d'envoi réel : le devis approuvé ne part pas seul, la livraison est à M1 (T2.1-c). Données fictives.
Peu de tests, chacun racontant un scénario : chaque test qui touche la base migre un SQLite neuf, et les outils de
mutation de M3 rejouent toute la suite du département à chaque mutant.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from m2_preparation_estimation import marqueur_m2
from sqlalchemy import func, select, update

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import contrats, hierarchie_echelle, revue_devis  # noqa: E402
from m3_estimation import outils as outils_m3  # noqa: E402

from opsys import (  # noqa: E402
    approbations,
    approbations_appareil,
    contexte,
    evenements,
    idempotence,
    identite,
    liaison_cibles,
    openclaw,
    stockage,
)
from opsys.capacites import Capacites, outils_executables  # noqa: E402
from opsys.departements import lire_manifeste  # noqa: E402
from opsys.evenements.schemas import erreurs_charge  # noqa: E402
from opsys.outils import Autonomie, Niveau, executer_atomique  # noqa: E402
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS  # noqa: E402

FICTIF = True
_RACINE_M3 = Path(__file__).resolve().parents[1]
_HORODATAGE = "2026-09-29T14:00:00-04:00"
_MOT_DE_PASSE = "un-mot-de-passe-suffisamment-long"
NOM = "m3_demander_envoi_devis"
DEP = "m03-estimation"
APPAREIL = "tel-fictif-t4-7"

VENDEUR = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
PROPRIO = contexte.IdentiteAppelante(personne="proprio", role="admin")
GESTIONNAIRE = contexte.IdentiteAppelante(personne="gestionnaire", role="admin")
FINANCE = contexte.IdentiteAppelante(personne="financeuse", role="admin")

NIVEAUX = hierarchie_echelle.NIVEAUX_CONFIANCE
# Le devis type : 1 600 $ de coût, 25 % de marge, 2 000,00 $ de prix (arithmétique exacte).
CONTEXTE_MONO_VUE = {
    "niveau_confiance_hierarchie": NIVEAUX[2],
    "verdict_estimation": contrats.VERDICT_AUCUN_BLOCAGE,
    "alerte_plancher": False,
    "service_complexe": False,
    "client_a_risque": False,
    "distance_km": "80",
    "donnees_fournisseur_completes": True,
}
SEUILS_DU_PROPRIETAIRE = {
    "confiance_minimale": NIVEAUX[1], "montant_maximal_cad": 10000, "marge_minimale": 0.30,
    "distance_maximale_km": 50, "minimum_rentable_cad": 2500,
}


# -- installation ---------------------------------------------------------------------------------------
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m3-envoi.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def dep():
    return lire_manifeste(_RACINE_M3)


@pytest.fixture
def departements(dep, base_durable):
    return {DEP: dep}


@pytest.fixture
def capacites(departements):
    return Capacites(departements, stockage.transaction, appelant=DEP, memoire=False)


@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un (fictif)", _MOT_DE_PASSE, ["seller"])
        identite.creer_personne(cnx, "proprio", "Propriétaire (fictif)", _MOT_DE_PASSE, ["admin", "nathan_owner"])
        identite.creer_personne(cnx, "gestionnaire", "Gestionnaire (fictive)", _MOT_DE_PASSE, ["admin", "manager"])
        identite.creer_personne(cnx, "financeuse", "Financeuse (fictive)", _MOT_DE_PASSE, ["admin", "finance"])


@pytest.fixture
def seuils_configures(tmp_path, monkeypatch):
    """Le propriétaire a fixé ses seuils : un manifeste jetable les porte (le vrai les laisse vides, à dessein)."""
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(json.dumps({"configuration": {"revue_devis": SEUILS_DU_PROPRIETAIRE}}), encoding="utf-8")
    monkeypatch.setattr(outils_m3, "_MANIFESTE", manifeste)


def _outil(nom):
    return next(o for o in outils_m3.outils() if o.nom == nom)


def _creer_devis(devis_id, lead_id="lead-un", cout="1600.00", taux="0.25"):
    reponse = executer_atomique(_outil("m3_creer_devis"), {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": [{"description": "Gouttière alu 5 po", "quantite": "1", "unite": "forfait",
                    "cout_unitaire": cout, "reference_besoin_materiau": None}],
        "taux_marge": taux, "horodatage": _HORODATAGE,
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    _assurer_lead_m2_et_liaison(lead_id)


def _assurer_lead_m2_et_liaison(lead_id):
    """Prépare les résolveurs canoniques M2 et M10 exigés par un ticket de session M3."""
    from m2_revenue_crm import ingestion, statuts
    from m2_revenue_crm import registre as registre_m2
    from m10_memoire import liaison as liaison_m10
    from m10_memoire import registre as registre_m10

    with stockage.transaction():
        reg_m2 = registre_m2.Registre(maillons=stockage.maillons("m02-revenue-crm", "principal"))
        if statuts.statut_courant(reg_m2, lead_id) is None:
            contrat = {
                "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
                "contact": {"nom": f"Client {lead_id}", "telephone": "555-0101"},
                "type_travaux": "renovation_totale", "ville": "Québec",
                "urgence_declaree": False, "canal": "telephone",
            }
            # Ingère dans la chaîne durable courante : créer un registre vierge par lead
            # concaténerait plusieurs racines et invaliderait la preuve de cible M2 suivante.
            nouveau = registre_m2.Registre(maillons=stockage.maillons("m02-revenue-crm", "principal"))
            _, verdict = ingestion.ingerer(contrat, nouveau, _HORODATAGE)
            assert verdict is None

    cle_session = f"agent:{DEP}:tests:{lead_id}"
    with stockage.transaction():
        reg_m10 = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        active = liaison_m10.liaison_courante(cle_session, reg_m10)
        if active is None:
            _, refus = liaison_m10.lier_session_affaire(
                cle_session, lead_id, "proprio", "admin", "appareil", "liaison M3 de fixture fictive",
                _HORODATAGE, reg_m10,
            )
            assert refus is None
        else:
            assert active["affaire_id"] == lead_id
    return cle_session


def _arguments(devis_id, contexte_revue=CONTEXTE_MONO_VUE):
    return {"devis_id": devis_id, "contexte_revue": contexte_revue}


def _demander(capacites, devis_id, contexte_revue=CONTEXTE_MONO_VUE, cle="cle-1", identite_appelante=VENDEUR):
    """Propose N4 depuis une session d'agent liée, avec un ticket privé sur les arguments finaux."""
    del identite_appelante  # Une identité d'appareil seule n'autorise pas cette mutation N4.
    arguments = _arguments(devis_id, contexte_revue)
    cache = getattr(capacites, "_tickets_fixture_m3", None)
    if cache is None:
        cache = {}
        capacites._tickets_fixture_m3 = cache
    cle_cache = (cle, idempotence.empreinte_arguments(arguments))
    if cle_cache not in cache:
        etat_devis = _etat_du_devis(devis_id)
        cle_session = _assurer_lead_m2_et_liaison(etat_devis["lead_id"])
        try:
            with stockage.transaction() as cnx:
                ticket = liaison_cibles.emettre_ticket(
                    cnx, departement=DEP, agent_id=DEP, cle_session=cle_session,
                    affaire_id=etat_devis["lead_id"], origine_affaire="session",
                    outil=NOM, arguments=arguments,
                )
        except liaison_cibles.CibleRefusee as exc:
            return {"ok": False, "erreur": "cible_refusee", "details": str(exc)}
        cache[cle_cache] = ticket["ticket"]
    return capacites.appeler(
        NOM, arguments, ticket_cible=liaison_cibles.TicketMeta(cache[cle_cache])
    )


def _demandes(statut=None):
    with stockage.transaction() as cnx:
        return [d for d in approbations.lister(cnx, statut) if d["outil"] == NOM]


def _etat_du_devis(devis_id):
    with stockage.transaction():
        etat, verdict = outils_m3.devis_durable.lire_devis(outils_m3.registre_devis_production(), devis_id)
    assert verdict is None, verdict
    return etat


def _evenements_envoye(devis_id):
    with stockage.transaction() as cnx:
        return cnx.execute(
            select(func.count()).select_from(EVENEMENTS_SORTANTS)
            .where(EVENEMENTS_SORTANTS.c.type_evenement == "m3.devis_envoye",
                   EVENEMENTS_SORTANTS.c.evenement_id == f"m3-devis-envoye-{devis_id}")
        ).scalar_one()


def _transitions_envoye(devis_id):
    with stockage.transaction():
        maillons = list(stockage.maillons(DEP, "devis"))
    return [m for m in maillons if m["devis_id"] == devis_id and m.get("statut") == "envoye"]


def _file(departements):
    with stockage.transaction() as cnx:
        return approbations.file_proprietaire(cnx, departements)


def _lister_app(departements, identite_appelante):
    with stockage.transaction() as cnx:
        return approbations_appareil.lister_demandes(cnx, departements, identite_appelante)


def _decider_app(departements, demande_id, identite_appelante, decision="approuver", appareil="tel-decision-1"):
    with stockage.transaction() as cnx:
        return approbations_appareil.decider_demande(
            cnx, departements, identite_appelante, demande_id, decision, "", appareil=appareil)


def _decider_console(departements, demande_id, personne, approuver=True):
    with stockage.transaction() as cnx:
        outils = outils_executables(departements, lambda: contextlib.nullcontext(cnx))
        return approbations.decider(cnx, demande_id, approuver, personne, outils, departements)


def _instantane_ecritures(devis_id):
    """Ce qu'un refus ne doit jamais changer : le statut du devis, ses maillons, l'événement publié."""
    return (len(_transitions_envoye(devis_id)), _evenements_envoye(devis_id), _etat_du_devis(devis_id)["statut"])


# =========================================================================================
# 1. Le vendeur DEMANDE : la demande attend, rien n'est envoyé, l'attente porte les motifs
# =========================================================================================
def test_le_vendeur_cree_l_attente_le_devis_reste_brouillon_et_la_file_porte_les_motifs(
    capacites, departements, personnes, seuils_configures
):
    _creer_devis("M3-DEVIS-envoi-001")

    reponse = _demander(capacites, "M3-DEVIS-envoi-001")

    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation", reponse
    [demande] = _demandes("en_attente")
    assert demande["id"] == reponse["demande_id"]
    assert demande["niveau"] == "N4" and demande["departement"] == DEP
    assert demande["arguments"] == _arguments("M3-DEVIS-envoi-001")  # exactement ce qui sera exécuté
    assert _instantane_ecritures("M3-DEVIS-envoi-001") == (0, 0, "brouillon"), "rien n'a été exécuté ni publié"

    # La file du propriétaire : la demande du socle, et l'attente de M3 dont le résumé PORTE LES MOTIFS.
    file = _file(departements)
    assert [i["type"] for i in file] == ["approbation", "revue_envoi_devis"]
    attente = file[1]
    assert attente["id"] == demande["id"] and attente["niveau"] == "N4" and attente["departement"] == DEP
    assert attente["depuis"] == demande["cree_le"]
    assert attente["resume"].startswith(
        "Envoi du devis M3-DEVIS-envoi-001 à approuver : ALERTE ROUGE : prix 2000.00 $ sous le minimum rentable 2500 $"
    )
    assert "confiance MONO_VUE_BORNES_LARGES sous MULTI_VUES" in attente["resume"]
    assert "mesure incertaine" in attente["resume"] and "marge 0.25 sous 0.3" in attente["resume"]
    assert "chantier à 80 km (max 50 km)" in attente["resume"]
    assert len(attente["resume"]) <= approbations_appareil.LIMITE_RESUME_ATTENTE  # l'app le montre en entier


def test_le_proprietaire_et_le_gestionnaire_lisent_les_motifs_dans_l_app_mais_seul_le_proprietaire_voit_les_arguments(
    capacites, departements, personnes, seuils_configures
):
    _creer_devis("M3-DEVIS-envoi-002")
    demande_id = _demander(capacites, "M3-DEVIS-envoi-002")["demande_id"]

    proprio, verdict = _lister_app(departements, PROPRIO)
    assert verdict is None
    [item] = proprio["demandes"]
    assert item["id"] == demande_id and item["decidable"] is True
    assert item["arguments"] == _arguments("M3-DEVIS-envoi-002")
    [attente] = proprio["attentes"]
    assert attente["type"] == "revue_envoi_devis" and "ALERTE ROUGE : prix 2000.00 $" in attente["resume"]
    assert attente["niveau"] == "N4" and attente["id"] == demande_id

    gestion, verdict = _lister_app(departements, GESTIONNAIRE)
    assert verdict is None
    [item] = gestion["demandes"]
    assert item["arguments"] is None and item["decidable"] is False  # lecture seule, sans les arguments
    assert item["lecture_seule"]["code"] == approbations_appareil.RESERVE_AU_PROPRIETAIRE
    assert [a["resume"] for a in gestion["attentes"]] == [attente["resume"]]  # les motifs, eux, se lisent


def test_les_seuils_vides_du_vrai_manifeste_disent_seuil_a_configurer_dans_la_file(capacites, departements, personnes):
    """Sans configuration (le vrai `department.yaml` laisse les seuils vides à dessein) : aucune valeur inventée."""
    _creer_devis("M3-DEVIS-envoi-003")
    _demander(capacites, "M3-DEVIS-envoi-003", contexte_revue=None)

    [attente] = [i for i in _file(departements) if i["type"] == "revue_envoi_devis"]

    assert attente["resume"] == (
        "Envoi du devis M3-DEVIS-envoi-003 à approuver : 11 critères non évaluables "
        "(seuil à configurer ou donnée à fournir)"
    )
    assert "ALERTE ROUGE" not in attente["resume"]  # sans seuil, aucune alerte n'est inventée


def test_une_demande_qu_on_ne_sait_pas_revoir_reste_visible_avec_sa_raison(capacites, departements, personnes):
    _creer_devis("M3-DEVIS-envoi-004")
    cle_session = _assurer_lead_m2_et_liaison("lead-un")
    arguments_inconnus = _arguments("M3-DEVIS-inconnu")
    with stockage.transaction() as cnx, pytest.raises(liaison_cibles.CibleRefusee, match="devis absent"):
        liaison_cibles.emettre_ticket(
            cnx, departement=DEP, agent_id=DEP, cle_session=cle_session,
            affaire_id="lead-un", origine_affaire="session", outil=NOM, arguments=arguments_inconnus,
        )
    # Un agent ne peut pas créer une attente visant un devis absent du registre canonique.
    agent = capacites.appeler(NOM, _arguments("M3-DEVIS-envoi-004", {"climat": "froid"}))
    assert agent["ok"] is False and agent["erreur"] == "ticket_cible_requis", agent
    # Le même agent avec un ticket lié à un devis connu peut demander la revue, qui conserve le motif d'entrée invalide.
    agent = _demander(capacites, "M3-DEVIS-envoi-004", {"climat": "froid"}, cle="cle-b")
    assert agent["ok"] is True and agent["statut"] == "en_attente_approbation", agent

    resumes = {i["resume"] for i in _file(departements) if i["type"] == "revue_envoi_devis"}

    assert any("revue impossible (REJ-REVUE-CONTEXTE-INVALIDE" in r and "climat" in r for r in resumes)
    assert all(len(r) <= revue_devis.LIMITE_RESUME for r in resumes)


def test_hors_transaction_l_attente_ne_lit_rien_et_ne_plante_pas():
    assert stockage.connexion_courante() is None
    assert outils_m3.attentes() == []


# =========================================================================================
# 2. Qui décide : le propriétaire, et lui seul (console et app)
# =========================================================================================
def test_une_personne_qui_n_est_pas_le_proprietaire_ne_peut_ni_approuver_ni_refuser_par_la_console(
    capacites, departements, personnes, seuils_configures
):
    _creer_devis("M3-DEVIS-envoi-010")
    demande_id = _demander(capacites, "M3-DEVIS-envoi-010")["demande_id"]

    for personne in ("gestionnaire", "financeuse", "vendeur.un"):  # admin+manager, admin+finance, seller
        for approuver in (True, False):
            with pytest.raises(ValueError, match="aucun rôle autorisé pour N4"):
                _decider_console(departements, demande_id, personne, approuver=approuver)

        assert _demandes("en_attente")[0]["id"] == demande_id, f"{personne} : la demande attend toujours"
        assert _instantane_ecritures("M3-DEVIS-envoi-010") == (0, 0, "brouillon"), personne


def test_un_admin_qui_n_est_pas_proprietaire_ne_peut_pas_decider_depuis_l_app(
    capacites, departements, personnes, seuils_configures
):
    _creer_devis("M3-DEVIS-envoi-011")
    demande_id = _demander(capacites, "M3-DEVIS-envoi-011")["demande_id"]

    for appelante, code in (
        (GESTIONNAIRE, approbations_appareil.RESERVE_AU_PROPRIETAIRE),  # `admin` sans `nathan_owner`
        (FINANCE, approbations_appareil.RESERVE_AU_PROPRIETAIRE),
        (VENDEUR, approbations_appareil.ROLE_APPAREIL_INSUFFISANT),
    ):
        for decision in ("approuver", "refuser"):
            resultat, verdict = _decider_app(departements, demande_id, appelante, decision=decision)

            assert resultat is None and verdict["code"] == code, (appelante.personne, decision, verdict)
        assert _demandes("en_attente")[0]["id"] == demande_id, appelante.personne
        assert _instantane_ecritures("M3-DEVIS-envoi-011") == (0, 0, "brouillon"), appelante.personne


def test_le_manifeste_reserve_le_n4_de_m3_au_proprietaire_comme_l_outil_le_relit(dep):
    assert dep.roles_autorises(Niveau.N4) == frozenset({"nathan_owner"}) == outils_m3._ROLES_APPROBATEURS_ENVOI
    assert dep.mode == "ombre"
    assert "m3.devis_envoye" in dep.evenements_publie


# =========================================================================================
# 3. Le propriétaire approuve : envoye UNE fois, m3.devis_envoye publié, sans coût ni marge
# =========================================================================================
def test_le_proprietaire_approuve_le_devis_passe_envoye_une_fois_et_l_evenement_est_publie(
    capacites, departements, personnes, seuils_configures
):
    _creer_devis("M3-DEVIS-envoi-020", lead_id="lead-envoi-020")
    demande_id = _demander(capacites, "M3-DEVIS-envoi-020")["demande_id"]

    resultat, verdict = _decider_app(departements, demande_id, PROPRIO)

    assert verdict is None
    assert resultat["statut"] == "executee" and resultat["decide_par"] == "proprio"
    assert resultat["role"] == "nathan_owner"
    assert resultat["issue"] == {"ok": True, "accepte": True}
    with stockage.transaction() as cnx:
        decidee = approbations.lire(cnx, demande_id)
    assert decidee["statut"] == "executee" and decidee["decide_role"] == "nathan_owner"

    # Le devis : envoye, à l'instant de la décision du socle, avec qui a approuvé et ce qui a été regardé.
    devis = _etat_du_devis("M3-DEVIS-envoi-020")
    assert devis["statut"] == "envoye" and devis["horodatage"] == decidee["decide_le"]
    assert devis["envoi_approuve_par"] == "proprio" and devis["envoi_approuve_role"] == "nathan_owner"
    assert devis["revue_envoi"] == {
        "alerte_rouge": True,
        "motifs": ["PRIX_SOUS_MINIMUM_RENTABLE", "CONFIANCE_SOUS_SEUIL", "MESURE_INCERTAINE", "MARGE_SOUS_SEUIL",
                   "CHANTIER_ELOIGNE"],
        "non_evaluables": [],
    }
    assert str(devis["prix_total"]) == "2000.00"  # les lignes et les totaux ont survécu à la transition

    # L'événement : publié dans la même transaction, identifiant déterministe, conforme à son JSON Schema.
    with stockage.transaction():
        charge = evenements.charge_publiee("m3.devis_envoye", "m3-devis-envoye-M3-DEVIS-envoi-020")
    assert charge == {
        "devis_id": "M3-DEVIS-envoi-020", "lead_id": "lead-envoi-020", "chantier_id": None,
        "horodatage_envoi": decidee["decide_le"],
    }
    assert erreurs_charge("m3.devis_envoye", charge) == []
    texte = json.dumps(charge)
    assert set(charge) == {"devis_id", "lead_id", "chantier_id", "horodatage_envoi"}
    assert not any(interdit in texte for interdit in ("cout", "marge", "prix", "2000.00", "1600.00", "0.25", "lignes"))

    # La demande n'est plus en file.
    assert _demandes("en_attente") == []
    assert [i for i in _file(departements) if i["type"] == "revue_envoi_devis"] == []


def test_un_refus_du_proprietaire_ne_change_rien_et_l_attente_disparait(
    capacites, departements, personnes, seuils_configures
):
    _creer_devis("M3-DEVIS-envoi-021")
    demande_id = _demander(capacites, "M3-DEVIS-envoi-021")["demande_id"]

    resultat, verdict = _decider_app(departements, demande_id, PROPRIO, decision="refuser")

    assert verdict is None and resultat["statut"] == "refusee"
    assert _instantane_ecritures("M3-DEVIS-envoi-021") == (0, 0, "brouillon")
    assert _file(departements) == []


def test_le_rejeu_est_sans_effet_meme_cle_meme_demande_redecision_et_nouvelle_demande_apres_l_envoi(
    capacites, departements, personnes, seuils_configures
):
    _creer_devis("M3-DEVIS-envoi-022")

    premiere = _demander(capacites, "M3-DEVIS-envoi-022", cle="cle-rejeu")
    rejouee = _demander(capacites, "M3-DEVIS-envoi-022", cle="cle-rejeu")  # le réseau a coupé : le téléphone renvoie
    # La voie ticketée n'ajoute `rejoue` qu'au rejeu : la première réponse reste celle du contrat N3.
    assert premiere.get("rejoue", False) is False and rejouee["rejoue"] is True
    assert rejouee["demande_id"] == premiere["demande_id"]
    assert len(_demandes()) == 1, "la même clé ne crée pas une seconde demande"

    resultat, verdict = _decider_app(departements, premiere["demande_id"], PROPRIO)
    assert verdict is None and resultat["issue"] == {"ok": True, "accepte": True}
    apres_envoi = _instantane_ecritures("M3-DEVIS-envoi-022")
    envoye_le = _etat_du_devis("M3-DEVIS-envoi-022")["horodatage"]
    assert apres_envoi == (1, 1, "envoye")

    # Décider une seconde fois la même demande : « déjà décidée », rien n'est refait.
    resultat, verdict = _decider_app(departements, premiere["demande_id"], PROPRIO, appareil="tel-decision-2")
    assert resultat is None and verdict["code"] == approbations_appareil.DEJA_DECIDEE
    assert _instantane_ecritures("M3-DEVIS-envoi-022") == apres_envoi

    # Une NOUVELLE demande pour le même devis (autre clé), approuvée : un rejeu, sans effet ni republication.
    seconde = _demander(capacites, "M3-DEVIS-envoi-022", cle="cle-nouvelle")
    assert seconde["statut"] == "en_attente_approbation" and seconde["demande_id"] != premiere["demande_id"]
    [attente] = [i for i in _file(departements) if i["type"] == "revue_envoi_devis"]
    assert "déjà envoye : rien à approuver" in attente["resume"]
    resultat, verdict = _decider_app(departements, seconde["demande_id"], PROPRIO, appareil="tel-decision-3")
    assert verdict is None and resultat["issue"] == {"ok": True, "accepte": True}
    with stockage.transaction() as cnx:
        assert approbations.lire(cnx, seconde["demande_id"])["resultat"]["resultat"]["resultat"]["deja_envoye"] is True
    assert _instantane_ecritures("M3-DEVIS-envoi-022") == apres_envoi, "ni transition, ni événement de plus"
    assert _etat_du_devis("M3-DEVIS-envoi-022")["horodatage"] == envoye_le


def test_un_devis_deja_accepte_ne_s_envoie_pas_et_une_revue_impossible_refuse_l_envoi(
    capacites, departements, personnes, seuils_configures
):
    _creer_devis("M3-DEVIS-envoi-023")
    _creer_devis("M3-DEVIS-envoi-024", lead_id="lead-024")
    accepte = executer_atomique(_outil("m3_marquer_devis_accepte"), {
        "devis_id": "M3-DEVIS-envoi-023", "approbateur": "proprio", "horodatage": _HORODATAGE})
    assert accepte["ok"] is True and accepte["resultat"]["accepte"] is True
    a = _demander(capacites, "M3-DEVIS-envoi-023", cle="cle-a")["demande_id"]
    b = _demander(capacites, "M3-DEVIS-envoi-024", contexte_revue={"distance_km": -5}, cle="cle-b")["demande_id"]

    resultat_a, _ = _decider_app(departements, a, PROPRIO, appareil="tel-a")
    resultat_b, _ = _decider_app(departements, b, PROPRIO, appareil="tel-b")

    # L'exécution réussit techniquement, le verdict métier dit non : rien n'est envoyé ni publié.
    assert resultat_a["issue"]["accepte"] is False
    assert resultat_a["issue"]["verdict"]["code"] == "REJ-DEVIS-TRANSITION-ILLEGALE"
    assert resultat_b["issue"]["accepte"] is False
    assert resultat_b["issue"]["verdict"]["code"] == "REJ-REVUE-CONTEXTE-INVALIDE"
    assert _instantane_ecritures("M3-DEVIS-envoi-023") == (0, 0, "accepte")
    assert _instantane_ecritures("M3-DEVIS-envoi-024") == (0, 0, "brouillon")


# =========================================================================================
# 4. L'outil ne s'exécute JAMAIS hors d'une décision du propriétaire (défense en profondeur)
# =========================================================================================
def test_un_appel_direct_sans_decision_est_refuse_et_n_ecrit_rien(personnes):
    _creer_devis("M3-DEVIS-envoi-030")

    reponse = executer_atomique(_outil(NOM), _arguments("M3-DEVIS-envoi-030"))

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-ENVOI-SANS-APPROBATION"
    assert _instantane_ecritures("M3-DEVIS-envoi-030") == (0, 0, "brouillon")


def test_en_mode_autonome_le_socle_n_a_pas_de_file_pour_le_n4_mais_l_outil_refuse_de_lui_meme(
    capacites, personnes
):
    """Le mode `autonome` ne met que N5 en file (`politiques`) : sans cette garde, un agent enverrait le devis."""
    _creer_devis("M3-DEVIS-envoi-031")
    with stockage.transaction() as cnx:
        approbations.fixer_mode(cnx, DEP, "autonome", "proprio")

    # Même en mode autonome, une session doit d'abord prouver sa cible canonique par un ticket.
    reponse = _demander(capacites, "M3-DEVIS-envoi-031")

    assert reponse["ok"] is True and "statut" not in reponse, "aucune demande : le socle a exécuté l'outil"
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-ENVOI-SANS-APPROBATION"
    assert _instantane_ecritures("M3-DEVIS-envoi-031") == (0, 0, "brouillon")
    assert _demandes() == []


def _executer_sous_une_demande_reservee(
    devis_a_executer, devis_enregistre, decide_par, decide_role, actif=True, statut="en_cours",
):
    """Exécute l'outil comme le fait `approbations.decider` : une demande `en_cours` (réservée par un signataire)
    portant les arguments ENREGISTRÉS, puis l'appel de l'outil avec les arguments À EXÉCUTER. `statut` permet de
    montrer qu'une demande qui n'est PAS en cours de décision n'autorise rien."""
    with stockage.transaction() as cnx:
        ident = approbations.creer_demande(cnx, DEP, NOM, _arguments(devis_enregistre), niveau=Niveau.N4)
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(
            statut=statut, decide_par=decide_par, decide_role=decide_role,
            decide_le="2026-09-29T18:00:00+00:00"))
        if not actif:
            identite.activer(cnx, "proprio", False)
        return executer_atomique(_outil(NOM), _arguments(devis_a_executer))


def test_seule_la_decision_du_proprietaire_sur_ces_arguments_fait_executer_l_outil(personnes):
    """Chaque refus, puis le contrepoint : la MÊME construction avec le bon signataire réussit."""
    refus = (
        ("une décision d'un AUTRE devis", "proprio", "nathan_owner", "autre", "en_cours"),
        ("un rôle que le manifeste n'autorise pas pour N4", "gestionnaire", "admin", "meme", "en_cours"),
        ("la finance", "financeuse", "finance", "meme", "en_cours"),
        ("un rôle que la personne ne porte pas", "proprio", "manager", "meme", "en_cours"),
        ("un rôle autorisé que le signataire ne porte pas", "gestionnaire", "nathan_owner", "meme", "en_cours"),
        ("une demande réservée sans signataire", None, "nathan_owner", "meme", "en_cours"),
        ("une demande encore en attente", "proprio", "nathan_owner", "meme", "en_attente"),
        ("une demande déjà exécutée (un second appel direct)", "proprio", "nathan_owner", "meme", "executee"),
    )
    for numero, (raison, decide_par, decide_role, arguments, statut) in enumerate(refus):
        devis_id, autre = f"M3-DEVIS-envoi-03{numero}", f"M3-DEVIS-envoi-03{numero}-autre"
        _creer_devis(devis_id, lead_id=f"lead-{numero}")
        _creer_devis(autre, lead_id=f"lead-{numero}-autre")

        reponse = _executer_sous_une_demande_reservee(
            devis_id, autre if arguments == "autre" else devis_id, decide_par, decide_role, statut=statut)

        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, (raison, reponse)
        assert reponse["resultat"]["verdict"]["code"] == "REJ-ENVOI-SANS-APPROBATION", raison
        assert _instantane_ecritures(devis_id) == (0, 0, "brouillon"), raison

    _creer_devis("M3-DEVIS-envoi-039", lead_id="lead-039")
    reponse = _executer_sous_une_demande_reservee("M3-DEVIS-envoi-039", "M3-DEVIS-envoi-039", "proprio", "nathan_owner")
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    assert _etat_du_devis("M3-DEVIS-envoi-039")["horodatage"] == "2026-09-29T18:00:00+00:00"  # l'instant du socle
    assert _instantane_ecritures("M3-DEVIS-envoi-039") == (1, 1, "envoye")

    # Le propriétaire désactivé entre la réservation et l'exécution : plus une décision.
    _creer_devis("M3-DEVIS-envoi-038", lead_id="lead-038")
    reponse = _executer_sous_une_demande_reservee(
        "M3-DEVIS-envoi-038", "M3-DEVIS-envoi-038", "proprio", "nathan_owner", actif=False)
    assert reponse["resultat"]["verdict"]["code"] == "REJ-ENVOI-SANS-APPROBATION"
    assert _instantane_ecritures("M3-DEVIS-envoi-038") == (0, 0, "brouillon")


# =========================================================================================
# 5. La déclaration de l'outil : niveau, portée, schémas
# =========================================================================================
def test_l_outil_est_n4_t2_ouvert_au_vendeur_et_a_l_admin_jamais_a_l_employe(dep):
    outil = _outil(NOM)

    assert outil.autonomie is Autonomie.T2 and outil.niveau_effectif is Niveau.N4
    assert outil.frontiere_humaine is False  # N4 se décide depuis l'app (N5 et T3 : jamais)
    assert outil.roles_appareil == frozenset({"seller", "admin"})
    portees = openclaw.roles_outils({DEP: dep})
    assert NOM in portees["seller"] and NOM in portees["admin"] and NOM not in portees["employee"]


def test_les_parametres_de_l_outil_sont_un_json_schema_valide_qui_ferme_l_objet_et_les_enums():
    parametres = _outil(NOM).parametres
    Draft202012Validator.check_schema(parametres)
    validateur = Draft202012Validator(parametres)

    assert validateur.is_valid(_arguments("D-1"))
    assert validateur.is_valid({"devis_id": "D-1", "contexte_revue": None})
    # contexte_revue est requis : la demande approuvée rejoue les arguments exacts, sans clé manquante.
    assert not validateur.is_valid({"devis_id": "D-1"})
    assert not validateur.is_valid({"contexte_revue": None})
    assert not validateur.is_valid({**_arguments("D-1"), "horodatage": "2026-09-29T14:00:00-04:00"})
    assert not validateur.is_valid({**_arguments("D-1"), "approbateur": "proprio"}), "l'approbateur vient du socle"
    assert not validateur.is_valid(_arguments("D-1", {"niveau_confiance_hierarchie": "EXCELLENT"}))
    assert not validateur.is_valid(_arguments("D-1", {"climat": "froid"}))
    propres = parametres["properties"]["contexte_revue"]["properties"]
    assert propres["niveau_confiance_hierarchie"]["enum"] == list(NIVEAUX)
    assert propres["verdict_estimation"]["enum"] == list(contrats.VERDICTS_ESTIMATION)
    assert set(propres) == set(revue_devis.CHAMPS_CONTEXTE)


def test_le_schema_de_l_evenement_est_ferme_et_refuse_tout_montant():
    charge = {
        "devis_id": "D-1", "lead_id": "L-1", "chantier_id": "C-1", "horodatage_envoi": "2026-09-29T18:00:00+00:00",
    }

    assert erreurs_charge("m3.devis_envoye", charge) == []
    assert erreurs_charge("m3.devis_envoye", {**charge, "chantier_id": None}) == []
    for interdit in ("cout_total", "prix_total", "taux_marge", "lignes", "revue_envoi", "approuve_par"):
        assert erreurs_charge("m3.devis_envoye", {**charge, interdit: "1"}), interdit
    for manquant in charge:
        assert erreurs_charge("m3.devis_envoye", {c: v for c, v in charge.items() if c != manquant}), manquant
    assert erreurs_charge("m3.devis_envoye", {**charge, "devis_id": ""})
    assert erreurs_charge("m3.devis_envoye", {**charge, "horodatage_envoi": 1234})


def _creer_devis_source_revue(*, photos_valides=False, legacy=False, remplacer_faits=False, faits=None):
    lead_id = "lead-source-revue-fictif"
    estimation = executer_atomique(_outil("m3_estimer_projet"), {
        "contrat": {"lead_id": lead_id, "conversation_id": "conv-source-revue-fictif",
                    "type_travaux": "ravalement", "ville": "Quebec", "canal": "formulaire_web",
                    "contact": {"nom": "Client fictif", "telephone": "555-0101"},
                    "urgence_declaree": False},
        "marqueur": marqueur_m2(lead_id),
        "photos": [{"photo_id": "p-fictif", "resolution_largeur": 3000 if photos_valides else 640,
                    "resolution_hauteur": 2000, "eclairage": 7, "angle": "face",
                    "reference_echelle": {"type": "porte", "dimensions_connues": True}
                    if photos_valides else None}],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": {"version": "prix-fictifs-v1", "unite": "pi2",
                   "postes": {"ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}}},
        "quantite": 1, "plancher_rentable": 1, "graine": 42,
    })
    assert estimation["ok"] and estimation["resultat"]["accepte"]
    est = estimation["resultat"]["estimation"]
    assert est["prix_bloque"] is (not photos_valides)
    source_hash = est["hash_maillon"]
    if legacy or remplacer_faits:
        charge = dict(outils_m3.registre_production().lire()[0]["charge"])
        if legacy:
            charge.pop("faits_revue", None)
        else:
            charge["faits_revue"] = faits
        with stockage.transaction():
            legacy_registre = outils_m3.registre_production()
            maillon, verdict = legacy_registre.ajouter(charge)
        assert verdict is None
        source_hash = maillon["hash_maillon"]
    created = executer_atomique(_outil("m3_creer_devis"), {
        "devis_id": est["devis_id"], "lead_id": lead_id, "chantier_id": None,
        "lignes": [{"description": "Forfait fictif manuel", "quantite": "1", "unite": "forfait",
                    "cout_unitaire": "4000.00", "reference_besoin_materiau": None}],
        "taux_marge": "0.35", "horodatage": _HORODATAGE, "estimation_source_hash": source_hash,
    })
    assert created["ok"] and created["resultat"]["accepte"]
    _assurer_lead_m2_et_liaison(lead_id)
    return est["devis_id"], source_hash


@pytest.mark.parametrize("photos_valides", [False, True])
def test_source_canonique_prime_sur_contexte_dans_file_et_decision(
    capacites, departements, personnes, seuils_configures, photos_valides
):
    devis_id, source_hash = _creer_devis_source_revue(photos_valides=photos_valides)
    contexte_fourni = {**CONTEXTE_MONO_VUE, "niveau_confiance_hierarchie": NIVEAUX[0],
                       "verdict_estimation": contrats.VERDICT_AUCUN_BLOCAGE,
                       "distance_km": "0"}
    demande_id = _demander(capacites, devis_id, contexte_fourni)["demande_id"]
    [attente] = [x for x in _file(departements) if x["type"] == "revue_envoi_devis"]
    assert ("photos insuffisantes" in attente["resume"]) is (not photos_valides)
    assert _etat_du_devis(devis_id)["statut"] == "brouillon"
    assert _evenements_envoye(devis_id) == 0
    resultat, verdict = _decider_app(departements, demande_id, PROPRIO)
    assert verdict is None and resultat["statut"] == "executee"
    envoye = _etat_du_devis(devis_id)
    assert ("PHOTOS_INSUFFISANTES" in envoye["revue_envoi"]["motifs"]) is (not photos_valides)
    with stockage.transaction() as cnx:
        decidee = approbations.lire(cnx, demande_id)
    revue = decidee["resultat"]["resultat"]["resultat"]["revue"]
    if not photos_valides:
        motif = next(m for m in revue["motifs"] if m["code"] == "PHOTOS_INSUFFISANTES")
        assert motif["donnee"]["source"] == "estimation_canonique"
    assert revue["source_estimation"]["hash_maillon"] == source_hash
    assert str(envoye["prix_total"]) == "5400.00"


def test_source_legacy_sans_faits_est_non_evaluable_sans_inventer_des_photos(
    capacites, departements, personnes, seuils_configures
):
    devis_id, source_hash = _creer_devis_source_revue(legacy=True)
    supplied = {**CONTEXTE_MONO_VUE, "verdict_estimation": contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE}
    demande_id = _demander(capacites, devis_id, supplied)["demande_id"]
    [attente] = [x for x in _file(departements) if x["type"] == "revue_envoi_devis"]
    assert "source historique sans faits de revue" in attente["resume"]
    resultat, verdict = _decider_app(departements, demande_id, PROPRIO)
    assert verdict is None and resultat["statut"] == "executee"
    devis = _etat_du_devis(devis_id)
    assert "PHOTOS_INSUFFISANTES" not in devis["revue_envoi"]["motifs"]
    assert "SOURCE_ESTIMATION_HISTORIQUE_SANS_FAITS" in devis["revue_envoi"]["non_evaluables"]
    assert devis["estimation_source_hash"] == source_hash
    with stockage.transaction() as cnx:
        decidee = approbations.lire(cnx, demande_id)
    revue = decidee["resultat"]["resultat"]["resultat"]["revue"]
    assert all(isinstance(x[cle], list) and all(isinstance(texte, str) for texte in x[cle])
               for x in revue["non_evaluables"] for cle in ("manque", "a_faire"))


@pytest.mark.parametrize("faits", [None, {"version": "m3.faits-revue/v1"}, "non canonique"])
def test_snapshot_source_invalide_ne_retombe_jamais_sur_faits_declares(
    capacites, departements, personnes, seuils_configures, faits
):
    devis_id, _ = _creer_devis_source_revue(remplacer_faits=True, faits=faits)
    supplied = {**CONTEXTE_MONO_VUE, "verdict_estimation": contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE}
    demande_id = _demander(capacites, devis_id, supplied)["demande_id"]
    [attente] = [x for x in _file(departements) if x["type"] == "revue_envoi_devis"]
    assert "faits de revue source invalides ou non disponibles" in attente["resume"]
    resultat, verdict = _decider_app(departements, demande_id, PROPRIO)
    assert verdict is None and resultat["statut"] == "executee"
    devis = _etat_du_devis(devis_id)
    assert "PHOTOS_INSUFFISANTES" not in devis["revue_envoi"]["motifs"]
    assert "SOURCE_ESTIMATION_FAITS_NON_EVALUABLES" in devis["revue_envoi"]["non_evaluables"]


@pytest.mark.parametrize("absente", [False, True])
def test_source_perdue_ou_alteree_apres_demande_est_refusee_sans_envoi(
    capacites, departements, personnes, seuils_configures, absente
):
    from sqlalchemy import delete

    from opsys.stockage.schema import REGISTRES

    devis_id, _ = _creer_devis_source_revue(photos_valides=True)
    demande_id = _demander(capacites, devis_id)["demande_id"]
    assert _etat_du_devis(devis_id)["statut"] == "brouillon"
    with stockage.transaction() as cnx:
        filtre = (REGISTRES.c.departement == DEP) & (REGISTRES.c.registre == "principal")
        if absente:
            cnx.execute(delete(REGISTRES).where(filtre))
        else:
            from opsys.stockage import codec
            [maillon] = list(outils_m3.registre_production().lire())
            maillon["charge"]["lead_id"] = "autre-lead-fictif"
            cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(maillon)))
    [attente] = [x for x in _file(departements) if x["type"] == "revue_envoi_devis"]
    assert "revue impossible" in attente["resume"]
    assert "source d'estimation" in attente["resume"]
    resultat, verdict = _decider_app(departements, demande_id, PROPRIO)
    assert verdict is None and resultat["statut"] == "echec"
    assert _etat_du_devis(devis_id)["statut"] == "brouillon"
    assert _evenements_envoye(devis_id) == 0
