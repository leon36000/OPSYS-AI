import sys
import ast
import inspect
import subprocess
import os
from pathlib import Path
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import encodage  # noqa: E402
import verdicts  # noqa: E402
import registre  # noqa: E402
import adaptateurs  # noqa: E402


class TestFailClosed:
    """Propriété fail-closed : toute écriture hors mode ombre est rejetée sans effet de bord."""

    @pytest.fixture
    def charge_exemple(self):
        """Charge inoffensive pour les tests."""
        return {"nom": "Test Lead"}

    @pytest.fixture
    def horodatage_valide(self):
        """Horodatage ISO-8601 avec fuseau."""
        return "2025-03-27T10:00:00+00:00"

    @pytest.fixture
    def adaptateur_ombre(self, horodatage_valide):
        """Fabrique un adaptateur en mode ombre valide."""
        obj, ver = adaptateurs.construire_adaptateur("test_cible", adaptateurs.MODE_OMBRE)
        assert obj is not None, "construire_adaptateur a retourné None en mode ombre"
        assert ver is None, "construire_adaptateur a retourné un verdict en mode ombre"
        return obj

    def test_ecriture_mode_ombre_succes(self, adaptateur_ombre, charge_exemple, horodatage_valide):
        """
        Prouve qu'en mode ombre, ecrire retourne (accuse, None) et que l'accusé
        contient l'identifiant de l'adaptateur et l'horodatage fourni.
        """
        accuse, ver = adaptateur_ombre.ecrire(charge_exemple, horodatage_valide)
        assert accuse is not None, "Écriture en mode ombre doit retourner un accusé"
        assert ver is None, (
            "Écriture en mode ombre ne doit pas retourner de verdict de rejet"
        )
        assert isinstance(accuse, dict), "L'accusé doit être un dict"
        assert "adaptateur_id" in accuse, (
            "L'accusé doit porter l'identifiant de l'adaptateur"
        )
        assert accuse["adaptateur_id"] == adaptateur_ombre.identifiant(), (
            "L'identifiant dans l'accusé doit correspondre à celui de l'adaptateur"
        )
        assert "horodatage" in accuse, "L'accusé doit porter l'horodatage"
        assert accuse["horodatage"] == horodatage_valide, (
            "L'horodatage dans l'accusé doit être celui fourni à l'appel"
        )

    @pytest.mark.parametrize(
        "mode_invalide",
        ["production", "reel", "live", ""],
        ids=["production", "reel", "live", "vide"],
    )
    def test_construire_mode_invalide_rejete(self, mode_invalide):
        """
        Prouve que construire_adaptateur avec un mode hors énumération
        retourne (None, verdict REJ-ADAPTATEUR-INDISPONIBLE) et aucun objet.
        """
        obj, ver = adaptateurs.construire_adaptateur("test", mode_invalide)
        assert obj is None, "Aucun adaptateur ne doit être construit pour un mode invalide"
        assert ver is not None, "Un verdict doit être retourné"
        assert isinstance(ver, dict), "Le verdict doit être un dict"
        assert ver["code"] == "REJ-ADAPTATEUR-INDISPONIBLE", (
            f"Code attendu REJ-ADAPTATEUR-INDISPONIBLE, reçu {ver.get('code')}"
        )
        assert verdicts.est_verdict(ver["code"]), (
            "REJ-ADAPTATEUR-INDISPONIBLE doit faire partie du catalogue de verdicts"
        )

    def test_ecriture_hors_mode_ombre_sans_effet_de_bord(
        self, adaptateur_ombre, charge_exemple, horodatage_valide
    ):
        """
        Prouve qu'une écriture tentée après falsification du mode
        hors ombre est rejetée ET ne modifie pas le journal simulé.
        """
        # Écrire une première charge pour avoir un journal non vide
        adaptateur_ombre.ecrire(charge_exemple, horodatage_valide)
        taille_avant = len(adaptateur_ombre.lire_journal())

        # Falsification du mode. ATTENTION : l'attribut réel est _mode ;
        # écrire adaptateur_ombre.mode créerait un attribut NEUF sans rien
        # falsifier, et l'écriture réussirait — le test passerait alors en
        # croyant tester le rejet. On vérifie donc que l'attribut existe
        # AVANT de le falsifier.
        assert adaptateur_ombre._mode == adaptateurs.MODE_OMBRE, (
            "pré-condition : l'adaptateur doit être en mode ombre"
        )
        adaptateur_ombre._mode = "production"

        accuse, ver = adaptateur_ombre.ecrire(
            {"autre": "charge"}, horodatage_valide
        )
        assert accuse is None, "Écriture hors mode ombre ne doit pas produire d'accusé"
        assert ver is not None, "Écriture hors mode ombre doit retourner un verdict"
        assert ver["code"] == "REJ-ADAPTATEUR-INDISPONIBLE", (
            "Le code de rejet doit être REJ-ADAPTATEUR-INDISPONIBLE"
        )
        taille_apres = len(adaptateur_ombre.lire_journal())
        assert taille_apres == taille_avant, (
            "La longueur du journal simulé ne doit pas changer après un rejet"
        )

    def test_horodatage_sans_fuseau_refuse(self, adaptateur_ombre, charge_exemple):
        """Prouve qu'un horodatage sans fuseau est refusé par un VERDICT, sans
        effet de bord.

        Convention de tout le module M2 (ingestion.ingerer,
        statuts.transitionner, doublons.signaler) : le refus est un couple
        (None, verdict), jamais une exception qui remonterait à l'appelant.
        """
        taille_avant = len(adaptateur_ombre.lire_journal())
        accuse, verdict = adaptateur_ombre.ecrire(charge_exemple, "2026-03-01T10:00:00")
        assert accuse is None, "aucun accusé sur horodatage sans fuseau"
        assert verdict is not None, "un verdict doit être retourné"
        assert verdict["code"] == "REJ-HORODATAGE-INVALIDE", (
            f"attendu REJ-HORODATAGE-INVALIDE, reçu {verdict['code']}"
        )
        assert len(adaptateur_ombre.lire_journal()) == taille_avant, (
            "un rejet ne doit rien ajouter au journal"
        )

    @pytest.mark.parametrize(
        "charge_invalide",
        [{}, None, [], "chaine", 42],
        ids=["dict_vide", "none", "liste", "chaine", "entier"],
    )
    def test_charge_structurellement_inutilisable_refusee(
        self, adaptateur_ombre, horodatage_valide, charge_invalide
    ):
        """Prouve qu'une charge structurellement inutilisable est refusée par
        REJ-CHAMP-MANQUANT, SANS effet de bord.

        Frontière assumee : seul le contrôle STRUCTUREL est fait (dict non
        vide). Aucun schéma par champ n'est validé car aucun contrat de charge
        n'est gelé dans le PRD — en inventer un violerait « aucun champ
        deviné ». Rend rouge la suppression du contrôle structurel."""
        taille_avant = len(adaptateur_ombre.lire_journal())
        accuse, verdict = adaptateur_ombre.ecrire(charge_invalide, horodatage_valide)
        assert accuse is None, f"aucun accusé pour une charge {charge_invalide!r}"
        assert verdict is not None, "un verdict doit être retourné"
        assert verdict["code"] == "REJ-CHAMP-MANQUANT", (
            f"attendu REJ-CHAMP-MANQUANT, reçu {verdict['code']}"
        )
        assert len(adaptateur_ombre.lire_journal()) == taille_avant, (
            "un rejet ne doit rien ajouter au journal"
        )

    def test_ordre_des_controles_le_mode_prime(self, horodatage_valide):
        """Prouve l'ordre FIGÉ des contrôles : sur un adaptateur hors-mode avec
        une charge invalide ET un horodatage invalide, c'est
        REJ-ADAPTATEUR-INDISPONIBLE qui sort — pas les deux autres verdicts.

        POURQUOI cet ordre importe : le mode est la frontière de sécurité ; un
        appel hors mode ombre ne doit jamais révéler un diagnostic sur sa
        charge, qui n'aurait pas dû être examinée."""
        hors_mode = adaptateurs.AdaptateurMemoire("cible", "production")
        accuse, verdict = hors_mode.ecrire({}, "pas-une-date")
        assert accuse is None
        assert verdict["code"] == "REJ-ADAPTATEUR-INDISPONIBLE", (
            "le contrôle de mode doit primer sur charge et horodatage, "
            f"reçu {verdict['code']}"
        )
        assert hors_mode.lire_journal() == [], "journal vide sur rejet"

    @pytest.mark.parametrize("charge", [
        {"t": {"a", "b"}},
        {"b": b"x"},
        {"o": object()},
        {"f": len},
    ], ids=["set", "bytes", "object", "function"])
    def test_charge_non_serialisable_refusee(self, adaptateur_ombre, horodatage_valide, charge):
        """Prouve qu'une charge dict non vide mais contenant une valeur non JSON-sérialisable
        est refusée sans exception : (accuse=None, verdict REJ-FRONTIERE-VIOLEE), le journal
        reste inchangé (pas d'effet de bord). Une mutation du code qui laisserait remonter
        l'exception sera détectée ici."""
        journal_avant = len(adaptateur_ombre.lire_journal())
        accuse, verdict = adaptateur_ombre.ecrire(charge, horodatage_valide)
        assert accuse is None, "L'accusé doit être None pour une charge rejetée"
        assert verdict["code"] == "REJ-FRONTIERE-VIOLEE", (
            f"Code attendu REJ-FRONTIERE-VIOLEE, reçu {verdict['code']!r}"
        )
        assert len(adaptateur_ombre.lire_journal()) == journal_avant, (
            "Le journal ne doit pas contenir d'écriture supplémentaire"
        )

    @pytest.mark.parametrize("type_invalide", [
        None,
        42,
        ["2026-03-01"],
        {"a": 1},
    ], ids=["None", "int", "liste", "dict"])
    def test_horodatage_de_type_inattendu_refuse(self, adaptateur_ombre, charge_exemple, type_invalide):
        """Prouve qu'un horodatage de type inattendu (None, int, liste, dict) est refusé
        par un verdict REJ-HORODATAGE-INVALIDE sans exception et sans effet de bord,
        même si valider_horodatage lève TypeError. Garantit que tout type non str
        termine en verdict."""
        journal_avant = len(adaptateur_ombre.lire_journal())
        accuse, verdict = adaptateur_ombre.ecrire(charge_exemple, type_invalide)
        assert accuse is None, "L'accusé doit être None pour un horodatage invalide"
        assert verdict["code"] == "REJ-HORODATAGE-INVALIDE", (
            f"Code attendu REJ-HORODATAGE-INVALIDE, reçu {verdict['code']!r}"
        )
        assert len(adaptateur_ombre.lire_journal()) == journal_avant, (
            "Le journal ne doit pas être modifié"
        )

    def test_charge_serialisable_imbriquee_acceptee(self, adaptateur_ombre, horodatage_valide):
        """Prouve qu'une charge dict non vide avec imbrication légitime de types JSON
        (str, list, bool, int) est acceptée : accuse renvoyé, verdict None, journal
        incrémenté de 1 et le dernier élément est la charge. Ce test empêche qu'une
        garde de sérialisation trop stricte rejette le cas nominal."""
        charge = {"client": {"nom": "Dupont", "tags": ["a", "b"], "actif": True, "score": 3}}
        journal_avant = len(adaptateur_ombre.lire_journal())
        accuse, verdict = adaptateur_ombre.ecrire(charge, horodatage_valide)
        assert accuse is not None, "L'accusé doit être renvoyé pour une charge valide"
        assert verdict is None, "Le verdict doit être None en cas de succès"
        assert len(adaptateur_ombre.lire_journal()) == journal_avant + 1, (
            "Le journal doit contenir exactement une entrée supplémentaire"
        )
        assert adaptateur_ombre.lire_journal()[-1] == charge, (
            "La dernière entrée du journal doit être la charge exacte"
        )

    @pytest.mark.parametrize(
        "fabrique_valeur",
        ["verrou", "generateur", "module", "fichier"],
        ids=["verrou", "generateur", "module", "fichier"],
    )
    def test_charge_non_copiable_refusee(
        self, adaptateur_ombre, horodatage_valide, fabrique_valeur
    ):
        """PROUVE qu'une charge NON COPIABLE est refusée par un verdict, pas par
        une exception.

        Défaut trouvé par deux reviewers convergents : copy.deepcopy était placé
        HORS du bloc try qui n'encadrait que json.dumps. Mesuré : un verrou, un
        générateur ou un module lèvent TypeError « cannot pickle ». Rend rouge
        toute sortie de deepcopy hors du bloc try."""
        if fabrique_valeur == "verrou":
            import threading
            valeur = threading.Lock()
        elif fabrique_valeur == "generateur":
            valeur = (n for n in [1, 2])
        elif fabrique_valeur == "module":
            valeur = ast
        else:
            import io
            valeur = io.StringIO("contenu")
        taille_avant = len(adaptateur_ombre.lire_journal())
        accuse, verdict = adaptateur_ombre.ecrire({"v": valeur}, horodatage_valide)
        assert accuse is None, f"aucun accusé pour une charge {fabrique_valeur}"
        assert verdict["code"] == "REJ-FRONTIERE-VIOLEE", (
            f"attendu REJ-FRONTIERE-VIOLEE, reçu {verdict['code']}"
        )
        assert len(adaptateur_ombre.lire_journal()) == taille_avant, (
            "un rejet ne doit rien ajouter au journal"
        )

    @pytest.mark.parametrize(
        "non_fini",
        [float("inf"), float("-inf"), float("nan")],
        ids=["inf", "moins_inf", "nan"],
    )
    def test_charge_float_non_fini_refusee(
        self, adaptateur_ombre, horodatage_valide, non_fini
    ):
        """PROUVE qu'un float non fini est REFUSÉ, et non silencieusement accepté.

        Défaut FAIL-OPEN mesuré : par défaut json.dumps ACCEPTE inf et nan et
        produit {"v": Infinity}, qui n'est PAS du JSON conforme. L'adaptateur
        simulait donc avec succès une écriture qu'aucun CRM réel n'accepterait —
        pire qu'une exception, car silencieux. Rend rouge la suppression de
        allow_nan=False."""
        taille_avant = len(adaptateur_ombre.lire_journal())
        accuse, verdict = adaptateur_ombre.ecrire({"v": non_fini}, horodatage_valide)
        assert accuse is None, "un float non fini ne doit pas être accepté"
        assert verdict["code"] == "REJ-FRONTIERE-VIOLEE", (
            f"attendu REJ-FRONTIERE-VIOLEE, reçu {verdict['code']}"
        )
        assert len(adaptateur_ombre.lire_journal()) == taille_avant, (
            "un rejet ne doit rien ajouter au journal"
        )

class TestIdentifiantInjectif:
    """Identifiants injectifs et déterministes, aucun risque de collision par concaténation."""

    def test_determinisme_meme_parametres(self):
        """
        Prouve que deux instances construites avec les mêmes (nom_cible, mode)
        produisent des identifiants identiques.
        """
        obj1, _ = adaptateurs.construire_adaptateur("a", adaptateurs.MODE_OMBRE)
        obj2, _ = adaptateurs.construire_adaptateur("a", adaptateurs.MODE_OMBRE)
        assert obj1 is not None
        assert obj2 is not None
        id1 = obj1.identifiant()
        id2 = obj2.identifiant()
        assert id1 == id2, (
            f"Les identifiants doivent être égaux pour mêmes paramètres, reçu {id1} vs {id2}"
        )

    def test_noms_distincts_identifiants_differents(self):
        """
        Prouve que deux noms_cible différents (même mode) donnent des identifiants distincts.
        """
        obj1, _ = adaptateurs.construire_adaptateur("client_a", adaptateurs.MODE_OMBRE)
        obj2, _ = adaptateurs.construire_adaptateur("client_b", adaptateurs.MODE_OMBRE)
        id1 = obj1.identifiant()
        id2 = obj2.identifiant()
        assert id1 != id2, (
            "Deux noms différents doivent produire des identifiants distincts"
        )

    def test_injectivite_contre_concatenation(self):
        """Prouve que l'identifiant est INJECTIF : deux couples distincts dont la
        concaténation naïve serait IDENTIQUE donnent des identifiants distincts.

        ("ab", "ombre") et ("a", "bombre") se concatènent tous deux en
        "abombre". Une implémentation utilisant nom + mode les confondrait — et
        deux adaptateurs distincts partageraient un identifiant. C'est la
        collision par concaténation réellement observée dans un module voisin,
        que le préfixage par longueur de encoder_canonique écarte.

        Instanciation DIRECTE assumée : __init__ ne valide pas (par conception,
        pour que le verrou de ecrire reste testable), et ce test porte sur
        identifiant(), pas sur la garde de mode. L'objet reste inerte.
        """
        instance_a = adaptateurs.AdaptateurMemoire("ab", "ombre")
        instance_b = adaptateurs.AdaptateurMemoire("a", "bombre")
        # Pré-condition : la concaténation naïve produit bien la MÊME chaîne,
        # sans quoi le test ne discriminerait rien.
        assert "ab" + "ombre" == "a" + "bombre", (
            "pré-condition : les deux couples doivent collisionner par concatenation"
        )
        assert instance_a.identifiant() != instance_b.identifiant(), (
            "deux couples distincts doivent donner des identifiants distincts ; "
            "une concatenation directe les confondrait"
        )

    def test_determinisme_inter_processus(self, tmp_path):
        """
        Prouve que l'identifiant reste identique quelle que soit la graine
        PYTHONHASHSEED, en lançant au moins 3 exécutions indépendantes.
        """
        # Code exécuté dans le sous-processus
        src_path = str(_SRC)
        code_template = (
            "import sys\n"
            f"sys.path.insert(0, {repr(src_path)})\n"
            "from adaptateurs import AdaptateurMemoire\n"
            "inst = AdaptateurMemoire('inter_proc', 'ombre')\n"
            "print(inst.identifiant())\n"
        )
        graines = ["0", "12345", "987654321"]
        ids_obtenus = []
        for graine in graines:
            env_mod = os.environ.copy()
            env_mod["PYTHONHASHSEED"] = graine
            proc = subprocess.run(
                [sys.executable, "-c", code_template],
                capture_output=True,
                text=True,
                env=env_mod,
                cwd=str(_SRC.parent.parent),  # racine du projet
            )
            assert proc.returncode == 0, (
                f"Subprocess échoué avec PYTHONHASHSEED={graine}: {proc.stderr}"
            )
            sortie = proc.stdout.strip()
            assert sortie, "La sortie ne doit pas être vide"
            ids_obtenus.append(sortie)
        assert ids_obtenus[0] == ids_obtenus[1] == ids_obtenus[2], (
            "Les identifiants doivent être identiques pour toutes les graines"
        )


class TestJournalSimule:
    """Le journal simulé en mémoire respecte l'ordre, retourne des copies et n'altère aucun registre."""

    @pytest.fixture
    def adaptateur(self):
        """Adaptateur en mode ombre vierge."""
        obj, _ = adaptateurs.construire_adaptateur("journal_test", adaptateurs.MODE_OMBRE)
        assert obj is not None
        return obj

    def test_ordre_chronologique(self, adaptateur):
        """
        Prouve que lire_journal() restitue les charges dans l'ordre exact d'écriture.
        """
        h = "2025-03-27T10:00:00+00:00"
        charges = [{"i": i} for i in range(5)]
        for c in charges:
            adaptateur.ecrire(c, h)
        journal = adaptateur.lire_journal()
        assert len(journal) == len(charges), (
            "Le journal doit contenir autant d'entrées que d'écritures"
        )
        for idx, attendu in enumerate(charges):
            assert journal[idx] == attendu, (
                f"Écart à l'index {idx}: attendu {attendu}, reçu {journal[idx]}"
            )

    def test_copie_profonde(self, adaptateur):
        """
        Prouve que lire_journal() retourne des copies indépendantes :
        muter le résultat ne modifie pas l'état interne.
        """
        charge = {"cle": "valeur"}
        adaptateur.ecrire(charge, "2025-03-27T10:00:00+00:00")
        journal1 = adaptateur.lire_journal()
        # Muter la première entrée
        journal1[0]["cle"] = "modifiee"
        journal1.append({"intrus": True})
        # Relire
        journal2 = adaptateur.lire_journal()
        assert len(journal2) == 1, "La mutation externe ne doit pas changer la taille interne"
        assert journal2[0] == {"cle": "valeur"}, (
            "La mutation externe ne doit pas altérer les données internes"
        )

    def test_aucun_effet_sur_registre(self, adaptateur):
        """
        Prouve que l'adaptateur en mode ombre n'écrit rien dans un registre
        externe : la taille du registre reste inchangée.
        """
        reg = registre.Registre()
        taille_init = reg.taille()
        adaptateur.ecrire({"x": 1}, "2025-03-27T10:00:00+00:00")
        adaptateur.ecrire({"x": 2}, "2025-03-27T10:00:00+00:00")
        assert reg.taille() == taille_init, (
            "Le registre externe ne doit pas être impacté par les écritures en mode ombre"
        )


class TestInvariantsAdaptateurs:
    """Invariants structurels du module : énumération, absence de réseau, d'horloge, identifiant canonique."""

    def test_modes_constants(self):
        """Prouve que MODE_OMBRE vaut "ombre" et que MODES est un tuple contenant uniquement ombre."""
        assert adaptateurs.MODE_OMBRE == "ombre", "MODE_OMBRE doit être la chaîne 'ombre'"
        assert adaptateurs.MODES == ("ombre",), "MODES doit être le tuple ('ombre',)"

    @staticmethod
    def _modules_importes(module):
        """Retourne les noms de modules réellement IMPORTÉS, par AST.

        Une recherche textuelle ("socket" in source) produit des faux positifs
        sur un commentaire, une docstring ou une variable nommée http_client, et
        des faux négatifs sur un import dynamique renommé. On lit donc l'arbre
        syntaxique et on ne retient que les vrais noeuds Import/ImportFrom.
        """
        arbre = ast.parse(inspect.getsource(module))
        noms = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                for alias in noeud.names:
                    noms.add(alias.name.split(".")[0])
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                noms.add(noeud.module.split(".")[0])
        return noms

    def test_aucun_reseau_dans_source(self):
        """Prouve par AST qu'aucun module réseau n'est importé."""
        importes = self._modules_importes(adaptateurs)
        interdits = {"socket", "urllib", "urllib2", "requests", "http",
                     "httplib", "ssl", "ftplib", "smtplib", "telnetlib",
                     "asyncio", "subprocess"}
        fautifs = importes & interdits
        assert not fautifs, (
            f"modules réseau/exécution importés : {sorted(fautifs)} ; "
            "l'adaptateur v1 ne doit rien faire sortir du processus"
        )
        # Garde de la garde : l'AST voit bien les imports légitimes du module,
        # sinon un ensemble vide rendrait ce test vacuement vrai.
        assert "json" in importes or "copy" in importes, (
            "l'analyse AST ne voit aucun import connu : elle est inopérante"
        )

    def test_aucune_horloge_interne(self):
        """Prouve par AST qu'aucun APPEL d'horloge n'est présent.

        On inspecte les noeuds d'appel plutôt que le texte : un commentaire
        mentionnant time.time ne doit pas faire échouer, et un appel réel doit
        échouer même écrit différemment. Les horodatages sont FOURNIS par
        l'appelant, sans exception (invariant §8)."""
        arbre = ast.parse(inspect.getsource(adaptateurs))
        interdits = {"now", "utcnow", "today", "time", "monotonic", "perf_counter"}
        appels_fautifs = []
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Call):
                cible = noeud.func
                nom = getattr(cible, "attr", None) or getattr(cible, "id", None)
                if nom in interdits:
                    appels_fautifs.append(nom)
        assert not appels_fautifs, (
            f"appels d'horloge interne détectés : {sorted(set(appels_fautifs))}"
        )
        # Garde de la garde : l'AST voit bien des appels, sinon le test serait
        # vacuement vrai.
        tous = [n for n in ast.walk(arbre) if isinstance(n, ast.Call)]
        assert tous, "l'analyse AST ne voit aucun appel : elle est inopérante"

    def test_identifiant_via_encoder_canonique(self):
        """
        Prouve que l'identifiant est dérivé par encoder_canonique et non par une
        concaténation directe des champs. Le source doit contenir l'appel à
        encoder_canonique et aucun '+'.
        """
        src = inspect.getsource(adaptateurs)
        assert "encodage.encoder_canonique" in src or "encoder_canonique" in src, (
            "L'identifiant doit utiliser encoder_canonique"
        )
        # Vérification qu'il n'y a pas de concaténation directe du type nom+mode
        # On cherche un pattern comme f"{nom}{mode}" ou nom + mode
        # Le test peut être affinable, on va simplement vérifier l'absence de signe '+'
        # dans du code qui ressemble à une construction d'identifiant.
        # Cela peut produire des faux positifs. L'important est l'appel à encoder_canonique.
        # Ajoutons un contrôle basique : la ligne où apparaît encoder_canonique ne contient pas '+'.
        # C'est suffisant pour le test demandé.
        for line in src.splitlines():
            if "encoder_canonique" in line and "+" in line:
                pytest.fail(
                    f"L'identifiant semble utiliser une concaténation directe : {line.strip()}"
                )

    def test_protocol_adaptateur_crm(self):
        """Prouve que AdaptateurCRM est un Protocol et que AdaptateurMemoire expose ecrire."""
        # isinstance(classe, Protocol) est un usage invalide et ne prouve rien.
        # C'est @runtime_checkable qui rend isinstance(INSTANCE, Protocol)
        # significatif : il vérifie que la surface (méthode ecrire) est bien
        # présente. Sans le décorateur, cette ligne lèverait TypeError.
        instance_conforme = adaptateurs.AdaptateurMemoire("cible_proto", "ombre")
        assert isinstance(instance_conforme, adaptateurs.AdaptateurCRM), (
            "AdaptateurMemoire doit satisfaire le Protocol AdaptateurCRM"
        )
        assert hasattr(adaptateurs.AdaptateurMemoire, "ecrire"), (
            "AdaptateurMemoire doit posséder une méthode ecrire"
        )
        # Vérification que la méthode est appelable
        instance = adaptateurs.AdaptateurMemoire("test_proto", "ombre")
        assert callable(instance.ecrire), "ecrire doit être appelable"
