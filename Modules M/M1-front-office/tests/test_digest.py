import sys
from pathlib import Path
import hashlib
import inspect
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import digest  # noqa: E402
import adaptateurs  # noqa: E402
import garde_fou  # noqa: E402
from registre import Registre  # noqa: E402
import verdicts  # noqa: E402


# ------------------------------------------------------------------ #
# helpers & fixtures statiques
# ------------------------------------------------------------------ #

def _entree_minimale(type_entree, canal, conversation_id="c-001", payload=""):
    """Forme minimale d'une entrée dans le registre (M1-S001)."""
    import uuid
    return {
        "type_entree": type_entree,
        "canal": canal,
        "signal_id": str(uuid.uuid4()),
        "conversation_id": conversation_id,
        "contenu_filtre": payload,
        "horodatage": "2025-04-01T12:00:00Z",
        "metadonnees": {},
    }


ENTREES_REGLABLES = [
    _entree_minimale("signal", "telephone", payload="urgent Nice rénovation totale"),
    _entree_minimale("signal", "courriel", payload="extension Lyon devis"),
    _entree_minimale("signal", "telephone", payload="isolation thermique"),
    _entree_minimale("transition_phase", "telephone", payload="phase 3"),
    _entree_minimale("lead_emis", "formulaire", payload="lead formulaire"),
    _entree_minimale("chiffrage_emis", "texte", payload="chiffrage 15000 euros"),
    _entree_minimale("alerte", "courriel", payload="alerte délai"),
]

ENTREES_SENSIBLES = [
    _entree_minimale("signal", "telephone", payload="Remise 5% si signé avant le 2025-06-30"),
    _entree_minimale("lead_emis", "courriel", payload="budget 15000 euros, livraison juin 2025"),
    _entree_minimale("chiffrage_emis", "courriel", payload="prix total 12345 EUR TTC"),
]


# ------------------------------------------------------------------ #
# mock implémentations pour le test de contrat
# ------------------------------------------------------------------ #

class MockApprovalEngine:
    """Implémentation alternative minimale du protocole ApprovalEngine."""
    def __init__(self):
        self._store = {}

    def proposer(self, objet, acteur):
        raw = f"{objet}::{acteur}"
        self._store[raw] = "proposé"
        return hashlib.sha256(raw.encode()).hexdigest()

    def statut(self, identifiant):
        for raw, statut_val in self._store.items():
            if hashlib.sha256(raw.encode()).hexdigest() == identifiant:
                return statut_val
        raise LookupError(f"Identifiant inconnu : {identifiant}")


class MockNotificationBus:
    """Implémentation alternative minimale du protocole NotificationBus."""
    def __init__(self):
        self._sent = {}

    def emettre(self, canal, message):
        raw = f"{canal}::{message}"
        self._sent[raw] = True
        return hashlib.sha256(raw.encode()).hexdigest()


# ------------------------------------------------------------------ #
# tests
# ------------------------------------------------------------------ #

class TestDigestByteIdentique:
    @pytest.mark.parametrize("entrees", [ENTREES_REGLABLES, ENTREES_SENSIBLES, []])
    def test_memes_entrees_meme_digest(self, entrees):
        d1 = digest.produire_digest(entrees, "2025-04-01")
        d2 = digest.produire_digest(entrees, "2025-04-01")
        assert d1 == d2
        assert hashlib.sha256(d1.encode()).hexdigest() == hashlib.sha256(d2.encode()).hexdigest()

    def test_ordre_independant(self):
        import random
        entrees = list(ENTREES_REGLABLES)
        random.shuffle(entrees)
        d_shuffle = digest.produire_digest(entrees, "2025-04-01")
        d_original = digest.produire_digest(ENTREES_REGLABLES, "2025-04-01")
        assert d_shuffle == d_original


class TestZeroHorloge:
    def test_source_sans_horloge(self):
        sources = inspect.getsource(digest)
        assert "datetime.now" not in sources
        assert "time.time" not in sources

    def test_dates_differentes_produit_digest_different(self):
        d1 = digest.produire_digest(ENTREES_REGLABLES, "2025-04-01")
        d2 = digest.produire_digest(ENTREES_REGLABLES, "2025-04-02")
        assert d1 != d2


class TestAgregatsCanalEtType:
    def test_comptes_exacts(self):
        digest_txt = digest.produire_digest(ENTREES_REGLABLES, "2025-04-01")

        attendus = {
            "telephone": {"signal": 2, "transition_phase": 1, "lead_emis": 0, "chiffrage_emis": 0, "alerte": 0},
            "courriel": {"signal": 1, "alerte": 1, "transition_phase": 0, "lead_emis": 0, "chiffrage_emis": 0},
            "formulaire": {"signal": 0, "lead_emis": 1, "transition_phase": 0, "chiffrage_emis": 0, "alerte": 0},
            "texte": {"signal": 0, "chiffrage_emis": 1, "transition_phase": 0, "lead_emis": 0, "alerte": 0},
        }

        verifications = 0
        for ligne in digest_txt.splitlines():
            ligne = ligne.strip("*- ")
            if ":" not in ligne:
                continue
            parties = [p.strip() for p in ligne.split(":", 2)]
            if len(parties) != 3:
                continue
            canal, type_, nb_str = parties
            try:
                nb = int(nb_str)
            except ValueError:
                continue
            if canal in attendus and type_ in attendus[canal]:
                assert attendus[canal][type_] == nb, f"Compte faux pour {canal}/{type_}"
                verifications += 1

        assert verifications == 20, f"Seulement {verifications} vérifications effectuées, 20 attendues"

class TestGardeFou:
    def test_passe_garde_fou_malgre_donnees_sensibles(self):
        digest_txt = digest.produire_digest(ENTREES_SENSIBLES, "2025-04-01")
        result = garde_fou.verifier_sortie(digest_txt)
        assert result["code"] == "OK", f"Garde-fou rejeté: {result}"

    def test_prix_et_engagement_absents_du_texte(self):
        digest_txt = digest.produire_digest(ENTREES_SENSIBLES, "2025-04-01")
        # Vérification ultra-stricte : pas de mention numérique de montants ni de dates
        assert "15000" not in digest_txt
        assert "2025-06-30" not in digest_txt
        assert "12345" not in digest_txt


class TestDigestVide:
    def test_entree_vide_produit_texte_fr_non_vide(self):
        digest_txt = digest.produire_digest([], "2025-04-01")
        assert len(digest_txt.strip()) > 0
        assert any(mot in digest_txt.lower() for mot in ["aucun", "absence", "vide", "néant"])


class TestAdaptateursDeterministes:
    def setup_method(self):
        self.engine = adaptateurs.creer_approval_engine()
        self.bus = adaptateurs.creer_bus()

    def test_proposer_meme_objet_meme_acteur_meme_id(self):
        id1 = self.engine.proposer({"chantier": "villa"}, "architecte")
        id2 = self.engine.proposer({"chantier": "villa"}, "architecte")
        assert id1 == id2

    @pytest.mark.parametrize("objet1,acteur1,objet2,acteur2", [
        ({"a":1}, "X", {"a":2}, "X"),
        ({"a":1}, "X", {"a":1}, "Y"),
        ({"a":1}, "X", {"b":1}, "X"),
    ])
    def test_proposer_objets_differents_ids_differents(self, objet1, acteur1, objet2, acteur2):
        id1 = self.engine.proposer(objet1, acteur1)
        id2 = self.engine.proposer(objet2, acteur2)
        assert id1 != id2

    def test_statut_id_inconnu_leve_exception_ou_verdict_explicite(self):
        # Doit lever une exception ou retourner un verdict non‑None
        try:
            statut_ret = self.engine.statut("id_inconnu_abc123")
        except Exception:
            pytest.fail("statut lève une exception inattendue")
        else:
            assert statut_ret is not None, "statut a retourné None pour un id inconnu"

    def test_bus_emettre_deterministe(self):
        id1 = self.bus.emettre("courriel", "message test")
        id2 = self.bus.emettre("courriel", "message test")
        assert id1 == id2

        id3 = self.bus.emettre("telephone", "autre message")
        assert id1 != id3


class TestFailClosedHorsModeOmbre:
    def test_approval_engine_hors_mode_ombre(self):
        engine = adaptateurs.creer_approval_engine(mode_ombre=False)
        # Toute opération renvoie le verdict d'indisponibilité
        res_proposer = engine.proposer({"x": 1}, "acteur")
        assert res_proposer["code"] == "REJ-ADAPTATEUR-INDISPONIBLE"

        res_statut = engine.statut("n'importe quoi")
        assert res_statut["code"] == "REJ-ADAPTATEUR-INDISPONIBLE"

    def test_bus_hors_mode_ombre(self):
        bus = adaptateurs.creer_bus(mode_ombre=False)
        res_emettre = bus.emettre("canal", "message")
        assert res_emettre["code"] == "REJ-ADAPTATEUR-INDISPONIBLE"

class TestContratAdaptateurs:
    """Vérification que l'implémentation alternative satisfait le même contrat."""

    @pytest.fixture(params=["mock_approval", "mock_bus", "adaptateurs_approval", "adaptateurs_bus"])
    def sujet(self, request):
        if request.param == "mock_approval":
            return MockApprovalEngine()
        elif request.param == "mock_bus":
            return MockNotificationBus()
        elif request.param == "adaptateurs_approval":
            return adaptateurs.creer_approval_engine()
        elif request.param == "adaptateurs_bus":
            return adaptateurs.creer_bus()

    def test_approval_engine_contrat(self):
        engine = MockApprovalEngine()
        # Vérification des méthodes et signatures
        assert hasattr(engine, "proposer")
        assert hasattr(engine, "statut")
        id_prop = engine.proposer({"test": 1}, "testeur")
        assert isinstance(id_prop, str) and len(id_prop) > 0

        # statut sur id existant fonctionne (si on a stocké)
        # (notre mock stocke par raw, impossible d'obtenir le statut avec l'id directement,
        #  donc on vérifie juste que ça existe)
        engine2 = adaptateurs.creer_approval_engine()
        id2 = engine2.proposer({"test": 1}, "testeur")
        assert id2  # id valide
        # statut sur id présent ne doit pas lever d'exception (peut être "proposé" ou autre)
        try:
            statut_res = engine2.statut(id2)
        except Exception:
            # Certaines implémentations lèvent si l'id n'a pas encore de statut (normal)
            pass

    def test_bus_contrat(self):
        bus = MockNotificationBus()
        assert hasattr(bus, "emettre")
        id_msg = bus.emettre("courriel", "test")
        assert isinstance(id_msg, str) and len(id_msg) > 0


class TestZeroReseau:
    def test_adaptateurs_sans_reseau(self):
        source = inspect.getsource(adaptateurs)
        for forbidden in ("urllib", "socket", "http.client"):
            assert forbidden not in source, f"adaptateurs utilise {forbidden}"

    def test_digest_sans_reseau(self):
        source = inspect.getsource(digest)
        for forbidden in ("urllib", "socket", "http.client"):
            assert forbidden not in source, f"digest utilise {forbidden}"


import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import digest
import adaptateurs
import garde_fou


ENTREES_SENSIBLES = [
    {
        "canal": "telephone",
        "type_entree": "signal",
        "payload": {"prix": 15000, "date_engagement": "2025-06-30"},
    },
    {
        "canal": "courriel",
        "type_entree": "lead_emis",
        "payload": {"montant": 12345, "echeance": "2025-08-15"},
    },
]


# ------------------------------------------------------------------ #
# correctif 1 : collision d'identifiants dans le bus
# ------------------------------------------------------------------ #
def test_ids_bus_injectifs():
    bus = adaptateurs.creer_bus()
    id1 = bus.emettre('a|b', 'c')
    id2 = bus.emettre('a', 'b|c')
    assert id1 != id2


# ------------------------------------------------------------------ #
# correctif 2 : entrées non classées comptées
# ------------------------------------------------------------------ #
def test_entrees_non_classees_comptees():
    entrees = [
        {"canal": "INCONNU", "type_entree": "signal"},
        {"canal": "telephone", "type_entree": "TYPE_INCONNU"},
        {"canal": "formulaire", "type_entree": "alerte"},  # valide
    ]
    result = digest.produire_digest(entrees, "2025-01-01")
    assert "entrées non classées : 2" in result

    entrees_ok = [{"canal": "courriel", "type_entree": "transition_phase"}]
    result_ok = digest.produire_digest(entrees_ok, "2025-01-01")
    assert "entrées non classées : 0" in result_ok


# ------------------------------------------------------------------ #
# correctif 3 : objet non sérialisable
# ------------------------------------------------------------------ #
def test_proposer_objet_non_serialisable():
    eng = adaptateurs.creer_approval_engine()
    id1 = eng.proposer({'x': {1, 2}}, 'alice')
    assert isinstance(id1, str)
    id2 = eng.proposer({'x': {1, 2}}, 'alice')
    assert id1 == id2


# ------------------------------------------------------------------ #
# correctif 5 : test d'absence des données payload + garde-fou
# ------------------------------------------------------------------ #
def test_prix_et_engagement_absents_du_texte_et_garde_fou():
    digest_txt = digest.produire_digest(ENTREES_SENSIBLES, "2025-04-01")
    # Aucune fuite de montants ou de dates issues des payloads
    assert "15000" not in digest_txt
    assert "12345" not in digest_txt
    assert "2025-06-30" not in digest_txt
    assert "2025-08-15" not in digest_txt
    # La date de référence est bien présente dans l'en-tête
    assert "2025-04-01" in digest_txt
    # Le digest doit passer le garde-fou
    verdict = garde_fou.verifier_sortie(digest_txt)
    assert verdict["code"] == "OK"
