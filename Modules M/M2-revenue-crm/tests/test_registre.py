import sys
from pathlib import Path
import pytest
import inspect
import re

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
import registre  # noqa: E402
import verdicts  # noqa: E402

# ---------------------------------------------------------------------------
# Constantes pour les tests
# ---------------------------------------------------------------------------
TYPE_VALIDE = "VISITE"          # valeur tolérée par l'énumération (supposée)
TYPE_INVALIDE = "INCONNU"
HORODATAGE_VALIDE = "2023-10-01T12:00:00+02:00"
HORODATAGE_INVALIDE = "2023-10-01"          # simple date sans timezone
ENTREE_VALIDE = dict(
    type_entree=TYPE_VALIDE,
    horodatage=HORODATAGE_VALIDE,
    visitor_id="v-001",
    landing="/accueil",
)
ENTREE_VALIDE2 = dict(
    type_entree="LEAD",
    horodatage="2023-10-02T09:30:00+02:00",
    lead_id="l-001",
    source="google",
)
ENTREE_VALIDE3 = dict(
    type_entree="CONVERSION",
    horodatage="2023-10-03T14:15:00+02:00",
    visitor_id="v-002",
    montant=99.9,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def registre_vide():
    """Retourne un registre neuf sans aucune entrée."""
    return registre.Registre()


def _registre_rempli(n=3):
    """Crée un registre avec n entrées valides distinctes et le retourne."""
    r = registre.Registre()
    entrees = [ENTREE_VALIDE, ENTREE_VALIDE2, ENTREE_VALIDE3]
    for i in range(min(n, len(entrees))):
        r.ajouter(entrees[i])
    return r


# ---------------------------------------------------------------------------
# Tests d'usage basique (règle 1, 2, 3)
# ---------------------------------------------------------------------------
class TestAppendOnly:
    def test_ajouter_retourne_hash_non_vide(self, registre_vide):
        """ajouter() doit retourner une chaîne non vide."""
        hash_maillon = registre_vide.ajouter(ENTREE_VALIDE)
        assert isinstance(hash_maillon, str), "Le hash doit être une chaîne"
        assert len(hash_maillon) > 0, "Le hash ne doit pas être vide"

    def test_taille_croit_apres_ajout(self, registre_vide):
        """taille() augmente de 1 à chaque ajouter()."""
        assert registre_vide.taille() == 0
        registre_vide.ajouter(ENTREE_VALIDE)
        assert registre_vide.taille() == 1
        registre_vide.ajouter(ENTREE_VALIDE2)
        assert registre_vide.taille() == 2

    def test_lire_ordre_insertion(self, registre_vide):
        """lire() rend les entrées dans l'ordre d'insertion."""
        registre_vide.ajouter(ENTREE_VALIDE)
        registre_vide.ajouter(ENTREE_VALIDE2)
        contenu = registre_vide.lire()
        assert len(contenu) == 2, "Deux entrées attendues"
        assert contenu[0]["type_entree"] == TYPE_VALIDE
        assert contenu[1]["type_entree"] == "LEAD"

    def test_chainage_ligne_id(self, registre_vide):
        """Les entrées portent ligne_id et precedent_ligne_id chaînés."""
        hash1 = registre_vide.ajouter(ENTREE_VALIDE)
        hash2 = registre_vide.ajouter(ENTREE_VALIDE2)
        contenu = registre_vide.lire()
        # Première entrée
        assert "ligne_id" in contenu[0], "ligne_id manquant dans le premier maillon"
        assert contenu[0]["precedent_ligne_id"] is None, (
            "La première entrée doit avoir precedent_ligne_id à None"
        )
        # Deuxième entrée
        assert contenu[1]["precedent_ligne_id"] == contenu[0]["ligne_id"], (
            "precedent_ligne_id de n+1 doit égaler le ligne_id de n"
        )
        # tete() doit correspondre au dernier hash
        assert registre_vide.tete() == hash2, "tete() doit renvoyer le hash du dernier maillon ajouté"


class TestValidationEntree:
    def test_type_entree_invalide_leve(self, registre_vide):
        """Ajouter une entrée avec un type_entree hors enum doit lever une erreur."""
        mauvaise = dict(ENTREE_VALIDE, type_entree=TYPE_INVALIDE)
        with pytest.raises(
            (ValueError, TypeError),
            match=r"type_entree|inconnu|non reconnu",
        ):
            registre_vide.ajouter(mauvaise)

    def test_horodatage_absent_leve(self, registre_vide):
        """Une entrée sans horodatage doit provoquer une erreur."""
        sans_horodatage = dict(ENTREE_VALIDE)
        del sans_horodatage["horodatage"]
        with pytest.raises((ValueError, KeyError, TypeError)):
            registre_vide.ajouter(sans_horodatage)

    def test_horodatage_invalide_leve(self, registre_vide):
        """Un horodatage invalide (sans timezone) doit lever."""
        mauvais_horodatage = dict(ENTREE_VALIDE, horodatage=HORODATAGE_INVALIDE)
        with pytest.raises(
            (ValueError, TypeError),
            match=r"horodatage|timezone|ISO.8601",
        ):
            registre_vide.ajouter(mauvais_horodatage)

    def test_entree_non_dict_leve(self, registre_vide):
        """Passer autre chose qu'un dict doit lever."""
        with pytest.raises((TypeError, ValueError)):
            registre_vide.ajouter("pas_un_dict")


# ---------------------------------------------------------------------------
# Tests de chaîne valide et altérations (règles 4, 5)
# ---------------------------------------------------------------------------
class TestValiditeChaine:
    def test_sequence_valide_donne_valider_chaine_vrai(self):
        """Après des ajouts valides, valider_chaine() retourne True et assert_chaine() ne lève pas."""
        r = _registre_rempli(2)
        assert r.valider_chaine() is True, "Une chaîne correcte doit être validée"
        # Ne doit pas lever
        r.assert_chaine()

    @pytest.mark.parametrize(
        "altération,description",
        [
            (
                lambda r: r._chain.__setitem__(0, dict(r._chain[0], type_entree="ALTERE")),
                "mutation du contenu d'un maillon",
            ),
            (
                lambda r: r._chain.pop(),
                "troncature (suppression du dernier maillon)",
            ),
            (
                lambda r: r._chain.__setitem__(0, r._chain[1]) or r._chain.__setitem__(1, r._chain[0]),
                "réordonnancement de deux maillons",
            ),
            (
                lambda r: r._chain.pop(1),
                "suppression d'un maillon au milieu",
            ),
        ],
        ids=["mutation", "troncature", "reordonnancement", "suppression_milieu"],
    )
    def test_alteration_casse_validation(self, altération, description):
        """
        CA-M2-14 : toute altération (mutation, troncature, réordonnancement,
        suppression d'un maillon) doit être détectée.
        """
        r = _registre_rempli(3)
        # Appliquer l'altération sur la structure interne
        altération(r)
        assert r.valider_chaine() is False, (
            f"Validation devrait échouer après {description}"
        )
        with pytest.raises(
            (ValueError, AssertionError, registre.VerificationError),
            match=r"cha[iî]ne|corrompu|invalide|alt[eé]r[eé]",
        ):
            r.assert_chaine()

    def test_ancre_externe_invalide(self):
        """
        valider_chaine(ancre_attendue) doit échouer si l'ancre ne correspond
        pas à tete(). Cela protège contre une réécriture complète de la chaîne
        (car la tête changerait et l'ancre externe, gardée à l'extérieur,
        révélerait la substitution).
        """
        r = _registre_rempli(2)
        fausse_ancre = "f00ba4-ancre-bidon"
        assert r.valider_chaine(ancre=fausse_ancre) is False, (
            "Une ancre externe différente de tete() doit invalider la chaîne"
        )
        with pytest.raises(
            (ValueError, AssertionError, registre.VerificationError),
            match=r"ancre|t[eê]te|correspond",
        ):
            r.assert_chaine(ancre=fausse_ancre)

    def test_ancre_correcte_valide(self):
        """Avec la bonne ancre (tete()), valider_chaine doit réussir."""
        r = _registre_rempli(2)
        bonne_ancre = r.tete()
        assert r.valider_chaine(ancre=bonne_ancre) is True
        r.assert_chaine(ancre=bonne_ancre)  # ne lève pas


# ---------------------------------------------------------------------------
# Déterminisme et absence d’horloge / réseau (règles 7, 8)
# ---------------------------------------------------------------------------
class TestDeterminismeEtPurete:
    def test_determinisme_tete(self):
        """Deux registres alimentés des mêmes entrées produisent la même tête."""
        r1 = registre.Registre()
        r2 = registre.Registre()
        for entree in (ENTREE_VALIDE, ENTREE_VALIDE2):
            r1.ajouter(entree)
            r2.ajouter(entree)
        assert r1.tete() == r2.tete(), "Les têtes doivent être identiques"
        assert r1.valider_chaine() and r2.valider_chaine()

    def test_aucune_horloge_interne(self):
        """Le module registre ne doit pas utiliser ni datetime.now ni time.time."""
        source = inspect.getsource(registre)
        assert "datetime.now" not in source, "datetime.now détecté dans le module"
        assert "time.time" not in source, "time.time détecté dans le module"

    def test_aucun_reseau_ni_llm(self):
        """Aucun import réseau ou LLM ne doit apparaître dans le module."""
        source = inspect.getsource(registre)
        interdits = [
            "urllib",
            "socket",
            "http.client",
            "requests",
            "openai",
            "litellm",
        ]
        for mot in interdits:
            assert mot not in source, f"Import interdit détecté : {mot}"


# ---------------------------------------------------------------------------
# Règle 6 : aucune écriture hors ajouter()
# ---------------------------------------------------------------------------
class TestAucuneEcritureSaufAjouter:
    METHODES_PUBLIQUES = [
        "ajouter",
        "lire",
        "tete",
        "valider_chaine",
        "assert_chaine",
        "taille",
    ]

    def test_ajouter_seul_a_modifier_append(self):
        """
        Seule la méthode ajouter() peut contenir un appel à .append()
        sur la structure interne. Les autres méthodes publiques ne doivent pas
        écrire dans la chaîne.
        """
        cls = registre.Registre
        for nom in self.METHODES_PUBLIQUES:
            meth = getattr(cls, nom)
            try:
                src = inspect.getsource(meth)
            except (TypeError, OSError):
                # méthode built-in ou non accessible – toléré
                continue
            if nom == "ajouter":
                # ajouter doit bien contenir un append (ou insert) – on vérifie
                # qu'il y a au moins un appel de modification de liste
                assert re.search(r"\.(append|extend|insert|__setitem__|__delitem__)\s*\(", src), (
                    "ajouter() doit modifier la structure interne"
                )
            else:
                assert ".append(" not in src, (
                    f"La méthode {nom}() ne doit pas faire d'append sur la chaîne"
                )
                assert ".insert(" not in src, (
                    f"La méthode {nom}() ne doit pas faire d'insert sur la chaîne"
                )
                # tolérer pop() pour certaines opérations de lecture? Non, aucun
                # pop ne doit être présent non plus car il modifie.
                assert ".pop(" not in src, (
                    f"La méthode {nom}() ne doit pas faire de pop sur la chaîne"
                )
