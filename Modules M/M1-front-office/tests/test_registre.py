import sys
import hashlib
import inspect
import copy
from pathlib import Path
import pytest
import yaml

# Adapter le path pour importer les sources
_M1 = Path(__file__).resolve().parents[1]
_SRC = _M1 / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
import registre
import horodatage
import verdicts

# Fixture pour charger les signaux réels
@pytest.fixture
def charger_signaux_fixture():
    fichier = _M1 / "fixtures" / "signaux" / "signaux.v1.yaml"
    with fichier.open() as f:
        data = yaml.safe_load(f)
    if not data.get("fictif"):
        raise ValueError("fictif manquant")
    return data["signaux"]


def _entree_signal(signal_id="abc", horodatage_val="2026-07-15T14:30:00-04:00"):
    return {
        "type_entree": "signal",
        "horodatage": horodatage_val,
        "payload": {
            "signal_id": signal_id,
            "canal": "telephone",
            "contenu_brut": "test",
        },
        "precedent_ligne_id": None,
    }


def _entree_signal_personnalisee(**kwargs):
    base = _entree_signal()
    base.update(kwargs)
    return base


class TestRegistre:
    def test_ajout_produit_ligne_id_sha256(self):
        r = registre.Registre()
        entree = _entree_signal()
        id1 = r.ajouter(entree)
        assert isinstance(id1, str)
        assert len(id1) == 64
        assert all(c in "0123456789abcdef" for c in id1)

        # Déterministe ?
        id2 = r.ajouter(entree)
        # Note: le précédent change, donc l'id change (chaîne intégrée).
        # On vérifie juste qu'il est produit sans erreur.
        assert id1 != id2   # preuve que le chaînage modifie l'id

    def test_chainage(self):
        r = registre.Registre()
        e1 = _entree_signal()
        e2 = _entree_signal_personnalisee(payload={"signal_id": "def"})
        e3 = _entree_signal_personnalisee(payload={"signal_id": "ghi"})

        id1 = r.ajouter(e1)
        id2 = r.ajouter(e2)
        id3 = r.ajouter(e3)

        chaine = r.lire(depuis=id1)
        assert len(chaine) == 3
        assert chaine[0]["precedent_ligne_id"] is None
        assert chaine[1]["precedent_ligne_id"] == id1
        assert chaine[2]["precedent_ligne_id"] == id2

    def test_valider_chaine_ok(self):
        r = registre.Registre()
        e1 = _entree_signal()
        e2 = _entree_signal_personnalisee(payload={"signal_id": "def"})
        e3 = _entree_signal_personnalisee(payload={"signal_id": "ghi"})
        r.ajouter(e1)
        r.ajouter(e2)
        r.ajouter(e3)
        ok, verdict = r.valider_chaine()
        assert ok is True
        assert verdict is None

    def test_valider_chaine_detecte_alteration(self):
        r = registre.Registre()
        e1 = _entree_signal()
        r.ajouter(e1)
        # Altération manuelle de la mémoire interne
        chaine = r._entrees  # accès direct pour le test
        originale = dict(chaine[0])
        chaine[0]["payload"]["signal_id"] = "corrompu"
        ok, verdict = r.valider_chaine()
        assert ok is False
        assert verdict["code"] == "REJ-CHAINE-ALTEREE"
        # Restaurer
        chaine[0] = originale

    def test_append_only(self):
        r = registre.Registre()
        attrs = dir(r)
        for forbidden in ["supprimer", "modifier", "update", "delete", "remove"]:
            assert not any(forbidden in attr for attr in attrs), (
                f"Méthode {forbidden} trouvée dans Registre"
            )

    def test_zero_perte_fixtures(self, charger_signaux_fixture):
        r = registre.Registre()
        signaux = charger_signaux_fixture
        initial_count = r.taille()
        for signal in signaux:
            entree = {
                "type_entree": "signal",
                "horodatage": signal["horodatage"],
                "payload": signal,
                "precedent_ligne_id": None,
            }
            r.ajouter(entree)
        after_count = r.taille()
        assert after_count - initial_count == len(signaux)

    def test_refus_fixture_sans_fictif(self, tmp_path):
        fichier = tmp_path / "signaux_sans_fictif.yaml"
        fichier.write_text("signaux: []\n")
        with pytest.raises(ValueError, match="fictif"):
            registre.charger_signaux(str(fichier))

        fichier.write_text("fictif: false\nsignaux: []\n")
        with pytest.raises(ValueError, match="fictif"):
            registre.charger_signaux(str(fichier))

    def test_type_entree_enum(self):
        r = registre.Registre()
        entree_invalide = _entree_signal_personnalisee(type_entree="inconnu")
        with pytest.raises(ValueError) as excinfo:
            r.ajouter(entree_invalide)
        assert "REJ-ENUM-INVALIDE" in str(excinfo.value)

    def test_zero_horloge(self):
        # Vérifier qu'aucun appel à l'horloge système n'existe dans le code source de registre
        source_registre = inspect.getsource(registre)
        assert "datetime.now" not in source_registre
        assert "time.time" not in source_registre

        assert horodatage.valider_horodatage("2026-07-15T14:30:00-04:00") is True
        with pytest.raises(ValueError) as excinfo:
            horodatage.valider_horodatage("2026-07-15T14:30:00")
        assert "fuseau" in str(excinfo.value) or "ISO" in str(excinfo.value)

    # --- NOUVEAUX TESTS EXIGÉS PAR LA REVUE ---

    def test_suppression_recousue_detectee(self):
        r = registre.Registre()
        e1 = _entree_signal("id1")
        e2 = _entree_signal("id2")
        e3 = _entree_signal("id3")
        id1 = r.ajouter(e1)
        r.ajouter(e2)
        r.ajouter(e3)

        # On récupère la liste interne, on supprime l'entrée du milieu
        chaine = r._entrees
        assert len(chaine) == 3
        # On garde la première et la troisième, puis on recoud
        del chaine[1]  # suppression de l'entrée centrale
        assert len(chaine) == 2
        # Recoudre : le precedent_ligne_id de l'ex-3e (maintenant index 1) vers la 1re (index 0)
        chaine[1]["precedent_ligne_id"] = chaine[0]["ligne_id"]

        ok, verdict = r.valider_chaine()
        assert ok is False
        assert verdict["code"] == "REJ-CHAINE-ALTEREE"

    def test_lecture_immuable(self):
        r = registre.Registre()
        e1 = _entree_signal("original")
        r.ajouter(e1)

        copie = r.lire()
        assert len(copie) == 1
        # Muter profondément
        copie[0]["payload"]["signal_id"] = "pirate"
        copie[0]["payload"]["canal"] = "texte"
        copie[0]["ligne_id"] = "invalide"
        copie.pop()  # tentative de suppression

        # Relire
        relu = r.lire()
        assert len(relu) == 1
        assert relu[0]["payload"]["signal_id"] == "original"
        assert relu[0]["payload"]["canal"] == "telephone"

    def test_zero_perte_identite(self, charger_signaux_fixture):
        r = registre.Registre()
        signaux = charger_signaux_fixture
        signal_ids_fixture = {s["signal_id"] for s in signaux}

        for signal in signaux:
            entree = {
                "type_entree": "signal",
                "horodatage": signal["horodatage"],
                "payload": signal,
                "precedent_ligne_id": None,
            }
            r.ajouter(entree)

        chaine = r.lire()
        assert len(chaine) == len(signaux)
        ids_registre = {entree["payload"]["signal_id"] for entree in chaine}
        assert ids_registre == signal_ids_fixture

    def test_signal_malforme_rejete(self, tmp_path):
        # YAML temporaire avec un signal sans canal
        contenu = """
fictif: true
signaux:
  - signal_id: abc
    horodatage: "2026-07-15T14:30:00-04:00"
    contenu_brut: "bonjour"
    # canal manquant
"""
        fichier = tmp_path / "mauvais.yaml"
        fichier.write_text(contenu)
        with pytest.raises(ValueError) as excinfo:
            registre.charger_signaux(str(fichier))
        assert "canal" in str(excinfo.value).lower()

    def test_assert_chaine_leve(self):
        r = registre.Registre()
        r.ajouter(_entree_signal("a"))
        # Altérer
        r._entrees[0]["payload"]["signal_id"] = "corrompu"
        with pytest.raises(ValueError) as excinfo:
            r.assert_chaine()
        assert "REJ-CHAINE-ALTEREE" in str(excinfo.value)
