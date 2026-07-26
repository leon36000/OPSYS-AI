import sys, hashlib, inspect
from pathlib import Path
import pytest
import yaml

_M1 = Path(__file__).resolve().parents[1]
_SRC = _M1 / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
import registre, contrats, verdicts, horodatage  # noqa: E402

# --- Helpers ---
@pytest.fixture(autouse=True)
def registre_propre():
    """Isole les tests en réinitialisant le registre avant et après chaque test."""
    registre.reset()
    yield
    registre.reset()


def _entree_signal(signal_id="abc", horodatage="2026-07-15T14:30:00-04:00"):
    return {
        "type_entree": "signal",
        "horodatage": horodatage,
        "payload": {"signal_id": signal_id, "canal": "telephone", "contenu_brut": "test"},
        "precedent_ligne_id": None
    }

def _entree_signal_personnalisee(**kwargs):
    base = _entree_signal()
    base.update(kwargs)
    return base

class TestRegistre:
    def test_ajout_produit_ligne_id_sha256(self):
        entree = _entree_signal()
        id1 = registre.ajouter_entree(entree)
        assert isinstance(id1, str)
        assert len(id1) == 64
        assert all(c in "0123456789abcdef" for c in id1)

        id2 = registre.ajouter_entree(entree)
        assert id1 == id2  # déterministe

    def test_chainage(self):
        e1 = _entree_signal()
        e2 = _entree_signal_personnalisee(payload={"signal_id": "def"})
        e3 = _entree_signal_personnalisee(payload={"signal_id": "ghi"})

        id1 = registre.ajouter_entree(e1)
        id2 = registre.ajouter_entree(e2)
        id3 = registre.ajouter_entree(e3)

        registre_chain = registre.lire_registre(depuis=id1)
        assert len(registre_chain) == 3
        assert registre_chain[0]["precedent_ligne_id"] is None
        assert registre_chain[1]["precedent_ligne_id"] == id1
        assert registre_chain[2]["precedent_ligne_id"] == id2

    def test_valider_chaine_ok(self):
        # Ajouter 3 entrées, la chaîne doit être valide
        e1 = _entree_signal()
        e2 = _entree_signal_personnalisee(payload={"signal_id": "def"})
        e3 = _entree_signal_personnalisee(payload={"signal_id": "ghi"})
        registre.ajouter_entree(e1)
        registre.ajouter_entree(e2)
        registre.ajouter_entree(e3)
        assert registre.valider_chaine() is True

    def test_valider_chaine_detecte_alteration(self):
        # Altération manuelle de la mémoire interne (on suppose un accès direct possible pour test)
        # Si non accessible, on pourrait tester via un rechargement ; ici on supposera une corruption interne.
        e1 = _entree_signal()
        registre.ajouter_entree(e1)
        # On ne peut pas modifier facilement l'état interne, donc nous testons plutôt que 
        # si on altère une entrée après coup (en modifiant la liste interne), valider_chaine détecte.
        # Pour cela, on récupère la liste et on modifie un payload.
        chaine = registre._registre  # hypothèse d'accès pour test
        originale = dict(chaine[0])
        chaine[0]["payload"]["signal_id"] = "corrompu"
        assert registre.valider_chaine() is False
        # Restaurer
        chaine[0] = originale

    def test_append_only(self):
        # Vérifier qu'aucune méthode de suppression/modification n'est exposée
        attrs = dir(registre)
        for forbidden in ["supprimer", "modifier", "update", "delete", "remove"]:
            assert not any(forbidden in attr for attr in attrs), f"Fonction {forbidden} trouvée dans registre"

    def test_zero_perte_fixtures(self, charger_signaux_fixture):
        signaux = charger_signaux_fixture
        initial_count = len(registre.lire_registre(depuis=None))
        for signal in signaux:
            entree = {
                "type_entree": "signal",
                "horodatage": signal["horodatage"],
                "payload": signal,
                "precedent_ligne_id": None
            }
            registre.ajouter_entree(entree)
        after_count = len(registre.lire_registre(depuis=None))
        assert after_count - initial_count == len(signaux)

    def test_refus_fixture_sans_fictif(self, tmp_path):
        # Fichier temporaire sans fictif
        fichier = tmp_path / "signaux_sans_fictif.yaml"
        fichier.write_text("signaux: []\n")
        with pytest.raises(ValueError, match="fictif"):
            registre.charger_signaux(str(fichier))

        # fictif: false
        fichier.write_text("fictif: false\nsignaux: []\n")
        with pytest.raises(ValueError, match="fictif"):
            registre.charger_signaux(str(fichier))

    def test_type_entree_enum(self):
        entree_invalide = _entree_signal_personnalisee(type_entree="inconnu")
        with pytest.raises(ValueError) as excinfo:
            registre.ajouter_entree(entree_invalide)
        assert "REJ-ENUM-INVALIDE" in str(excinfo.value)

    def test_zero_horloge(self):
        # Vérifier qu'aucun appel à l'horloge système n'existe dans le code source de registre
        source_registre = inspect.getsource(registre)
        assert "datetime.now" not in source_registre
        assert "time.time" not in source_registre

        # horodatage : valider un ISO avec fuseau accepté, sans fuseau rejeté
        assert horodatage.valider_horodatage("2026-07-15T14:30:00-04:00") is True
        with pytest.raises(ValueError) as excinfo:
            horodatage.valider_horodatage("2026-07-15T14:30:00")  # sans fuseau
        assert "fuseau" in str(excinfo.value) or "ISO" in str(excinfo.value)

# Fixture pour charger les signaux réels
@pytest.fixture
def charger_signaux_fixture():
    fichier = _M1 / "fixtures" / "signaux" / "signaux.v1.yaml"
    with fichier.open() as f:
        data = yaml.safe_load(f)
    if not data.get("fictif"):
        raise ValueError("fictif manquant")
    return data["signaux"]
