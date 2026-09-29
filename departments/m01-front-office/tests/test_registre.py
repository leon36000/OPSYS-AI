import inspect
from pathlib import Path

import pytest
import yaml
from m1_front_office import horodatage, registre

_M1 = Path(__file__).resolve().parents[1]

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
        r.ajouter(e3)

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

    # --- NOUVEAUX TESTS EXIGÉS PAR LA REVUE ---

    def test_recouture_naive_detectee(self):
        """Altération partielle : suppression du maillon milieu + recouture naïve."""
        r = registre.Registre()
        e1 = _entree_signal("id1")
        e2 = _entree_signal("id2")
        e3 = _entree_signal("id3")
        r.ajouter(e1)
        r.ajouter(e2)
        r.ajouter(e3)

        # Suppression de l'entrée du milieu et recouture naïve
        del r._entrees[1]  # on retire e2
        # recouture : le precedent de l'ex-e3 (maintenant index 1) vers e1
        r._entrees[1]["precedent_ligne_id"] = r._entrees[0]["ligne_id"]
        # le ligne_id n'est PAS recalculé → la vérification échoue
        ok, verdict = r.valider_chaine()
        assert ok is False
        assert verdict["code"] == "REJ-CHAINE-ALTEREE"

    def test_reecriture_complete_detectee_par_ancre(self):
        """La chaîne seule ne suffit pas — l'ancre externe est la preuve."""
        r = registre.Registre()
        e1 = _entree_signal("id1")
        e2 = _entree_signal("id2")
        e3 = _entree_signal("id3")
        id1 = r.ajouter(e1)
        r.ajouter(e2)
        id3 = r.ajouter(e3)

        # Ancre AVANT attaque
        ancre = r.tete()
        assert ancre == id3

        # Attaque complète : supprimer l'entrée du milieu,
        # recoudre ET recalculer le ligne_id du successeur.
        del r._entrees[1]  # e2 disparaît, l'ex-e3 est à l'index 1
        succ = r._entrees[1]
        succ["precedent_ligne_id"] = id1
        contenu = registre._canonical_material(succ)
        new_id = registre._compute_ligne_id(contenu, id1)
        succ["ligne_id"] = new_id

        # Sans ancre, la chaîne semble intacte
        ok_sans_ancre, _ = r.valider_chaine()
        assert ok_sans_ancre is True

        # Avec l'ancre originale, l'attaque est détectée
        ok_avec_ancre, verdict = r.valider_chaine(ancre_attendue=ancre)
        assert ok_avec_ancre is False
        assert verdict["code"] == "REJ-CHAINE-ALTEREE"
        assert "ancre" in str(verdict).lower()


def test_ingestion_immuable():
    """Prouve que l'ingestion copie défensivement le dictionnaire d'entrée."""
    r = registre.Registre()

    entree = {
        "type_entree": "signal",
        "horodatage": "2026-07-15T14:30:00-04:00",
        "payload": {"signal_id": "ABC"}
    }

    ligne_id = r.ajouter(entree)

    # Mutation profonde après ingestion
    entree["payload"]["signal_id"] = "MUTE"
    entree["payload"]["injecte"] = "donnee extra"

    entrees_stockees = r.lire()
    assert len(entrees_stockees) == 1

    stockee = entrees_stockees[0]
    assert stockee["payload"]["signal_id"] == "ABC"
    assert "injecte" not in stockee["payload"]
    assert ligne_id is not None


def test_id_depend_du_predecesseur():
    """Propriété de chaîne : le même contenu ajouté deux fois dans un même registre produit des ids
    différents car le prédécesseur change."""
    r = registre.Registre()
    entree = _entree_signal()
    id1 = r.ajouter(entree)
    id2 = r.ajouter(entree)
    assert id1 != id2

def test_reproductibilite_sequence():
    """Déterminisme réel : deux registres neufs alimentés avec la même séquence de 3 entrées
    génèrent des ligne_id identiques deux à deux et la même tête."""
    sequence = [_entree_signal(), _entree_signal(), _entree_signal()]
    r1 = registre.Registre()
    r2 = registre.Registre()
    ids1 = [r1.ajouter(e) for e in sequence]
    ids2 = [r2.ajouter(e) for e in sequence]
    assert ids1 == ids2
    assert r1.tete() == r2.tete()
