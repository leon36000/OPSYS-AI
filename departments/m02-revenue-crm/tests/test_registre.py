import inspect
import re
from pathlib import Path

import pytest
from m2_revenue_crm import registre

_SRC = Path(__file__).resolve().parents[1] / "src"
_PKG = _SRC / "m2_revenue_crm"  # répertoire du paquet, pour les scans de sources


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
        registre_vide.ajouter(ENTREE_VALIDE)
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


    def test_identifiants_internes_fournis_sont_ignores(self):
        """Les clés internes ligne_id/precedent_ligne_id fournies dans l'entrée sont purgées."""
        r = registre.Registre()
        entree = dict(ENTREE_VALIDE, ligne_id="FAUX", precedent_ligne_id="FAUX")
        ligne_id = r.ajouter(entree)
        assert ligne_id != "FAUX", (
            "le ligne_id retourné ne doit pas reprendre la valeur falsifiée 'FAUX', "
            f"obtenu {ligne_id!r}"
        )
        maillon = r.lire()[0]
        assert maillon["ligne_id"] != "FAUX", (
            "le maillon stocké ne doit pas conserver le ligne_id falsifié 'FAUX', "
            f"obtenu {maillon['ligne_id']!r}"
        )
        assert maillon["precedent_ligne_id"] is None, (
            "le premier maillon doit porter precedent_ligne_id=None et non la valeur "
            f"falsifiée 'FAUX', obtenu {maillon['precedent_ligne_id']!r}"
        )
        assert r.valider_chaine() is True, (
            "la chaîne doit se revalider après purge des identifiants internes falsifiés : "
            "sans le nettoyage préventif, les clés falsifiées entreraient dans le calcul "
            "du ligne_id puis seraient écrasées, rendant la chaîne invalide"
        )
        r.ajouter(dict(ENTREE_VALIDE2))
        assert len(r.lire()) == 2, (
            "le registre devrait contenir 2 maillons après le second ajout, "
            f"obtenu {len(r.lire())}"
        )
        assert r.valider_chaine() is True, (
            "la chaîne à 2 maillons doit rester valide après ingestion d'une entrée "
            "contenant des identifiants internes falsifiés"
        )

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
                lambda r: r._chain.__setitem__(slice(0, 2), [r._chain[1], r._chain[0]]),
                "permutation des deux premiers maillons (ordre [m1, m0, m2])",
            ),
            (
                lambda r: r._chain.pop(1),
                "suppression d'un maillon au milieu",
            ),
            (
                lambda r: r._chain.insert(1, r._chain[1]),
                "duplication d'un maillon",
            ),
        ],
        ids=["mutation", "troncature", "permutation", "suppression_milieu", "duplication"],
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


    def test_registre_vide_est_valide(self):
        """Un registre neuf est valide au sens de toutes les vérifications."""
        r = registre.Registre()
        assert r.taille() == 0
        assert r.tete() is None
        assert r.lire() == []
        assert r.valider_chaine() is True
        assert r.valider_chaine(ancre=None) is True
        # l'ancre inexistante rend la chaîne invalide sans planter
        assert r.valider_chaine(ancre="ancre-inexistante") is False
        with pytest.raises(registre.VerificationError):
            r.assert_chaine(ancre="ancre-inexistante")

    def test_mutation_entree_apres_ajout_sans_effet(self):
        """Muter l'objet passé à ajouter() ne compromet pas le registre."""
        # Entrée avec valeurs imbriquées mutables
        entree = dict(
            type_entree="VISITE",
            horodatage="2023-10-01T12:00:00+02:00",
            visitor_id="v-001",
            landing="/accueil",
            details={"source": "facebook", "campaign": "spring"},
            tags=["urgent", "a-rappeler"],
        )
        r = registre.Registre()
        r.ajouter(entree)
        avant = r.lire()

        # Mutations profondes sur l'objet d'origine
        entree["visitor_id"] = "MODIFIE"
        entree["details"]["campaign"] = "INJECTION"
        entree["tags"].append("spam")

        apres = r.lire()
        assert apres == avant, "La mutation de l'entrée d'origine a altéré le registre"
        assert r.valider_chaine(), "La chaîne est corrompue après mutation externe"

    def test_champ_precedent_falsifie_seul_est_detecte(self):
        """Détecte une falsification isolée du champ precedent_ligne_id, que l'empreinte
        globale (qui ne dépend que des ligne_id) ne peut pas repérer ; le recalcul des
        ligne_id (qui exclut ce champ) n'est quant à lui jamais atteint pour ce maillon,
        car le contrôle de chaînage retourne avant que le recalcul ne soit franchi."""
        r = _registre_rempli(3)
        r._chain[1]["precedent_ligne_id"] = "falsifié"
        assert registre._hash_chaine(r._chain) == r._empreinte, (
            "Après falsification du seul champ precedent_ligne_id, l'empreinte globale "
            "recalculée doit rester identique à l'empreinte stockée : le contrôle "
            "d'empreinte globale est effectivement franchi et ce n'est donc pas lui qui détecte."
        )
        assert r.valider_chaine() is False, (
            "valider_chaine() doit retourner False : la falsification de precedent_ligne_id "
            "est détectée par le contrôle de chaînage, pas par l'empreinte globale."
        )
        with pytest.raises(registre.VerificationError, match="precedent"):
            r.assert_chaine()
    def test_maillon_non_encodable_est_refuse_sans_planter(self):
        """Un maillon falsifié non encodable invalide la chaîne sans lever d'exception."""

        class _ValeurNonEncodable:
            """Type factice qu'encoder_canonique ne sait pas encoder canoniquement."""

        r = _registre_rempli(3)
        r._chain[0]["valeur_injectee"] = _ValeurNonEncodable()
        try:
            resultat = r.valider_chaine()
        except Exception as exc:
            pytest.fail(
                "valider_chaine() ne doit propager aucune exception sur un maillon non "
                f"encodable, exception inattendue remontée : {type(exc).__name__}: {exc}"
            )
        assert resultat is False, (
            "valider_chaine() doit retourner False sur un maillon non encodable "
            f"(chemin fail-closed du recalcul), obtenu {resultat!r}"
        )
        with pytest.raises(registre.VerificationError, match="recalcul") as exc_info:
            r.assert_chaine()
        assert "recalcul" in str(exc_info.value), (
            "le message de VerificationError devrait mentionner l'échec du recalcul du "
            f"ligne_id, obtenu : {exc_info.value}"
        )

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
        "taille",
        "valider_chaine",
        "assert_chaine",
    ]
    # Expression régulière couvrant les mutateurs standards de list Python.
    # Inclut volontairement pop car aucune autre méthode publique n'utilise .pop(
    # (le .pop() présent dans ajouter() est un pop de dictionnaire, non visé ici).
    MUTATEUR_RE = re.compile(
        r"\.(append|extend|insert|remove|clear|sort|reverse|__setitem__|__delitem__|pop)\s*\("
    )

    def test_ajouter_seul_a_modifier_append(self):
        """
        Seule la méthode ajouter() peut contenir un appel à .append()
        sur la structure interne. Les autres méthodes publiques ne doivent pas
        écrire dans la chaîne.
        """
        cls = registre.Registre
        inspected = 0
        for nom in self.METHODES_PUBLIQUES:
            meth = getattr(cls, nom)
            try:
                src = inspect.getsource(meth)
            except (TypeError, OSError):
                # méthode built-in ou non accessible – toléré
                continue
            inspected += 1
            if nom == "ajouter":
                assert self.MUTATEUR_RE.search(src), (
                    "ajouter() doit modifier la structure interne"
                )
            else:
                assert not self.MUTATEUR_RE.search(src), (
                    f"La méthode {nom}() ne doit pas écrire dans la chaîne, "
                    f"mutateur trouvé : {self.MUTATEUR_RE.findall(src)}"
                )
        assert inspected == len(self.METHODES_PUBLIQUES), (
            f"Inspection incomplète : {inspected} méthode(s) inspectée(s) "
            f"au lieu de {len(self.METHODES_PUBLIQUES)}"
        )


# ---------------------------------------------------------------------------
# Lecture partielle : lire(depuis=...)
# ---------------------------------------------------------------------------
class TestLecturePartielle:
    """Vérifie la lecture partielle du registre via lire(depuis=...)."""

    @pytest.mark.parametrize(
        "indice",
        [0, 1, 2],
        ids=["premier-maillon", "second-maillon", "troisieme-maillon"],
    )
    def test_lire_depuis_un_maillon_retourne_la_queue(self, indice):
        """lire(depuis=<ligne_id du maillon d'indice donné>) retourne la queue complète."""
        r = _registre_rempli(3)
        tous = r.lire()
        ligne_id_cible = tous[indice]["ligne_id"]
        attendu_ids = [m["ligne_id"] for m in tous[indice:]]
        extrait = r.lire(depuis=ligne_id_cible)
        assert len(extrait) == 3 - indice, (
            f"lire(depuis=<ligne_id d'indice {indice}>) devrait retourner "
            f"{3 - indice} maillon(s), obtenu {len(extrait)}"
        )
        obtenu_ids = [m["ligne_id"] for m in extrait]
        assert obtenu_ids == attendu_ids, (
            f"les ligne_id retournés depuis l'indice {indice} devraient être "
            f"{attendu_ids}, obtenu {obtenu_ids}"
        )

    def test_lire_depuis_ligne_id_inconnu_leve(self):
        """lire(depuis=<ligne_id inconnu>) lève ValueError mentionnant la valeur fournie."""
        r = _registre_rempli(3)
        with pytest.raises(ValueError, match="inexistant") as exc_info:
            r.lire(depuis="inexistant")
        assert "inexistant" in str(exc_info.value), (
            "le message de ValueError devrait mentionner la valeur fournie 'inexistant', "
            f"obtenu : {exc_info.value}"
        )

    def test_lire_depuis_retourne_une_copie(self):
        """Muter le résultat de lire(depuis=...) laisse le registre interne intact."""
        r = _registre_rempli(3)
        etat_initial = r.lire()
        ligne_id_cible = etat_initial[1]["ligne_id"]
        extrait = r.lire(depuis=ligne_id_cible)
        extrait[0]["ligne_id"] = "MUTATION_INTERDITE"
        extrait[0]["champ_corrompu"] = "MUTATION_INTERDITE"
        etat_apres = r.lire()
        assert etat_apres == etat_initial, (
            "muter la liste retournée par lire(depuis=...) ne doit pas altérer le "
            f"registre : état initial {etat_initial}, état après mutation {etat_apres}"
        )
        assert r.valider_chaine() is True, (
            "valider_chaine() doit rester True après mutation de la copie retournée"
        )

    def test_lire_sans_argument_equivaut_au_premier_maillon(self):
        """lire() et lire(depuis=<premier ligne_id>) retournent exactement la même liste."""
        r = _registre_rempli(3)
        tous = r.lire()
        premier_ligne_id = tous[0]["ligne_id"]
        depuis_premier = r.lire(depuis=premier_ligne_id)
        assert depuis_premier == tous, (
            "lire(depuis=<ligne_id du premier maillon>) devrait être strictement "
            f"identique à lire() : lire()={tous}, "
            f"lire(depuis={premier_ligne_id!r})={depuis_premier}"
        )

    def test_lire_sans_argument_retourne_une_copie(self):
        """Muter le résultat de lire() sans argument (champ modifié et clé ajoutée) ne doit
        pas altérer le registre : ce test rougit si lire() retourne directement self._chain."""
        r = _registre_rempli(3)
        lecture = r.lire()
        assert len(lecture) == 3, (
            f"Le registre rempli avec 3 maillons doit en exposer 3, obtenu : {len(lecture)}."
        )
        avant = [{cle: valeur for cle, valeur in maillon.items()} for maillon in lecture]
        lecture[1]["ligne_id"] = "muté"
        lecture[1]["cle_injectee"] = "injectée"
        apres = r.lire()
        assert apres == avant, (
            "Muter le résultat de lire() sans argument a altéré le registre : lire() doit "
            "retourner une copie profonde de la chaîne, jamais une référence à self._chain."
        )
        assert r.valider_chaine() is True, (
            "valider_chaine() doit rester True après la mutation de la copie retournée par "
            "lire() : le registre interne ne doit pas avoir été touché."
        )
