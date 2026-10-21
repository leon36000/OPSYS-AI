"""Parcours synthétique des déclarations paie/DAS privées."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from opsys import cles_chiffrement, identite, stockage
from opsys.console import obligations_privees
from opsys.stockage.schema import JOURNAL, REGISTRES

_TESTS = Path(__file__).resolve().parents[1] / "tests"
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import test_console_paie as paie_test  # noqa: E402
from test_console_paie import OWNER, PASSWORD, _connecter, _csrf  # noqa: E402

client_paie = paie_test.client_paie

FICTIF = True
PATH = "/finance/paie/obligations"
FINANCE = "finance-paie-fictif"
FINANCE_PASSWORD = "finance-paie-fictif-password"


def _form(csrf: str, *, revision="0", mutation_id="a" * 32):
    return {
        "type": "paies",
        "montant_cad": "1250.00",
        "periode_debut": "2026-09-01",
        "periode_fin": "2026-09-15",
        "date_paie": "2026-09-18",
        "echeance": "2026-09-21",
        "reference_piece": "pièce-fictive-01",
        "autorite": "Source déclarée fictive",
        "source_consultee_le": "2026-09-17",
        "applicable_du": "2026-01-01",
        "applicable_au": "2026-12-31",
        "version": "2026-déclarée",
        "revision_attendue": revision,
        "mutation_id": mutation_id,
        "csrf": csrf,
    }


def _chaine():
    return list(stockage.maillons("m05-financecore", "obligations_paies_das_privees"))


def test_saisie_privee_chiffree_rejeu_cas_et_confidentialite(client_paie, session):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    assert client.get(PATH + "?montant=1250").status_code == 400
    assert client.post(PATH, data=_form("faux")).status_code == 403
    sans_csrf = _form(csrf)
    sans_csrf.pop("csrf")
    assert client.post(PATH, data=sans_csrf).status_code == 400
    extra = _form(csrf)
    extra["acteur"] = OWNER
    assert client.post(PATH, data=extra).status_code == 400
    assert client.post(PATH + "?acteur=autre", data=_form(csrf)).status_code == 400
    with session() as cnx:
        mouvements_avant = cnx.execute(
            select(func.count()).select_from(REGISTRES).where(
                (REGISTRES.c.departement == "m05-financecore") & (REGISTRES.c.registre == "principal")
            )
        ).scalar_one()

    premier = client.post(PATH, data=_form(csrf), follow_redirects=True)
    assert premier.status_code == 200, premier.text
    assert "1250.00" in premier.text and "pièce-fictive-01" in premier.text
    assert "Aucune paie nette" in premier.text
    chaine = _chaine()
    assert len(chaine) == 1
    clair = json.dumps(chaine[0], ensure_ascii=False)
    assert "1250.00" not in clair and "pièce-fictive-01" not in clair
    assert chaine[0]["ciphertext"] and chaine[0]["cipher_sha256"]

    # Le rejeu de la même mutation reste idempotent, même avec l'ancien snapshot.
    rejoue = client.post(PATH, data=_form(csrf), follow_redirects=True)
    assert rejoue.status_code == 200 and len(_chaine()) == 1
    altere = _form(csrf)
    altere["montant_cad"] = "1251.00"
    assert client.post(PATH, data=altere).status_code == 409
    # Une mutation différente avec l'ancien snapshot échoue en CAS et ne perd pas la première entrée.
    conflit = client.post(PATH, data=_form(csrf, mutation_id="b" * 32), follow_redirects=True)
    assert conflit.status_code == 409 and len(_chaine()) == 1

    with session() as cnx:
        ligne = cnx.execute(
            select(REGISTRES.c.maillon).where(
                (REGISTRES.c.departement == "m05-financecore")
                & (REGISTRES.c.registre == "obligations_paies_das_privees")
            )
        ).scalar_one()
        journal = cnx.execute(select(JOURNAL.c.details)).scalars().all()
    assert "1250.00" not in ligne and "pièce-fictive-01" not in ligne
    assert all("1250.00" not in detail and "pièce-fictive-01" not in detail for detail in journal)
    with session() as cnx:
        mouvements_apres = cnx.execute(
            select(func.count()).select_from(REGISTRES).where(
                (REGISTRES.c.departement == "m05-financecore") & (REGISTRES.c.registre == "principal")
            )
        ).scalar_one()
    assert mouvements_apres == mouvements_avant


def test_role_retire_avant_append_refuse(client_paie, session):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    with session() as cnx:
        identite.retirer_role(cnx, OWNER, "nathan_owner")
    retour = client.post(PATH, data=_form(csrf))
    assert retour.status_code == 403
    assert _chaine() == []


def test_role_revoque_pendant_chiffrement_revalide_juste_avant_append(client_paie, monkeypatch):
    client = _connecter(client_paie)
    csrf = _csrf(client)

    class AESGCMFictif:
        def __init__(self, _cle):
            pass

        def encrypt(self, _nonce, _clair, _aad):
            cnx = stockage.connexion_courante()
            assert cnx is not None
            identite.retirer_role(cnx, OWNER, "nathan_owner")
            return b"x" * 32

    monkeypatch.setattr(obligations_privees, "_aead", lambda: AESGCMFictif)
    retour = client.post(PATH, data=_form(csrf))
    assert retour.status_code == 403
    assert _chaine() == []


def test_droit_revalide_apres_dechiffrement_avant_reponse(client_paie, session, monkeypatch):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    assert client.post(PATH, data=_form(csrf), follow_redirects=True).status_code == 200
    lire_original = obligations_privees.lire

    def lire_puis_revoquer(cnx):
        resultat = lire_original(cnx)
        identite.retirer_role(cnx, OWNER, "nathan_owner")
        return resultat

    monkeypatch.setattr(obligations_privees, "lire", lire_puis_revoquer)
    retour = client.get(PATH)
    assert retour.status_code == 403
    assert "1250.00" not in retour.text


def test_finance_actif_peut_lire_et_confirmer(client_paie, session):
    with session() as cnx:
        identite.creer_personne(cnx, FINANCE, "Finance fictive", FINANCE_PASSWORD, ["finance"])
    client = _connecter(client_paie, FINANCE, FINANCE_PASSWORD)
    assert client.get(PATH).status_code == 200
    csrf = _csrf(client)
    retour = client.post(PATH, data=_form(csrf), follow_redirects=True)
    assert retour.status_code == 200 and "1250.00" in retour.text
    assert len(_chaine()) == 1


def test_xss_dans_reference_est_echappe(client_paie):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    formulaire = _form(csrf)
    formulaire["reference_piece"] = '<script>alert("fictif")</script>'
    retour = client.post(PATH, data=formulaire, follow_redirects=True)
    assert retour.status_code == 200
    assert '<script>alert("fictif")</script>' not in retour.text
    assert "&lt;script&gt;" in retour.text


def test_rejeu_refuse_acteur_et_revision_differents(client_paie, session):
    client = _connecter(client_paie)
    csrf_owner = _csrf(client)
    original = _form(csrf_owner, mutation_id="c" * 32)
    assert client.post(PATH, data=original, follow_redirects=True).status_code == 200
    with session() as cnx:
        identite.creer_personne(cnx, FINANCE, "Finance fictive", FINANCE_PASSWORD, ["finance"])
    _connecter(client, FINANCE, FINANCE_PASSWORD)
    assert client.post(PATH, data=_form(_csrf(client), mutation_id="c" * 32)).status_code == 409

    client_owner = _connecter(client, OWNER, PASSWORD)
    csrf_owner = _csrf(client_owner)
    assert client_owner.post(
        PATH, data=_form(csrf_owner, revision="1", mutation_id="d" * 32), follow_redirects=True
    ).status_code == 200
    revision_changee = _form(csrf_owner, revision="2", mutation_id="d" * 32)
    assert client_owner.post(PATH, data=revision_changee).status_code == 409


def test_admin_sans_role_finance_ne_peut_pas_lire_ni_ecrire(client_paie):
    client = _connecter(client_paie, "admin-paie-fictif", "admin-paie-password")
    assert client.get(PATH).status_code == 403
    assert client.post(PATH, data=_form(_csrf(client))).status_code == 403
    assert _chaine() == []


def test_chiffrement_altéré_refuse_toute_lecture(client_paie):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    assert client.post(PATH, data=_form(csrf), follow_redirects=True).status_code == 200
    with stockage.transaction() as cnx:
        env = _chaine()[0]
        cipher = bytes.fromhex(env["ciphertext"])
        env["ciphertext"] = bytes([cipher[0] ^ 1, *cipher[1:]]).hex()
        env["cipher_sha256"] = hashlib.sha256(bytes.fromhex(env["ciphertext"])).hexdigest()
        cnx.execute(
            update(REGISTRES).where(
                (REGISTRES.c.departement == "m05-financecore")
                & (REGISTRES.c.registre == "obligations_paies_das_privees")
                & (REGISTRES.c.rang == 0)
            ).values(maillon=json.dumps(env, separators=(",", ":")))
        )
    retour = client.get(PATH)
    assert retour.status_code == 409
    assert "1250.00" not in retour.text


def test_cle_detruite_refuse_le_calendrier(client_paie, session):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    assert client.post(PATH, data=_form(csrf), follow_redirects=True).status_code == 200
    with session() as cnx:
        assert cles_chiffrement.detruire(cnx, "m05/obligations-paies-das", "a" * 32)
    retour = client.get(PATH)
    assert retour.status_code == 409
    assert "1250.00" not in retour.text
    with session() as cnx:
        assert cles_chiffrement.lire(cnx, "m05/obligations-paies-das", "a" * 32) is None


def test_plafond_registre_refuse_avant_iteration_ou_dechiffrement(session, monkeypatch):
    class RegistreSurdimensionne:
        def __len__(self):
            return obligations_privees.MAX_ENTREES + 1

        def __iter__(self):
            raise AssertionError("aucune matérialisation au-delà du plafond")

    def dechiffrement_interdit():
        raise AssertionError("aucun déchiffrement après dépassement du plafond")

    monkeypatch.setattr(obligations_privees.stockage, "maillons", lambda *_args: RegistreSurdimensionne())
    monkeypatch.setattr(obligations_privees, "_aead", dechiffrement_interdit)
    with session() as cnx, pytest.raises(obligations_privees.RefusObligation, match="volumineux"):
        obligations_privees.lire(cnx)


def test_corps_ferme_et_fenetre_incoherente_refuses(client_paie):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    incomplet = _form(csrf)
    incomplet.pop("autorite")
    assert client.post(PATH, data=incomplet).status_code == 400
    hors_fenetre = _form(csrf)
    hors_fenetre["applicable_au"] = "2026-09-17"
    assert client.post(PATH, data=hors_fenetre).status_code == 409
    assert _chaine() == []


def _transition_form(csrf: str, *, action, target="a" * 32, revision="1", mutation_id="b" * 32):
    form = _form(csrf, revision=revision, mutation_id=mutation_id)
    form.update({
        "action": action,
        "cible_id": target,
        "reglee_le": "2026-09-22" if action == "REGLER" else "",
    })
    return form


def test_cycle_remplacement_preserve_historique_et_rejeu(client_paie):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    assert client.post(PATH, data=_form(csrf), follow_redirects=True).status_code == 200
    avant = _chaine()
    remplacement = _transition_form(csrf, action="REMPLACER")
    remplacement["montant_cad"] = "1300.00"
    remplacement["reference_piece"] = "correction-fictive"
    retour = client.post(PATH + "/transition", data=remplacement, follow_redirects=True)
    assert retour.status_code == 200, retour.text
    assert len(_chaine()) == 2
    assert "REMPLACEE" in retour.text and "ACTIVE" in retour.text
    assert "1300.00" in retour.text and "correction-fictive" in retour.text
    assert "1250.00" in retour.text
    assert _chaine()[0] == avant[0]
    rejoue = client.post(PATH + "/transition", data=remplacement, follow_redirects=True)
    assert rejoue.status_code == 200 and len(_chaine()) == 2


def test_cycle_reglement_est_declaration_humaine_et_references_strictes(client_paie):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    assert client.post(PATH, data=_form(csrf), follow_redirects=True).status_code == 200
    invalide = _transition_form(csrf, action="REGLER", mutation_id="c" * 32)
    invalide["periode_fin"] = "2026-09-14"
    assert client.post(PATH + "/transition", data=invalide).status_code == 409
    montant_incoherent = _transition_form(csrf, action="REGLER", mutation_id="9" * 32)
    montant_incoherent["montant_cad"] = "1.00"
    assert client.post(PATH + "/transition", data=montant_incoherent).status_code == 409
    absent = _transition_form(csrf, action="REGLER", target="f" * 32, mutation_id="d" * 32)
    assert client.post(PATH + "/transition", data=absent).status_code == 409
    reglement = _transition_form(csrf, action="REGLER", mutation_id="e" * 32)
    retour = client.post(PATH + "/transition", data=reglement, follow_redirects=True)
    assert retour.status_code == 200, retour.text
    assert "REGLEMENT_DECLARE_NON_RAPPROCHE" in retour.text
    assert "déclaration humaine, non rapprochée" in retour.text
    assert "Aucune paie nette" in retour.text
    assert "Réserves utilisables : INCONNU" in retour.text
    assert len(_chaine()) == 2
    second = _transition_form(csrf, action="REGLER", revision="2", mutation_id="f" * 32)
    assert client.post(PATH + "/transition", data=second).status_code == 409
    assert len(_chaine()) == 2


def test_transition_refuse_rbac_csrf_et_conserve_chiffrement(client_paie):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    assert client.post(PATH, data=_form(csrf), follow_redirects=True).status_code == 200
    mutation = _transition_form(csrf, action="REGLER")
    csrf_invalide = dict(mutation)
    csrf_invalide["csrf"] = "jeton-fictif-invalide"
    assert client.post(PATH + "/transition", data=csrf_invalide).status_code == 403
    assert client.post(PATH + "/transition?x=1", data=mutation).status_code == 400
    ciphertexts = _chaine()
    assert len(ciphertexts) == 1 and "1250.00" not in json.dumps(ciphertexts)
    client.post(PATH + "/transition", data=mutation)
    assert len(_chaine()) == 2
    assert all("1250.00" not in json.dumps(env) for env in _chaine())


def test_evenement_cycle_cle_detruite_refuse_lecture_sans_montant(client_paie, session):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    assert client.post(PATH, data=_form(csrf), follow_redirects=True).status_code == 200
    assert client.post(
        PATH + "/transition",
        data=_transition_form(csrf, action="REGLER"),
        follow_redirects=True,
    ).status_code == 200
    with session() as cnx:
        assert cles_chiffrement.detruire(cnx, "m05/obligations-paies-das", "b" * 32)
    retour = client.get(PATH)
    assert retour.status_code == 409
    assert "1250.00" not in retour.text


def test_transition_revalide_role_apres_chiffrement(client_paie, monkeypatch):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    assert client.post(PATH, data=_form(csrf), follow_redirects=True).status_code == 200

    aesgcm_reel = obligations_privees._aead()

    class AESGCMFictif:
        def __init__(self, cle):
            self._aesgcm = aesgcm_reel(cle)

        def decrypt(self, nonce, cipher, aad):
            return self._aesgcm.decrypt(nonce, cipher, aad)

        def encrypt(self, nonce, clair, aad):
            cipher = self._aesgcm.encrypt(nonce, clair, aad)
            cnx = stockage.connexion_courante()
            assert cnx is not None
            identite.retirer_role(cnx, OWNER, "nathan_owner")
            return cipher

    monkeypatch.setattr(obligations_privees, "_aead", lambda: AESGCMFictif)
    retour = client.post(PATH + "/transition", data=_transition_form(csrf, action="REGLER"))
    assert retour.status_code == 403
    assert len(_chaine()) == 1


def test_chaine_evenement_alteree_refuse_lecture(client_paie):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    assert client.post(PATH, data=_form(csrf), follow_redirects=True).status_code == 200
    assert client.post(
        PATH + "/transition",
        data=_transition_form(csrf, action="REGLER"),
        follow_redirects=True,
    ).status_code == 200
    with stockage.transaction() as cnx:
        env = _chaine()[1]
        env["precedent_sha256"] = "0" * 64
        cnx.execute(
            update(REGISTRES).where(
                (REGISTRES.c.departement == "m05-financecore")
                & (REGISTRES.c.registre == "obligations_paies_das_privees")
                & (REGISTRES.c.rang == 1)
            ).values(maillon=json.dumps(env, separators=(",", ":")))
        )
    retour = client.get(PATH)
    assert retour.status_code == 409
    assert "1250.00" not in retour.text


def test_transition_rejeu_refuse_cible_revision_acteur_et_charge_alteres(client_paie, session):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    assert client.post(PATH, data=_form(csrf), follow_redirects=True).status_code == 200
    originale = _transition_form(csrf, action="REMPLACER")
    originale["montant_cad"] = "1300.00"
    assert client.post(PATH + "/transition", data=originale, follow_redirects=True).status_code == 200
    assert client.post(PATH + "/transition", data=originale, follow_redirects=True).status_code == 200
    nombre = len(_chaine())

    cible_modifiee = dict(originale)
    cible_modifiee["cible_id"] = "f" * 32
    assert client.post(PATH + "/transition", data=cible_modifiee).status_code == 409
    charge_modifiee = dict(originale)
    charge_modifiee["montant_cad"] = "1400.00"
    assert client.post(PATH + "/transition", data=charge_modifiee).status_code == 409
    revision_modifiee = dict(originale)
    revision_modifiee["revision_attendue"] = "2"
    assert client.post(PATH + "/transition", data=revision_modifiee).status_code == 409

    with session() as cnx:
        identite.creer_personne(cnx, FINANCE, "Finance fictive", FINANCE_PASSWORD, ["finance"])
    autre = _connecter(client, FINANCE, FINANCE_PASSWORD)
    acteur_modifie = dict(originale)
    acteur_modifie["csrf"] = _csrf(autre)
    assert autre.post(PATH + "/transition", data=acteur_modifie).status_code == 409
    assert len(_chaine()) == nombre


def test_transition_reglement_refuse_dates_futures_ou_anterieures(client_paie):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    assert client.post(PATH, data=_form(csrf), follow_redirects=True).status_code == 200
    futur = _transition_form(csrf, action="REGLER")
    futur["reglee_le"] = "2099-01-01"
    assert client.post(PATH + "/transition", data=futur).status_code == 409
    avant_paie = _transition_form(csrf, action="REGLER")
    avant_paie["reglee_le"] = "2026-09-17"
    assert client.post(PATH + "/transition", data=avant_paie).status_code == 409
    assert len(_chaine()) == 1


def test_remplacement_chaine_et_relecture_semantique_avant_creation(client_paie, session, monkeypatch):
    client = _connecter(client_paie)
    csrf = _csrf(client)
    assert client.post(PATH, data=_form(csrf), follow_redirects=True).status_code == 200
    replacement = _transition_form(csrf, action="REMPLACER", mutation_id="b" * 32)
    replacement["montant_cad"] = "1300.00"
    assert client.post(PATH + "/transition", data=replacement, follow_redirects=True).status_code == 200
    next_replacement = _transition_form(csrf, action="REMPLACER", target="b" * 32,
                                        revision="2", mutation_id="c" * 32)
    next_replacement["montant_cad"] = "1350.00"
    retour = client.post(PATH + "/transition", data=next_replacement, follow_redirects=True)
    assert retour.status_code == 200 and "1350.00" in retour.text
    assert len(_chaine()) == 3

    verifier_original = obligations_privees._verifier_lire_brut

    def corrompre_semantiquement(cnx, enveloppes):
        events = verifier_original(cnx, enveloppes)
        events.append({"action": "REGLER", "id": "d" * 32, "cible_id": "e" * 32,
                       "obligation": events[0]["obligation"], "reglee_le": "2026-09-22",
                       "confirme_par": OWNER, "confirme_le": "2026-10-03T00:00:00+00:00"})
        return events

    monkeypatch.setattr(obligations_privees, "_verifier_lire_brut", corrompre_semantiquement)
    payload = _form(csrf, revision="3", mutation_id="e" * 32)
    with stockage.transaction() as cnx, pytest.raises(obligations_privees.RefusObligation):
        obligations_privees.ajouter(
            cnx, {key: payload[key] for key in obligations_privees.CHAMPS}, revision_attendue=3,
            mutation_id="e" * 32, confirme_par=OWNER, confirme_le="2026-10-03T00:00:00+00:00",
            verifier_acteur=lambda *_args: None,
        )
    assert len(_chaine()) == 3
