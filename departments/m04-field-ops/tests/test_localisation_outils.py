"""PLAN T4.1-a : les outils `m4_proposer_localisation` et `m4_confirmer_localisation`, sur les VRAIS
outils, le registre durable (base SQLite migrée, ADR-0009) et un index RQA importé dans le dossier d'état
de l'instance (`<OPSYS_HOME>/rqa/index.sqlite`), appelés comme en production (`executer_atomique`).

Le RQA de ces tests est FICTIF (`tests/data/rqa_fictif.csv`) ; les personnes, appareils et chantiers le
sont aussi. Les refus sont prouvés SANS écriture : le registre ET la table des clés de chiffrement sont
comparés avant et après. Le contrôle d'accès suit celui de T1.4-k (`acces.py`) : l'admin authentifié est
tracé sous son nom, un employé est refusé, un autre nom que le sien est refusé sans être remplacé.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import socket
from pathlib import Path

import pytest
from m4_field_ops import localisation
from m4_field_ops import registre as registre_m4
from m4_field_ops.outils import lire_localisation_confirmee, outils
from sqlalchemy import select

from opsys import approbations, cles_chiffrement, contexte, identite, politiques, stockage
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage.schema import CLES_CHIFFREMENT

FICTIF = True
M4 = Path(__file__).resolve().parents[1]
DONNEES = Path(__file__).parent / "data" / "rqa_fictif.csv"
HORLOGE_APPAREIL_DEREGLEE = dt.datetime(2000, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
RECU_LE = dt.datetime(2025, 6, 2, 9, 0, 0, tzinfo=dt.UTC)
HORODATAGE_ARGUMENT = "2030-01-01T00:00:00+00:00"

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
MARIE = contexte.IdentiteAppelante(personne="marie.fictif", role="admin")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")
FANTOME = contexte.IdentiteAppelante(personne="fantome.fictif", role="admin")

CHANTIER = "C-LOC-1"
ADRESSE = {"numero_municipal": "100", "odonyme": "boulevard Iberville", "municipalite": "Repentigny"}
ADRESSE_INCONNUE = {"numero_municipal": "999", "odonyme": "rue Inconnue", "municipalite": "Repentigny"}
PORTEE = localisation.PORTEE_CLES_LOCALISATION


# -- installation -----------------------------------------------------------------------------------
@pytest.fixture
def instance(tmp_path, monkeypatch):
    """Base SQLite migrée ET dossier d'état (`OPSYS_HOME`) jetables, comme au démarrage de l'instance."""
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "marie.fictif", "Marie Fictive", "mot-de-passe-marie-12345", ["admin"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def par_nom(instance):
    return {o.nom: o for o in outils()}


@pytest.fixture
def rqa_importe(instance):
    return localisation.importer_rqa(
        DONNEES, stockage.dossier_opsys() / localisation.SOUS_DOSSIER_INDEX / localisation.NOM_FICHIER_INDEX)


@pytest.fixture
def sockets_bloques(monkeypatch):
    def interdit(*_args, **_kwargs):
        raise AssertionError("accès réseau interdit dans la localisation")

    class SocketInterdit:
        def __init__(self, *_args, **_kwargs):
            interdit()

    monkeypatch.setattr(socket, "socket", SocketInterdit)
    monkeypatch.setattr(socket, "create_connection", interdit)
    monkeypatch.setattr(socket, "getaddrinfo", interdit)
    monkeypatch.setattr(socket, "gethostbyname", interdit)


# -- aides -------------------------------------------------------------------------------------------
@contextlib.contextmanager
def _appareil(identite_appelante, recu_le=RECU_LE):
    """Ce que le serveur MCP pose pour un appel d'appareil : l'identité authentifiée ET les deux
    horloges. Sans identité : un appel d'agent."""
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
            pile.enter_context(contexte.receptionne_de(contexte.HorodatageAppareil(
                appareil="tel-fictif-t4-1-a", horodatage_appareil=HORLOGE_APPAREIL_DEREGLEE, recu_le=recu_le)))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=None):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _proposer(par_nom, adresse=ADRESSE, identite_appelante=ADMIN, **extra):
    return _appeler(par_nom, "m4_proposer_localisation", {"adresse": adresse, **extra}, identite_appelante)


def _confirmer(par_nom, identite_appelante=ADMIN, **arguments):
    donnees = {"chantier_id": CHANTIER, "action": "confirmee", "horodatage": HORODATAGE_ARGUMENT,
               "confirme_par": identite_appelante.personne if identite_appelante else "agent.fictif", **arguments}
    return _appeler(par_nom, "m4_confirmer_localisation", donnees, identite_appelante)


def _confirmer_rqa(par_nom, identite_appelante=ADMIN, adresse=ADRESSE, identifiant="f001", **extra):
    return _confirmer(par_nom, identite_appelante, adresse=adresse, source="rqa", rqa_identifiant=identifiant, **extra)


def _code_refus(reponse):
    """Code du verdict d'un refus métier : `ok` reste vrai (l'outil a répondu), `accepte` est faux."""
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _resultat(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _registre():
    return registre_m4.Registre(stockage.maillons("m04-field-ops", "principal"))


def _maillons():
    with stockage.transaction():
        return _registre().lire()


def _cles():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(
            CLES_CHIFFREMENT.c.portee, CLES_CHIFFREMENT.c.identifiant, CLES_CHIFFREMENT.c.cle)).all()
    return sorted(tuple(ligne) for ligne in lignes)


def _etat():
    """Tout ce qu'un outil de localisation pourrait écrire : les maillons ET les clés."""
    return _maillons(), _cles()


def _lire(chantier=CHANTIER, adresse=None):
    with stockage.transaction():
        return lire_localisation_confirmee(_registre(), chantier, adresse)


def _localisations(chantier=CHANTIER):
    return [m for m in _maillons() if m["type_entree"] == "localisation_chantier" and m["chantier_id"] == chantier]


# =========================================================================================
# 1. Déclaration des outils : niveau, autonomie, portée d'appareil
# =========================================================================================
def test_les_deux_outils_sont_declares_avec_leur_niveau_et_leur_portee(par_nom):
    proposer, confirmer = par_nom["m4_proposer_localisation"], par_nom["m4_confirmer_localisation"]
    assert proposer.autonomie is Autonomie.T0 and proposer.niveau_effectif is Niveau.N0
    # Écriture interne non finale : N3 (défaut de T1), pas N2 (automatique), pas N4 (rien d'externe).
    assert confirmer.autonomie is Autonomie.T1 and confirmer.niveau is None
    assert confirmer.niveau_effectif is Niveau.N3
    assert not confirmer.frontiere_humaine
    for outil in (proposer, confirmer):
        assert outil.roles_appareil == frozenset({"admin"}), outil.nom


def test_en_mode_ombre_un_appel_d_agent_a_confirmer_passe_par_la_file_pas_la_proposition(par_nom):
    assert politiques.approbation_requise_niveau(par_nom["m4_confirmer_localisation"].niveau_effectif, "ombre")
    assert not politiques.approbation_requise_niveau(par_nom["m4_proposer_localisation"].niveau_effectif, "ombre")
    # Et l'admin qui confirme lui-même depuis son téléphone valide « au départ » (T1.4-h) : N3 au plus.
    assert politiques.validation_au_depart_possible(par_nom["m4_confirmer_localisation"].niveau_effectif)


def test_le_manifeste_charge_les_outils_et_la_skill_de_localisation():
    departement = lire_manifeste(M4)
    noms = [o.nom for o in departement.charger_outils()]
    assert "m4_proposer_localisation" in noms and "m4_confirmer_localisation" in noms
    assert "localiser-un-chantier" in departement.skills
    skill = (M4 / "skills" / "localiser-un-chantier" / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: localiser-un-chantier\n")


# =========================================================================================
# 2. m4_proposer_localisation : lecture seule
# =========================================================================================
def test_proposition_par_l_outil_ne_confirme_ni_n_ecrit_rien(par_nom, rqa_importe):
    avant = _etat()
    resultat = _resultat(_proposer(par_nom))
    assert resultat["statut"] == "proposee" and resultat["confirmation_humaine_requise"] is True
    assert resultat["coordonnees"] == {"latitude_microdegres": 45741000, "longitude_microdegres": -73450000}
    assert resultat["rqa_identifiant"] == "f001" and resultat["rqa_version"] == "2026-09-01"
    assert resultat["precision"] == "batiment" and "CC-BY 4.0" in resultat["attribution"]
    assert _etat() == avant  # aucune écriture, aucune clé créée


def test_proposition_accepte_une_ligne_d_adresse(par_nom, rqa_importe):
    resultat = _resultat(_proposer(par_nom, "776 ch. de la Marquise S., Terrebonne J6W 1F8"))
    assert resultat["rqa_identifiant"] == "f013" and resultat["precision"] == "centre_lot"


def test_doublon_et_absence_sont_le_verdict_a_confirmer_avec_les_candidats(par_nom, rqa_importe):
    avant = _etat()
    doublon = _proposer(par_nom, "30 rue Principale, Saint-Paul")
    assert _code_refus(doublon) == "REJ-COORDONNEES-A-CONFIRMER"
    reponse = doublon["resultat"]
    assert "coordonnées manquantes : à confirmer" in reponse["verdict"]["detail"]
    assert reponse["raison"] == "plusieurs_correspondances" and reponse["nombre_candidats"] == 2
    assert {c["rqa_identifiant"] for c in reponse["candidats"]} == {"f011", "f012"}
    assert "coordonnees" not in reponse and "resultat" not in reponse  # aucun candidat n'est choisi
    absent = _proposer(par_nom, ADRESSE_INCONNUE)
    assert _code_refus(absent) == "REJ-COORDONNEES-A-CONFIRMER"
    assert absent["resultat"]["candidats"] == [] and absent["resultat"]["raison"] == "aucune_correspondance"
    assert "latitude" not in json.dumps(absent["resultat"])
    faible = _proposer(par_nom, "12 rue Lafleur, Repentigny")
    assert _code_refus(faible) == "REJ-COORDONNEES-A-CONFIRMER"
    assert faible["resultat"]["raison"] == "qualite_insuffisante"
    assert _etat() == avant


def test_index_non_importe_est_un_verdict_qui_dit_quoi_faire(par_nom):
    reponse = _proposer(par_nom)
    assert _code_refus(reponse) == "REJ-INDEX-RQA-ABSENT" and "importer" in reponse["resultat"]["verdict"]["detail"]


def test_adresse_illisible_est_jugee_avant_l_index(par_nom):
    assert _code_refus(_proposer(par_nom, {"numero_municipal": "1"})) == "REJ-CHAMP-MANQUANT"
    assert _code_refus(_proposer(par_nom, "n'importe quoi")) == "REJ-CONTRAT-INVALIDE"
    assert _code_refus(_proposer(par_nom, ADRESSE, chantier_id="  ")) == "REJ-CHAMP-VIDE"


def test_la_proposition_dit_ou_en_est_la_confirmation_sans_devoiler_les_coordonnees(par_nom, rqa_importe):
    assert _proposer(par_nom, chantier_id=CHANTIER)["resultat"]["confirmation_actuelle"] is None
    _resultat(_confirmer_rqa(par_nom))
    reponse = _proposer(par_nom, chantier_id=CHANTIER)
    actuelle = reponse["resultat"]["confirmation_actuelle"]
    assert (actuelle["version"], actuelle["action"], actuelle["source"], actuelle["confirme_par"]) == (
        1, "confirmee", "rqa", "admin.fictif")
    assert "coordonnees_chiffrees" not in actuelle and "empreinte_adresse" not in actuelle
    # La seule position de la réponse est la PROPOSITION de l'index ; la position confirmée n'y est pas lue.
    assert json.dumps(actuelle).count("microdegres") == 0
    # Sur un refus aussi, l'état de la confirmation est dit.
    refus = _proposer(par_nom, ADRESSE_INCONNUE, chantier_id=CHANTIER)
    assert refus["resultat"]["confirmation_actuelle"]["version"] == 1


# =========================================================================================
# 3. m4_confirmer_localisation : le maillon, chiffré, versionné
# =========================================================================================
def test_confirmation_rqa_par_l_admin_authentifie_est_tracee_et_horodatee_par_le_serveur(par_nom, rqa_importe):
    reponse = _confirmer_rqa(par_nom)
    accuse = _resultat(reponse)
    assert accuse["version"] == 1 and accuse["action"] == "confirmee" and accuse["source"] == "rqa"
    assert accuse["confirme_par"] == "admin.fictif" and accuse["precision"] == "batiment"
    # L'heure du SERVEUR fait foi ; celle de l'appareil (déréglée) est lisible à côté, jamais retenue.
    assert accuse["horodatage"] == RECU_LE.isoformat()
    assert accuse["horodatage_appareil"] == HORLOGE_APPAREIL_DEREGLEE.isoformat()
    [maillon] = _localisations()
    assert maillon["horodatage"] == RECU_LE.isoformat() and maillon["confirme_par"] == "admin.fictif"
    assert maillon["ligne_id"] == accuse["ligne_id"]
    # L'accusé (rejoué par l'idempotence d'appareil) ne porte ni coordonnées ni adresse.
    accuse_json = json.dumps(accuse, ensure_ascii=False).lower()
    for interdit in ("45741", "73450", "iberville", "repentigny", "latitude", "longitude"):
        assert interdit not in accuse_json
    # Une clé PAR CHANTIER dans le coffre du socle, à la portée de M4 pour les localisations.
    assert [(p, i) for p, i, _ in _cles()] == [(PORTEE, CHANTIER)]


def test_les_coordonnees_de_la_source_rqa_viennent_de_l_index_jamais_des_arguments(par_nom, rqa_importe):
    avant = _etat()
    reponse = _confirmer_rqa(par_nom, latitude_microdegres=45000000, longitude_microdegres=-73000000)
    assert _code_refus(reponse) == "REJ-CONTRAT-INVALIDE" and "jamais des arguments" in (
        reponse["resultat"]["verdict"]["detail"])
    assert _etat() == avant
    _resultat(_confirmer_rqa(par_nom))
    position, verdict = _lire()
    assert verdict is None
    assert (position["latitude_microdegres"], position["longitude_microdegres"]) == (45741000, -73450000)
    assert position["source"] == "rqa" and position["rqa_identifiant"] == "f001"
    assert position["rqa_version"] == "2026-09-01" and position["confirme_par"] == "admin.fictif"


def test_lecture_pour_le_solveur_hors_transaction_et_avec_verification_d_adresse(par_nom, rqa_importe):
    _resultat(_confirmer_rqa(par_nom))
    copie = registre_m4.Registre(_maillons())
    position, verdict = lire_localisation_confirmee(copie, CHANTIER)  # hors transaction : une lecture s'ouvre
    assert verdict is None and position["latitude_microdegres"] == 45741000
    position, verdict = lire_localisation_confirmee(copie, CHANTIER, "100 boul. Iberville, Repentigny")
    assert verdict is None and position["version"] == 1
    position, verdict = lire_localisation_confirmee(copie, CHANTIER, "102 boulevard Iberville, Repentigny")
    assert position is None and verdict["code"] == "REJ-COORDONNEES-A-CONFIRMER"
    position, verdict = lire_localisation_confirmee(copie, "C-JAMAIS-CONFIRME")
    assert position is None and verdict["code"] == "REJ-COORDONNEES-A-CONFIRMER"
    assert "coordonnées manquantes : à confirmer" in verdict["detail"]


def test_dernier_maillon_gagne_par_les_outils_et_l_historique_reste(par_nom, rqa_importe):
    _resultat(_confirmer_rqa(par_nom))
    avant = _etat()
    sans_motif = _confirmer(par_nom, MARIE, adresse=ADRESSE, source="manuel",
                            latitude_microdegres=45741500, longitude_microdegres=-73450500)
    assert _code_refus(sans_motif) == "REJ-CHAMP-VIDE"  # remplacer exige un motif
    assert _etat() == avant
    accuse = _resultat(_confirmer(
        par_nom, MARIE, adresse=ADRESSE, source="manuel", latitude_microdegres=45741500,
        longitude_microdegres=-73450500, motif="portail d'accès relevé sur place"))
    assert accuse["version"] == 2 and accuse["source"] == "manuel" and accuse["precision"] == "manuel"
    assert accuse["confirme_par"] == "marie.fictif"
    position, _ = _lire()
    assert (position["version"], position["latitude_microdegres"], position["longitude_microdegres"]) == (
        2, 45741500, -73450500)
    assert position["source"] == "manuel" and position["rqa_identifiant"] is None
    assert [m["version"] for m in _localisations()] == [1, 2]
    with stockage.transaction() as cnx:
        historique = localisation.historique(_registre(), CHANTIER, cles_chiffrement.lire(cnx, PORTEE, CHANTIER))
    assert [(h["version"], h["source"], h["confirme_par"]) for h in historique] == [
        (1, "rqa", "admin.fictif"), (2, "manuel", "marie.fictif")]
    assert historique[0]["position"]["latitude_microdegres"] == 45741000
    assert historique[1]["position"]["latitude_microdegres"] == 45741500
    assert len(_cles()) == 1 and _cles() == avant[1]  # la même clé pour tout le chantier
    with stockage.transaction():
        assert _registre().valider_chaine() is True


def test_retirer_par_l_outil_ramene_le_chantier_a_a_confirmer(par_nom, rqa_importe):
    _resultat(_confirmer_rqa(par_nom))
    avant = _etat()
    assert _code_refus(_confirmer(par_nom, action="retiree")) == "REJ-CHAMP-VIDE"
    assert _etat() == avant
    accuse = _resultat(_confirmer(par_nom, action="retiree", motif="adresse corrigée au dossier"))
    assert accuse["version"] == 2 and accuse["action"] == "retiree" and accuse["source"] is None
    position, verdict = _lire()
    assert position is None and verdict["code"] == "REJ-COORDONNEES-A-CONFIRMER" and "retirée" in verdict["detail"]
    assert _proposer(par_nom, chantier_id=CHANTIER)["resultat"]["confirmation_actuelle"]["action"] == "retiree"


def test_doublon_departage_par_l_humain_qui_choisit_un_identifiant(par_nom, rqa_importe):
    adresse = "30 rue Principale, Saint-Paul"
    assert _code_refus(_proposer(par_nom, adresse)) == "REJ-COORDONNEES-A-CONFIRMER"
    _resultat(_confirmer_rqa(par_nom, adresse=adresse, identifiant="f012"))
    position, _ = _lire()
    assert (position["latitude_microdegres"], position["longitude_microdegres"]) == (47000000, -72000000)


def test_position_faible_confirmee_avec_motif_garde_sa_precision(par_nom, rqa_importe):
    adresse = "12 rue Lafleur, Repentigny"
    avant = _etat()
    assert _code_refus(_confirmer_rqa(par_nom, adresse=adresse, identifiant="f008")) == "REJ-CHAMP-VIDE"
    assert _etat() == avant
    accuse = _resultat(_confirmer_rqa(
        par_nom, adresse=adresse, identifiant="f008", motif="vérifié sur place avec le client"))
    assert accuse["precision"] == "geocodee"
    assert _lire()[0]["precision"] == "geocodee"


# -- effacement cryptographique --------------------------------------------------------------------
def test_cle_detruite_position_illisible_chaine_valide_puis_nouvelle_periode(par_nom, rqa_importe):
    _resultat(_confirmer_rqa(par_nom))
    _resultat(_confirmer(par_nom, adresse=ADRESSE, source="manuel", latitude_microdegres=45741500,
                         longitude_microdegres=-73450500, motif="correction"))
    maillons_avant = _maillons()
    with stockage.transaction() as cnx:
        tete = _registre().tete()
        assert cles_chiffrement.detruire(cnx, PORTEE, CHANTIER) is True  # l'effacement lui-même
    position, verdict = _lire()
    assert position is None and verdict["code"] == "REJ-LOCALISATION-DETRUITE"
    assert _cles() == []
    # Le registre n'a pas bougé d'un octet et sa chaîne est toujours valide ; l'historique se lit encore.
    assert _maillons() == maillons_avant
    with stockage.transaction():
        assert _registre().tete() == tete and _registre().valider_chaine() is True
        historique = localisation.historique(_registre(), CHANTIER, None)
    assert [(h["version"], h["confirme_par"], h["position"]) for h in historique] == [
        (1, "admin.fictif", None), (2, "admin.fictif", None)]
    actuelle = _proposer(par_nom, chantier_id=CHANTIER)["resultat"]["confirmation_actuelle"]
    assert actuelle["version"] == 2  # les métadonnées restent
    # Une nouvelle confirmation ouvre une période neuve : nouvelle clé, seul le nouveau maillon est lisible.
    _resultat(_confirmer(par_nom, adresse=ADRESSE, source="manuel", latitude_microdegres=45742000,
                         longitude_microdegres=-73451000, motif="reconfirmée après effacement"))
    position, verdict = _lire()
    assert verdict is None and position["version"] == 3 and position["latitude_microdegres"] == 45742000
    with stockage.transaction() as cnx:
        historique = localisation.historique(_registre(), CHANTIER, cles_chiffrement.lire(cnx, PORTEE, CHANTIER))
    assert [h["position"] is not None for h in historique] == [False, False, True]
    with stockage.transaction():
        assert _registre().valider_chaine() is True


# =========================================================================================
# 4. Rien de lisible dans la base : ni adresse, ni coordonnées
# =========================================================================================
def test_ni_adresse_ni_coordonnees_en_clair_dans_les_octets_de_la_base(par_nom, rqa_importe, instance):
    _resultat(_proposer(par_nom, chantier_id=CHANTIER))
    _resultat(_confirmer_rqa(par_nom))
    _resultat(_confirmer(par_nom, adresse=ADRESSE, source="manuel", latitude_microdegres=45741500,
                         longitude_microdegres=-73450500, motif="correction"))
    _resultat(_confirmer(par_nom, action="retiree", motif="test"))
    stockage.liberer()  # ferme les connexions : tout est écrit dans le fichier
    octets = b""
    for fichier in instance.glob("opsys.db*"):
        octets += fichier.read_bytes()
    assert CHANTIER.encode() in octets  # la lecture porte bien sur la base de cette instance
    assert b"localisation_chantier" in octets and b"coordonnees_chiffrees" in octets
    for interdit in (b"Iberville", b"iberville", b"Repentigny", b"boulevard", b"45741000", b"-73450000",
                     b"45741500", b"-73450500", b"45.741", b"J5Y1A1", b"Notre-Dame"):
        assert interdit not in octets, interdit


def test_la_trace_de_validation_au_depart_masque_l_adresse_et_les_coordonnees_saisies(instance):
    arguments = {
        "chantier_id": CHANTIER, "action": "confirmee", "horodatage": "2025-06-02T09:00:00+00:00",
        "confirme_par": "admin.fictif", "adresse": ADRESSE, "source": "manuel",
        "latitude_microdegres": 45741500, "longitude_microdegres": -73450500, "rqa_identifiant": None,
        "motif": "relevé sur place",
    }
    with stockage.transaction() as cnx:
        ident = approbations.tracer_validation_au_depart(
            cnx, "m04-field-ops", "m4_confirmer_localisation", arguments, niveau=Niveau.N3, signataire=ADMIN,
            reponse={"ok": True, "resultat": {"accepte": True}})
        trace = next(d for d in approbations.lister(cnx) if d["id"] == ident)["arguments"]
    for masque in ("adresse", "latitude_microdegres", "longitude_microdegres"):
        assert trace[masque] == approbations.VALEUR_MASQUEE, masque
    assert trace["chantier_id"] == CHANTIER and trace["confirme_par"] == "admin.fictif"
    assert trace["rqa_identifiant"] is None and trace["motif"] == "relevé sur place"
    assert "Iberville" not in json.dumps(trace) and "45741500" not in json.dumps(trace)


# =========================================================================================
# 5. Contrôle d'accès : qui peut confirmer, et sous quel nom
# =========================================================================================
@pytest.mark.parametrize("appelant", [MARC, VENDEUR])
def test_un_employe_ou_un_vendeur_est_refuse_par_les_deux_outils_sans_rien_ecrire(par_nom, rqa_importe, appelant):
    avant = _etat()
    reponse = _confirmer_rqa(par_nom, appelant)
    assert _code_refus(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert "sans portée" in reponse["resultat"]["verdict"]["detail"]
    assert _code_refus(_proposer(par_nom, ADRESSE, appelant)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _etat() == avant and _cles() == []  # aucune écriture, aucune clé créée


def test_un_admin_ne_peut_pas_confirmer_sous_le_nom_d_un_autre(par_nom, rqa_importe):
    avant = _etat()
    reponse = _confirmer_rqa(par_nom, ADMIN, confirme_par="marie.fictif")
    assert _code_refus(reponse) == "REJ-IDENTITE-FOURNIE-DIFFERENTE"
    assert _etat() == avant  # refusé, jamais remplacé en silence par la personne authentifiée
    accuse = _resultat(_confirmer_rqa(par_nom, ADMIN))
    assert accuse["confirme_par"] == "admin.fictif"


def test_une_personne_inconnue_ou_desactivee_ne_confirme_rien(par_nom, rqa_importe):
    avant = _etat()
    assert _code_refus(_confirmer_rqa(par_nom, FANTOME)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _code_refus(_proposer(par_nom, ADRESSE, FANTOME)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _etat() == avant


def test_un_appel_d_agent_sans_identite_garde_ses_arguments(par_nom, rqa_importe):
    accuse = _resultat(_confirmer_rqa(
        par_nom, None, confirme_par="agent.fictif", horodatage="2026-09-28T10:00:00+00:00"))
    assert accuse["confirme_par"] == "agent.fictif" and accuse["horodatage"] == "2026-09-28T10:00:00+00:00"
    assert "horodatage_appareil" not in accuse  # aucun appel d'appareil : pas d'horloge d'appareil
    assert _resultat(_proposer(par_nom, ADRESSE, None))["rqa_identifiant"] == "f001"


# =========================================================================================
# 6. Aucune écriture sur refus, aucune clé créée
# =========================================================================================
@pytest.mark.parametrize("arguments", [
    {"action": "confirmee"},                                                                # ni adresse ni source
    {"action": "confirmee", "adresse": ADRESSE},                                             # pas de source
    {"action": "confirmee", "adresse": ADRESSE, "source": "manuel"},                         # pas de coordonnées
    {"action": "confirmee", "adresse": ADRESSE, "source": "manuel",
     "latitude_microdegres": -73450000, "longitude_microdegres": 45741000},                  # inversées
    {"action": "confirmee", "adresse": ADRESSE, "source": "rqa"},                            # pas d'identifiant
    {"action": "confirmee", "adresse": ADRESSE, "source": "rqa", "rqa_identifiant": "nexiste-pas"},
    {"action": "confirmee", "adresse": ADRESSE, "source": "rqa", "rqa_identifiant": "f003"},  # autre immeuble
    {"action": "confirmee", "adresse": "illisible", "source": "rqa", "rqa_identifiant": "f001"},
    {"action": "confirmee", "adresse": ADRESSE_INCONNUE, "source": "rqa", "rqa_identifiant": "f001"},
    {"action": "retiree", "motif": "rien à retirer"},                                        # rien de confirmé
    {"action": "confirmee", "adresse": "12 rue Lafleur, Repentigny", "source": "rqa", "rqa_identifiant": "f008"},
])
def test_un_refus_ne_laisse_ni_maillon_ni_cle(par_nom, rqa_importe, arguments):
    avant = _etat()
    reponse = _confirmer(par_nom, **arguments)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    assert reponse["resultat"]["verdict"]["code"].startswith("REJ-")
    assert _etat() == avant and _cles() == []


def test_schema_des_arguments_refuse_un_champ_inconnu_ou_un_type_faux(par_nom, rqa_importe):
    avant = _etat()
    reponse = _appeler(par_nom, "m4_confirmer_localisation", {
        "chantier_id": CHANTIER, "action": "confirmee", "horodatage": HORODATAGE_ARGUMENT,
        "confirme_par": "admin.fictif", "latitude": 45.7}, ADMIN)
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    reponse = _appeler(par_nom, "m4_confirmer_localisation", {
        "chantier_id": CHANTIER, "action": "effacer", "horodatage": HORODATAGE_ARGUMENT,
        "confirme_par": "admin.fictif"}, ADMIN)
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    reponse = _appeler(par_nom, "m4_confirmer_localisation", {
        "chantier_id": CHANTIER, "action": "confirmee", "horodatage": HORODATAGE_ARGUMENT,
        "confirme_par": "admin.fictif", "adresse": ADRESSE, "source": "manuel",
        "latitude_microdegres": 45.741, "longitude_microdegres": -73.45}, ADMIN)
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"  # des degrés, pas des microdegrés
    assert _etat() == avant


def test_sans_base_durable_la_confirmation_est_refusee_jamais_ecrite_en_clair(rqa_importe, instance):
    registre_memoire = registre_m4.Registre()
    par_nom_memoire = {o.nom: o for o in outils(registre_memoire)}
    reponse = executer_atomique(par_nom_memoire["m4_confirmer_localisation"], {
        "chantier_id": CHANTIER, "action": "confirmee", "horodatage": HORODATAGE_ARGUMENT,
        "confirme_par": "agent.fictif", "adresse": ADRESSE, "source": "rqa", "rqa_identifiant": "f001"})
    assert _code_refus(reponse) == "REJ-CONTRAT-INVALIDE" and "clé de chiffrement" in (
        reponse["resultat"]["verdict"]["detail"])
    assert registre_memoire.taille() == 0 and _cles() == []


def test_confirmation_sans_index_importe_par_la_source_manuelle_seulement(par_nom):
    # Aucun RQA importé : la source rqa dit quoi faire ; la saisie manuelle reste possible, marquée manuel.
    reponse = _confirmer_rqa(par_nom)
    assert _code_refus(reponse) == "REJ-INDEX-RQA-ABSENT" and _cles() == []
    accuse = _resultat(_confirmer(par_nom, adresse=ADRESSE, source="manuel",
                                  latitude_microdegres=45741500, longitude_microdegres=-73450500))
    assert accuse["source"] == "manuel"


# =========================================================================================
# 7. Aucun accès réseau, de bout en bout
# =========================================================================================
def test_de_l_import_a_la_confirmation_aucun_socket_n_est_ouvert(instance, sockets_bloques):
    with pytest.raises(AssertionError, match="accès réseau interdit"):
        socket.getaddrinfo("example.org", 443)
    localisation.importer_rqa(
        DONNEES, stockage.dossier_opsys() / localisation.SOUS_DOSSIER_INDEX / localisation.NOM_FICHIER_INDEX)
    par_nom = {o.nom: o for o in outils()}
    assert _resultat(_proposer(par_nom))["rqa_identifiant"] == "f001"
    assert _code_refus(_proposer(par_nom, ADRESSE_INCONNUE)) == "REJ-COORDONNEES-A-CONFIRMER"
    _resultat(_confirmer_rqa(par_nom))
    position, verdict = _lire()
    assert verdict is None and position["latitude_microdegres"] == 45741000
