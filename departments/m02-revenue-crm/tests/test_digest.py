import json
import subprocess
import sys
from pathlib import Path

import pytest
from m2_revenue_crm import digest, doublons, ingestion, registre, statuts

_SRC = Path(__file__).resolve().parents[1] / "src"
_PKG = _SRC / "m2_revenue_crm"  # répertoire du paquet, pour les scans de sources


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _contrat_de_base(lead_id, horodatage):
    """Contrat gelé minimal valide, aucun prix ni date d'exécution."""
    return {
        "lead_id": lead_id,
        "conversation_id": "conv-" + lead_id,
        "contact": {"nom": "Jean", "telephone": "0600000000", "courriel": "j@e.m"},
        "type_travaux": "renovation_totale",
        "ville": "Lyon",
        "urgence_declaree": True,
        "canal": "telephone",
    }


def _ingerer_lead(reg, lead_id, horodatage, **surcharges):
    """Ingère un lead avec succès garanti, retourne l'accusé."""
    contrat = _contrat_de_base(lead_id, horodatage)
    contrat.update(surcharges)
    # ingestion.ingerer attend (contrat, registre_cible, horodatage)
    accuse, verdict = ingestion.ingerer(contrat, reg, horodatage)
    assert verdict is None, f"Ingestion échouée pour {lead_id}: {verdict}"
    return accuse


def _horodatage(date_str, heure="00:00:00"):
    """Retourne une chaîne ISO-8601 avec fuseau +00:00."""
    return f"{date_str}T{heure}+00:00"


def _lignes_section(digest_texte, entete):
    """Retourne les lignes (sans indentation) de la section nommée du digest.

    On ne peut PAS chercher un lead_id dans tout le digest pour tester son statut
    d'orphelin : un lead nouveau apparaît toujours dans [EN_ATTENTE]. Il faut
    isoler la section [ORPHELINS] pour vérifier l'appartenance réelle.
    """
    lignes = digest_texte.split("\n")
    dedans = False
    resultat = []
    for ligne in lignes:
        if ligne.startswith("[") and ligne.endswith("]"):
            dedans = (ligne == entete)
            continue
        if dedans and ligne.strip():
            resultat.append(ligne.strip())
    return resultat


# ---------------------------------------------------------------------------
# TestDeterminisme
# ---------------------------------------------------------------------------
class TestDeterminisme:
    """Prouve que le digest est déterministe et indépendant de l'ordre d'ingestion."""

    def test_meme_registre_deux_appels_donnent_meme_chaine(self):
        """Deux appels successifs sur le même registre produisent une chaîne byte-identique."""
        reg = registre.Registre()
        h1 = _horodatage("2026-03-01")
        _ingerer_lead(reg, "A", h1)
        date_jour = "2026-03-01"
        prod = _horodatage("2026-03-02", "12:00:00")
        d1 = digest.produire_digest(reg, date_jour, prod)
        d2 = digest.produire_digest(reg, date_jour, prod)
        assert d1 == d2, "Deux appels identiques sur le même registre doivent donner le même digest"

    def test_ordre_ingestion_indifferent(self):
        """Deux registres nourris avec les mêmes leads dans des ordres différents donnent le même digest."""
        date_jour = "2026-03-01"
        prod = _horodatage("2026-03-02", "12:00:00")
        h_A = _horodatage("2026-03-01", "08:00:00")
        h_B = _horodatage("2026-03-01", "09:00:00")

        reg1 = registre.Registre()
        _ingerer_lead(reg1, "A", h_A)
        _ingerer_lead(reg1, "B", h_B)

        reg2 = registre.Registre()
        _ingerer_lead(reg2, "B", h_B)
        _ingerer_lead(reg2, "A", h_A)

        d1 = digest.produire_digest(reg1, date_jour, prod)
        d2 = digest.produire_digest(reg2, date_jour, prod)
        assert d1 == d2, "Le digest ne doit pas dépendre de l'ordre d'ingestion"

    def test_determinisme_inter_processus_pythonhashseed_varie(self):
        """Digest identique entre processus pour plusieurs graines de PYTHONHASHSEED."""
        date_jour = "2026-03-01"
        prod = _horodatage("2026-03-02", "12:00:00")
        h1 = _horodatage("2026-03-01", "08:00:00")
        h2 = _horodatage("2026-03-01", "09:00:00")

        reg_local = registre.Registre()
        _ingerer_lead(reg_local, "L1", h1)
        _ingerer_lead(reg_local, "L2", h2)
        digest_local = digest.produire_digest(reg_local, date_jour, prod)
        assert len(digest_local) > 0, "Le digest local ne doit pas être vide"

        # Sérialise les entrées pour le sous-processus
        entrees = reg_local.lire()
        entrees_json = json.dumps(entrees, ensure_ascii=False)

        prog = (
            "import sys, json\n"
            "from pathlib import Path\n"
            "_SRC = Path('" + str(_SRC) + "')\n"
            "if not _SRC.exists():\n"
            "    sys.exit(2)\n"
            "if str(_SRC) not in sys.path:\n"
            "    sys.path.insert(0, str(_SRC))\n"
            "from m2_revenue_crm import registre, digest\n"
            "reg = registre.Registre()\n"
            "for entree in json.loads(sys.argv[1]):\n"
            "    reg.ajouter(entree)\n"
            "d = digest.produire_digest(reg, sys.argv[2], sys.argv[3])\n"
            "print(d, end='')\n"
        )

        graines = ["42", "7", "999"]
        for graine in graines:
            env = {"PYTHONHASHSEED": graine, "PYTHONPATH": str(_SRC)}
            res = subprocess.run(
                [sys.executable, "-c", prog, entrees_json, date_jour, prod],
                capture_output=True,
                text=True,
                env={**env, "PATH": sys.executable},  # PATH pas critique
                cwd=str(_SRC.parent),  # pour que les imports relatifs fonctionnent
            )
            assert res.returncode == 0, f"Subprocess échoué (PYTHONHASHSEED={graine}): {res.stderr}"
            assert res.stdout == digest_local, f"Digest différent avec PYTHONHASHSEED={graine}"


# ---------------------------------------------------------------------------
# TestExhaustivite
# ---------------------------------------------------------------------------
class TestExhaustivite:
    """Prouve que la section « en attente » est complète et triée."""

    def test_nouveau_et_qualifie_apparaissent(self):
        """Les leads nouveau et qualifie sont présents dans la section en attente."""
        reg = registre.Registre()
        h1 = _horodatage("2026-03-01", "08:00:00")
        h2 = _horodatage("2026-03-01", "09:00:00")
        _ingerer_lead(reg, "L1", h1)
        _ingerer_lead(reg, "L2", h2)
        # Assigner un owner et transition vers qualifie pour L2
        statuts.transitionner(
            "L2", "qualifie", reg, _horodatage("2026-03-01", "10:00:00"),
            owner="Alice", prochaine_action={"description": "Suivi", "echeance": "2026-03-20T09:00:00+00:00"}
        )
        date_jour = "2026-03-01"
        prod = _horodatage("2026-03-02", "12:00:00")
        d = digest.produire_digest(reg, date_jour, prod)
        assert "L1" in d
        assert "L2" in d

    @pytest.mark.parametrize("statut_final", ["converti", "perdu"],
                             ids=["converti", "perdu"])
    def test_statuts_finis_n_apparaissent_pas(self, statut_final):
        """Un lead converti ou perdu n'est pas dans « en attente »."""
        reg = registre.Registre()
        h1 = _horodatage("2026-03-01", "08:00:00")
        _ingerer_lead(reg, "Lfin", h1)
        # On doit d'abord le faire passer en qualifie pour pouvoir le convertir/perdre
        _, vq = statuts.transitionner(
            "Lfin", "qualifie", reg, _horodatage("2026-03-01", "09:00:00"),
            owner="Bob",
            prochaine_action={"description": "Suivi", "echeance": "2026-03-20T09:00:00+00:00"}
        )
        assert vq is None, f"transition vers qualifie a échoué : {vq}"
        if statut_final == "converti":
            _, v = statuts.transitionner(
                "Lfin", "converti", reg, _horodatage("2026-03-02", "10:00:00"),
                reference_devis_m3="DEV-1")
        else:  # perdu
            _, v = statuts.transitionner(
                "Lfin", "perdu", reg, _horodatage("2026-03-02", "10:00:00"),
                motif="abandon client")
        assert v is None, f"transition vers {statut_final} a échoué : {v}"
        d = digest.produire_digest(reg, "2026-03-02", _horodatage("2026-03-02", "12:00:00"))
        assert "Lfin" not in d, f"Lead {statut_final} ne doit pas apparaître dans le digest"

    def test_tri_par_date_puis_lead_id(self):
        """Les leads en attente sont triés par date d'ingestion puis lead_id."""
        reg = registre.Registre()
        h_mar1 = _horodatage("2026-03-01", "08:00:00")
        h_mar2 = _horodatage("2026-03-02", "08:00:00")
        h_mar3 = _horodatage("2026-03-03", "08:00:00")
        # Ingestion dans le désordre
        _ingerer_lead(reg, "C", h_mar3)
        _ingerer_lead(reg, "A", h_mar1)
        _ingerer_lead(reg, "B", h_mar2)
        d = digest.produire_digest(reg, "2026-03-03", _horodatage("2026-03-03", "12:00:00"))
        pos_A = d.index("A")
        pos_B = d.index("B")
        pos_C = d.index("C")
        assert pos_A < pos_B < pos_C, "Le tri doit être par date d'ingestion"

    def test_departage_meme_date_par_lead_id(self):
        """Deux leads avec même date d'ingestion sont départagés par lead_id."""
        reg = registre.Registre()
        h = _horodatage("2026-03-01", "08:00:00")
        _ingerer_lead(reg, "Z", h)
        _ingerer_lead(reg, "A", h)
        d = digest.produire_digest(reg, "2026-03-01", _horodatage("2026-03-01", "12:00:00"))
        pos_A = d.index("A")
        pos_Z = d.index("Z")
        assert pos_A < pos_Z, "Lead A doit précéder Z à date égale"

    def test_leads_en_attente_sont_tries_par_date_puis_id(self):
        """PROUVE que les leads en attente sont triés par date d’ingestion
        puis par lead_id. Rend rouge toute suppression du critère de tri
        (date, lead_id) sur cette section."""
        reg = registre.Registre()
        # Ingestion dans un ordre différent pour forcer le tri
        _ingerer_lead(reg, "Zz", _horodatage("2026-03-01", "08:00:00"))
        _ingerer_lead(reg, "Aa", _horodatage("2026-03-01", "08:00:00"))
        _ingerer_lead(reg, "Mm", _horodatage("2026-03-03", "08:00:00"))
        # On les laisse tous en statut nouveau (pas de transition)
        d = digest.produire_digest(reg, "2026-03-04", "2026-03-04T12:00:00+00:00")
        lignes = _lignes_section(d, "[EN_ATTENTE]")
        # Extraction du lead_id (premier token de chaque ligne)
        ids = [ligne.split()[0] for ligne in lignes]
        assert ids == ["Aa", "Zz", "Mm"]


# ---------------------------------------------------------------------------
# TestOrphelins
# ---------------------------------------------------------------------------
class TestOrphelins:
    """Prouve la détection des leads orphelins selon le seuil strict de 48 heures."""

    def test_plus_de_48h_sans_owner_nouveau_est_orphelin(self):
        """Lead nouveau sans owner ingéré il y a > 48h est orphelin."""
        reg = registre.Registre()
        ing = "2026-03-01T00:00:00+00:00"
        _ingerer_lead(reg, "O1", ing)
        prod = "2026-03-03T01:00:00+00:00"  # 49h plus tard
        d = digest.produire_digest(reg, "2026-03-03", prod)
        assert "O1" in _lignes_section(d, "[ORPHELINS]"), "> 48h sans owner : orphelin"

    def test_exactement_48h_n_est_pas_orphelin(self):
        """Exactement 48h après ingestion, le lead n'est PAS orphelin (seuil strict)."""
        reg = registre.Registre()
        ing = "2026-03-01T00:00:00+00:00"
        _ingerer_lead(reg, "O2", ing)
        prod = "2026-03-03T00:00:00+00:00"  # pile 48h
        d = digest.produire_digest(reg, "2026-03-03", prod)
        assert "O2" not in _lignes_section(d, "[ORPHELINS]"), "exactement 48h : pas orphelin"

    def test_moins_de_48h_n_est_pas_orphelin(self):
        """Moins de 48h : pas orphelin."""
        reg = registre.Registre()
        ing = "2026-03-02T00:00:00+00:00"
        _ingerer_lead(reg, "O3", ing)
        prod = "2026-03-03T23:00:00+00:00"  # 47h
        d = digest.produire_digest(reg, "2026-03-03", prod)
        assert "O3" not in _lignes_section(d, "[ORPHELINS]"), "moins de 48h : pas orphelin"

    def test_qualifie_ancien_avec_owner_n_est_pas_orphelin(self):
        """Un lead qualifié (donc porteur d'un owner via sa transition) ingéré il
        y a plus de 48h n'est PAS orphelin : l'orphelinage ne vise que les leads
        NOUVEAUX sans owner. C'est la conjonction statut=nouveau ET pas d'owner
        qui est exercée, pas le seul délai."""
        reg = registre.Registre()
        _ingerer_lead(reg, "OQ", "2026-02-01T00:00:00+00:00")
        _, v = statuts.transitionner(
            "OQ", "qualifie", reg, "2026-02-01T09:00:00+00:00",
            owner="Alice",
            prochaine_action={"description": "Suivi", "echeance": "2026-02-20T09:00:00+00:00"},
        )
        assert v is None, f"transition vers qualifie a échoué : {v}"
        prod = "2026-02-04T12:00:00+00:00"  # > 48h après l'ingestion
        d = digest.produire_digest(reg, "2026-02-04", prod)
        assert "OQ" not in _lignes_section(d, "[ORPHELINS]"), (
            "un lead qualifié (avec owner) ne doit jamais être orphelin, même après 48h"
        )
        assert "OQ" in d, "il reste en revanche listé en attente (statut qualifie)"

    def test_qualifie_n_est_pas_orphelin(self):
        """Lead qualifie (donc avec owner) après 60h n'est PAS orphelin."""
        reg = registre.Registre()
        ing = "2026-02-01T00:00:00+00:00"
        _ingerer_lead(reg, "Q1", ing)
        statuts.transitionner(
            "Q1", "qualifie", reg, "2026-02-01T01:00:00+00:00",
            owner="Bob", prochaine_action={"description": "Suivi", "echeance": "2026-03-20T09:00:00+00:00"}
        )
        prod = "2026-02-03T12:00:00+00:00"  # >48h
        d = digest.produire_digest(reg, "2026-02-03", prod)
        assert "Q1" not in _lignes_section(d, "[ORPHELINS]")

    def test_horloge_entierement_injectee(self):
        """Un même registre avec deux horodatages de production différents donne des orphelins différents."""
        reg = registre.Registre()
        ing = "2026-03-01T00:00:00+00:00"
        _ingerer_lead(reg, "Var", ing)
        # prod1 pile < 48h
        prod1 = "2026-03-02T23:59:00+00:00"
        d1 = digest.produire_digest(reg, "2026-03-02", prod1)
        assert "Var" not in _lignes_section(d1, "[ORPHELINS]"), "< 48h : pas orphelin"
        # prod2 > 48h
        prod2 = "2026-03-03T01:00:00+00:00"
        d2 = digest.produire_digest(reg, "2026-03-03", prod2)
        assert "Var" in _lignes_section(d2, "[ORPHELINS]"), "> 48h : orphelin"

    def test_orphelin_seul_le_lead_nouveau_sans_owner_est_signale(self):
        """Sur un même horodatage de production > 48h, distingue les trois cas :
        un lead NOUVEAU sans owner est orphelin ; un lead QUALIFIÉ (donc avec
        owner) ne l'est pas. La condition `owner == "-"` de l'implémentation est
        une garde DÉFENSIVE structurellement redondante avec `statut ==
        "nouveau"` — un lead nouveau n'acquiert jamais d'owner (l'owner ne
        s'obtient qu'en passant à qualifie, ce qui le sort de « nouveau »). Elle
        est conservée pour rester correcte si la machine à états évoluait, mais
        n'est pas isolable par un test tant que « nouveau + owner » est
        impossible — déclaré au reviewer, comme les deepcopy défensifs des
        stories précédentes."""
        reg = registre.Registre()
        horo_ingestion = _horodatage("2026-02-01", "00:00:00")
        _ingerer_lead(reg, "L_SANS_OWNER", horo_ingestion)
        _ingerer_lead(reg, "L_AVEC_OWNER", horo_ingestion)
        accuse, verdict = statuts.transitionner(
            "L_AVEC_OWNER", "qualifie", reg, _horodatage("2026-02-01", "09:00:00"),
            owner="Bob",
            prochaine_action={"description": "rappel", "echeance": "2026-02-05T09:00:00+00:00"}
        )
        assert verdict is None and accuse is not None, (
            f"transition vers qualifie a échoué : {verdict}"
        )
        d = digest.produire_digest(reg, "2026-02-04", "2026-02-04T12:00:00+00:00")
        orphelins = _lignes_section(d, "[ORPHELINS]")
        assert "L_SANS_OWNER" in orphelins, "nouveau sans owner > 48h : orphelin"
        assert "L_AVEC_OWNER" not in orphelins, "qualifié (avec owner) : jamais orphelin"

    def test_orphelins_sont_tries_par_id(self):
        """PROUVE que les orphelins sont triés par lead_id — de façon
        DISCRIMINANTE : les dates d'ingestion inversent l'ordre par id, donc le
        tri des orphelins par lead_id se distingue de l'ordre de la source
        (leads_en_attente, triée par date). Retirer le tri des orphelins donne
        alors [Zo, Al] ; le tri par id donne [Al, Zo]. Rend rouge la suppression
        de orphelins.sort()."""
        reg = registre.Registre()
        # Zo ingéré AVANT Al : dans leads_en_attente (tri par date), Zo précède Al.
        _ingerer_lead(reg, "Zo", _horodatage("2026-02-01", "00:00:00"))
        _ingerer_lead(reg, "Al", _horodatage("2026-02-02", "00:00:00"))
        # Production > 48h après les DEUX ingestions.
        d = digest.produire_digest(reg, "2026-02-05", "2026-02-05T12:00:00+00:00")
        orphelins = _lignes_section(d, "[ORPHELINS]")
        assert orphelins == ["Al", "Zo"], (
            "les orphelins doivent être triés par lead_id, pas par ordre de la "
            f"source triée par date ; obtenu {orphelins}"
        )


# ---------------------------------------------------------------------------
# TestDoublons
# ---------------------------------------------------------------------------
class TestDoublons:
    """Vérifie l'affichage des signalements de doublons dans le digest."""

    def test_signalement_en_attente_apparait(self):
        """Un signalement en_attente est listé dans la section doublons."""
        reg = registre.Registre()
        h = _horodatage("2026-03-01", "08:00:00")
        _ingerer_lead(reg, "A", h)
        _ingerer_lead(reg, "B", _horodatage("2026-03-01", "09:00:00"))
        sig, verdict = doublons.signaler(reg, "A", "B", _horodatage("2026-03-01", "10:00:00"))
        assert verdict is None
        d = digest.produire_digest(reg, "2026-03-01", _horodatage("2026-03-01", "12:00:00"))
        assert sig["signalement_id"] in d

    def test_signalement_arbitre_n_apparait_plus(self):
        """Après arbitrage distincts_confirmes, le signalement disparaît du digest."""
        reg = registre.Registre()
        h = _horodatage("2026-03-01", "08:00:00")
        _ingerer_lead(reg, "A", h)
        _ingerer_lead(reg, "B", _horodatage("2026-03-01", "09:00:00"))
        sig, _ = doublons.signaler(reg, "A", "B", _horodatage("2026-03-01", "10:00:00"))
        doublons.arbitrer(reg, sig["signalement_id"], "distincts_confirmes",
                          horodatage=_horodatage("2026-03-01", "11:00:00"))
        d = digest.produire_digest(reg, "2026-03-01", _horodatage("2026-03-01", "12:00:00"))
        assert sig["signalement_id"] not in d

    def test_tri_signalements(self):
        """Les signalements sont triés par identifiant."""
        reg = registre.Registre()
        h = _horodatage("2026-03-01", "08:00:00")
        _ingerer_lead(reg, "A", h)
        _ingerer_lead(reg, "B", h)
        _ingerer_lead(reg, "C", h)
        s1, _ = doublons.signaler(reg, "A", "B", _horodatage("2026-03-01", "10:00:00"))
        s2, _ = doublons.signaler(reg, "B", "C", _horodatage("2026-03-01", "10:01:00"))
        d = digest.produire_digest(reg, "2026-03-01", _horodatage("2026-03-01", "12:00:00"))
        idx1 = d.index(s1["signalement_id"])
        idx2 = d.index(s2["signalement_id"])
        assert idx1 < idx2, "Les signalement_id doivent être triés"


# ---------------------------------------------------------------------------
# TestInvariantsDigest
# ---------------------------------------------------------------------------
class TestInvariantsDigest:
    """Vérifie les propriétés structurelles du module digest."""

    def test_produire_digest_est_pur(self):
        """L'appel à produire_digest ne modifie pas le registre."""
        reg = registre.Registre()
        h = _horodatage("2026-03-01", "08:00:00")
        _ingerer_lead(reg, "A", h)
        taille_avant = reg.taille()
        tete_avant = reg.tete()
        digest.produire_digest(reg, "2026-03-01", _horodatage("2026-03-01", "12:00:00"))
        assert reg.taille() == taille_avant, "produire_digest ne doit pas ajouter d'entrées"
        assert reg.tete() == tete_avant, "produire_digest ne doit pas modifier la tête"

    def test_aucun_reseau_dans_digest(self):
        """Le fichier digest.py ne contient aucun import réseau."""
        fichier = _PKG / "digest.py"
        assert fichier.exists(), "digest.py doit exister"
        contenu = fichier.read_text(encoding="utf-8")
        interdits = ["socket", "urllib", "requests", "http"]
        for mot in interdits:
            assert mot not in contenu, f"digest.py ne doit pas contenir '{mot}'"

    def test_aucune_horloge_interne(self):
        """Aucune horloge système (datetime.now/time.time...) n'est utilisée dans digest.py."""
        fichier = _PKG / "digest.py"
        contenu = fichier.read_text(encoding="utf-8")
        horloges = ["datetime.now", "time.time", "date.today", "utcnow"]
        for mot in horloges:
            assert mot not in contenu, f"digest.py ne doit pas contenir '{mot}'"

    def test_constante_seuil_orphelin(self):
        """SEUIL_ORPHELIN_HEURES vaut 48."""
        assert digest.SEUIL_ORPHELIN_HEURES == 48

    def test_horodatage_production_sans_fuseau_est_refuse(self):
        """PROUVE que produire_digest REFUSE un horodatage de production naïf.

        Sans cette garde, datetime.astimezone retombe sur le fuseau LOCAL de la
        machine — une entrée ambiante que l'appelant n'a pas fournie. Mesuré sur
        un même registre avec le même horodatage naïf : orphelin vrai sous
        TZ=UTC, faux sous TZ=Pacific/Kiritimati. Fail-closed : on lève."""
        reg = registre.Registre()
        _ingerer_lead(reg, "NAIF", "2026-03-01T00:00:00+00:00")
        with pytest.raises(ValueError):
            digest.produire_digest(reg, "2026-03-03", "2026-03-03T01:00:00")

    def test_horodatage_production_non_parsable_est_refuse(self):
        """Une chaîne qui n'est pas un horodatage ISO-8601 est refusée."""
        reg = registre.Registre()
        _ingerer_lead(reg, "NP", "2026-03-01T00:00:00+00:00")
        with pytest.raises(ValueError):
            digest.produire_digest(reg, "2026-03-03", "pas-une-date")

    def test_sortie_identique_quel_que_soit_le_fuseau_de_la_machine(self):
        """PROUVE le déterminisme INTER-MACHINE : le même digest calculé sous
        trois TZ système différents est byte-identique. C'est la propriété que
        la garde de fuseau protège ; retirer la garde ET fournir un horodatage
        naïf ferait diverger ces sorties."""
        reg_local = registre.Registre()
        _ingerer_lead(reg_local, "T1", "2026-03-01T08:00:00+00:00")
        _ingerer_lead(reg_local, "T2", "2026-03-02T09:00:00+00:00")
        date_jour = "2026-03-04"
        prod = "2026-03-04T12:00:00+00:00"
        digest_local = digest.produire_digest(reg_local, date_jour, prod)
        assert len(digest_local) > 0, "le digest local ne doit pas être vide"
        entrees_json = json.dumps(reg_local.lire(), ensure_ascii=False)
        prog = (
            "import sys, json\n"
            "from pathlib import Path\n"
            "_SRC = Path(sys.argv[1])\n"
            "sys.path.insert(0, str(_SRC))\n"
            "from m2_revenue_crm import registre, digest\n"
            "reg = registre.Registre()\n"
            "for entree in json.loads(sys.argv[2]):\n"
            "    reg.ajouter(entree)\n"
            "print(digest.produire_digest(reg, sys.argv[3], sys.argv[4]), end='')\n"
        )
        for fuseau in ("UTC", "Pacific/Kiritimati", "Pacific/Midway"):
            res = subprocess.run(
                [sys.executable, "-c", prog, str(_SRC), entrees_json, date_jour, prod],
                capture_output=True, text=True,
                env={"TZ": fuseau, "PYTHONPATH": str(_SRC), "PATH": "/usr/bin:/bin"},
            )
            assert res.returncode == 0, (
                f"sous-processus TZ={fuseau} échoué : {res.stderr}"
            )
            assert res.stdout == digest_local, (
                f"digest différent sous TZ={fuseau} : le fuseau de la machine "
                "ne doit JAMAIS influencer la sortie"
            )


# ---------------------------------------------------------------------------
# TestCorrectifAuditDateJour — date_jour ne filtrait rien (bug d'audit)
# ---------------------------------------------------------------------------
class TestCorrectifAuditDateJour:
    """PROUVE que date_jour filtre réellement l'état « à la date » demandée :
    avant le correctif, date_jour ne servait qu'à l'en-tête du digest et un
    lead ingéré APRÈS date_jour apparaissait quand même, comme si le digest
    n'avait aucune notion de période."""

    def test_lead_ingere_apres_date_jour_est_absent(self):
        """Un lead ingéré strictement après date_jour ne doit apparaître dans
        aucune section : il n'existait pas encore « à la date » du digest."""
        reg = registre.Registre()
        _ingerer_lead(reg, "Futur", _horodatage("2026-03-10", "08:00:00"))
        d = digest.produire_digest(reg, "2026-03-05", _horodatage("2026-03-05", "12:00:00"))
        assert "Futur" not in d, (
            "un lead ingéré après date_jour ne doit pas apparaître dans le digest "
            "de cette date : date_jour doit filtrer, pas seulement s'afficher"
        )

    def test_lead_ingere_avant_ou_a_date_jour_reste_present(self):
        """Un lead ingéré le jour même ou avant date_jour reste présent
        (non-régression : date_jour ne doit pas devenir trop strict)."""
        reg = registre.Registre()
        _ingerer_lead(reg, "Present", _horodatage("2026-03-05", "08:00:00"))
        d = digest.produire_digest(reg, "2026-03-05", _horodatage("2026-03-05", "12:00:00"))
        assert "Present" in d

    def test_transition_posterieure_a_date_jour_ignoree_statut_recalcule(self):
        """Un lead qualifié APRÈS date_jour doit être vu, à cette date-là, dans
        son statut antérieur (nouveau) : la transition future ne doit pas fuiter
        dans un digest produit pour une date plus ancienne."""
        reg = registre.Registre()
        _ingerer_lead(reg, "L1", _horodatage("2026-03-01", "08:00:00"))
        statuts.transitionner(
            "L1", "qualifie", reg, _horodatage("2026-03-10", "09:00:00"),
            owner="Alice",
            prochaine_action={"description": "Suivi", "echeance": "2026-03-20T09:00:00+00:00"},
        )
        d = digest.produire_digest(reg, "2026-03-02", _horodatage("2026-03-02", "12:00:00"))
        lignes = _lignes_section(d, "[EN_ATTENTE]")
        assert any(ligne.startswith("L1 ") and "statut=nouveau" in ligne for ligne in lignes), (
            f"L1 doit apparaître avec statut=nouveau (sa transition vers qualifie "
            f"est postérieure à date_jour) ; sections en_attente obtenues : {lignes}"
        )

    def test_signalement_posterieur_a_date_jour_absent(self):
        """Un signalement de doublon créé après date_jour n'apparaît pas dans un
        digest produit pour une date antérieure."""
        reg = registre.Registre()
        _ingerer_lead(reg, "A", _horodatage("2026-03-01", "08:00:00"))
        _ingerer_lead(reg, "B", _horodatage("2026-03-01", "09:00:00"))
        sig, verdict = doublons.signaler(reg, "A", "B", _horodatage("2026-03-10", "10:00:00"))
        assert verdict is None
        d = digest.produire_digest(reg, "2026-03-02", _horodatage("2026-03-02", "12:00:00"))
        assert sig["signalement_id"] not in d
