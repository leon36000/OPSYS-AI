import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import m4_field_ops.cedule as cedule_mod
import m4_field_ops.encodage as encodage_mod

import copy
from datetime import datetime

# ------------------------------------------------------------------ #
# fixtures de base (utilisées et modifiées localement dans les tests)
# ------------------------------------------------------------------ #

SEL = "sel-de-test"
SEL_ALT = "autre-sel"

VILLES_CLAIRES = ["Lyon", "Paris", "Marseille"]

def _interventions_basiques():
    """Retourne une copie fraîche d'une liste d'interventions valides."""
    return copy.deepcopy([
        {"intervention_id": "i1", "lead_id": "L001", "type_travaux": "renovation_totale", "ville": "Lyon"},
        {"intervention_id": "i2", "lead_id": "L002", "type_travaux": "extension", "ville": "Paris"},
        {"intervention_id": "i3", "lead_id": "L003", "type_travaux": "isolation_thermique", "ville": "Marseille"},
        {"intervention_id": "i4", "lead_id": "L004", "type_travaux": "ravalement", "ville": "Lyon"},
        {"intervention_id": "i5", "lead_id": "L005", "type_travaux": "autre", "ville": "Paris"},
    ])

def _techniciens_basiques():
    return ["tech1", "tech2"]

def _fenetres_basiques():
    return [
        {"debut": "2025-06-02T08:00:00+00:00", "fin": "2025-06-02T12:00:00+00:00"},
        {"debut": "2025-06-03T08:00:00+00:00", "fin": "2025-06-03T12:00:00+00:00"},
    ]

# pour le test de fenêtres avec fuseaux différents
def _fenetres_fuseaux_contradictoires():
    """ chaîne '09:00+02:00' > '08:00+00:00' lexicographiquement,
        mais chronologiquement 09:00+02:00 = 07:00Z < 08:00Z """
    return [
        {"debut": "2025-06-02T09:00:00+02:00", "fin": "2025-06-02T13:00:00+02:00"},
        {"debut": "2025-06-02T08:00:00+00:00", "fin": "2025-06-02T12:00:00+00:00"},
    ]


# ================================================================== #
# 1. tokeniser_ville
# ================================================================== #
class TestTokeniserVille:

    def test_deterministe(self):
        t1 = cedule_mod.tokeniser_ville(SEL, "Lyon")
        t2 = cedule_mod.tokeniser_ville(SEL, "Lyon")
        assert t1 == t2
        assert t1 is not t2  # pas de cache mutable

    def test_villes_differentes_tokens_differents(self):
        t1 = cedule_mod.tokeniser_ville(SEL, "Paris")
        t2 = cedule_mod.tokeniser_ville(SEL, "Lyon")
        assert t1 != t2

    def test_sels_differents_tokens_differents(self):
        t1 = cedule_mod.tokeniser_ville(SEL, "Marseille")
        t2 = cedule_mod.tokeniser_ville("autre-grain", "Marseille")
        assert t1 != t2

    def test_egale_empreinte_encodage(self):
        ville = "Lyon"
        token = cedule_mod.tokeniser_ville(SEL, ville)
        expected = encodage_mod.empreinte("ville", SEL, ville)
        assert token == expected


# ================================================================== #
# 2. CA-M4-05 : déterminisme global
# ================================================================== #
class TestDeterminismeGlobal:

    def test_deux_appels_entrees_egales_sorties_strictement_egales(self):
        # Construire deux fois les entrées (objets distincts)
        intv1 = _interventions_basiques()
        tech1 = _techniciens_basiques()
        fen1 = _fenetres_basiques()

        intv2 = _interventions_basiques()
        tech2 = _techniciens_basiques()
        fen2 = _fenetres_basiques()

        c1, v1 = cedule_mod.generer_cedule(intv1, tech1, fen1, SEL)
        c2, v2 = cedule_mod.generer_cedule(intv2, tech2, fen2, SEL)

        assert v1 is None
        assert v2 is None
        assert c1 == c2


# ================================================================== #
# 3. tri triple discriminé
# ================================================================== #
class TestTriTriple:

    def test_ordre_selon_token_pas_selon_ville_claire(self):
        """Le tri porte sur le TOKEN, pas sur la ville en clair. Discriminant :
        deux villes dont l'ordre alphabétique des tokens est l'INVERSE de celui
        des noms — un tri sur la ville en clair produirait l'ordre opposé."""
        paires = [(a, b) for a in VILLES_CLAIRES for b in VILLES_CLAIRES if a < b]
        inversees = [
            (a, b) for a, b in paires
            if cedule_mod.tokeniser_ville(SEL, a) > cedule_mod.tokeniser_ville(SEL, b)
        ]
        assert inversees, (
            "aucune paire de villes n'a un ordre de tokens inverse de l'ordre en clair : "
            "le test ne serait pas discriminant"
        )
        ville_claire_avant, ville_claire_apres = inversees[0]
        token_avant = cedule_mod.tokeniser_ville(SEL, ville_claire_avant)
        token_apres = cedule_mod.tokeniser_ville(SEL, ville_claire_apres)
        assert token_avant > token_apres

        interventions = [
            {"intervention_id": "i_claire_premiere", "lead_id": "L001",
             "type_travaux": "renovation_totale", "ville": ville_claire_avant},
            {"intervention_id": "i_claire_seconde", "lead_id": "L002",
             "type_travaux": "renovation_totale", "ville": ville_claire_apres},
        ]
        techs = ["t"]
        fenetres = [
            {"debut": "2025-01-01T00:00:00+00:00", "fin": "2025-01-01T01:00:00+00:00"},
            {"debut": "2025-01-02T00:00:00+00:00", "fin": "2025-01-02T01:00:00+00:00"},
        ]
        c, verdict = cedule_mod.generer_cedule(interventions, techs, fenetres, SEL)
        assert verdict is None, f"cédule refusée : {verdict}"
        ordre = [a["intervention_id"] for a in c["assignations"]]
        assert ordre == ["i_claire_seconde", "i_claire_premiere"], (
            "l'ordre suit le token (croissant), pas la ville en clair"
        )
        assert c["assignations"][0]["ville_tokenisee"] == token_apres
        assert c["assignations"][1]["ville_tokenisee"] == token_avant

    def test_type_travaux_respecte(self):
        # Même ville, deux interventions avec type_travaux dans l'ordre inverse d'insertion
        # DISCRIMINANT sur DEUX plans : l'ordre trié contredit l'ordre d'INSERTION
        # (iZ inséré en premier arrive second) ET l'ordre par lead_id (L001 < L002
        # donnerait iZ en premier) — c'est donc bien le type_travaux qui décide,
        # et il décide AVANT le lead_id.
        interventions = [
            {"intervention_id": "iZ", "lead_id": "L001", "type_travaux": "isolation_thermique", "ville": "Lyon"},
            {"intervention_id": "iA", "lead_id": "L002", "type_travaux": "extension", "ville": "Lyon"},
        ]
        techs = ["t"]
        # DEUX fenêtres : capacité 1x2 = 2 pour deux interventions — sinon la
        # seconde tombe en non_cedulees et le test d'ORDRE n'observe qu'un seul
        # élément (entrée non discriminante, mesuré).
        fenetres = [
            {"debut": "2025-01-01T00:00:00+00:00", "fin": "2025-01-01T01:00:00+00:00"},
            {"debut": "2025-01-02T00:00:00+00:00", "fin": "2025-01-02T01:00:00+00:00"},
        ]
        c, verdict = cedule_mod.generer_cedule(interventions, techs, fenetres, SEL)
        assert verdict is None, f"cédule refusée : {verdict}"
        assert c["non_cedulees"] == [], "capacité suffisante : rien ne doit déborder"
        ordre = [a["intervention_id"] for a in c["assignations"]]
        # extension < isolation_thermique -> iA (extension) avant iZ
        assert ordre == ["iA", "iZ"]

    def test_lead_id_respecte(self):
        interventions = [
            {"intervention_id": "iBig", "lead_id": "L100", "type_travaux": "renovation_totale", "ville": "Marseille"},
            {"intervention_id": "iSmall", "lead_id": "L001", "type_travaux": "renovation_totale", "ville": "Marseille"},
        ]
        techs = ["t"]
        # DEUX fenêtres : capacité 1x2 = 2 pour deux interventions — sinon la
        # seconde tombe en non_cedulees et le test d'ORDRE n'observe qu'un seul
        # élément (entrée non discriminante, mesuré).
        fenetres = [
            {"debut": "2025-01-01T00:00:00+00:00", "fin": "2025-01-01T01:00:00+00:00"},
            {"debut": "2025-01-02T00:00:00+00:00", "fin": "2025-01-02T01:00:00+00:00"},
        ]
        c, verdict = cedule_mod.generer_cedule(interventions, techs, fenetres, SEL)
        assert verdict is None, f"cédule refusée : {verdict}"
        assert c["non_cedulees"] == [], "capacité suffisante : rien ne doit déborder"
        ordre = [a["intervention_id"] for a in c["assignations"]]
        # lead_id L001 < L100 -> iSmall avant iBig
        assert ordre == ["iSmall", "iBig"]


# ================================================================== #
# 4. indépendance de l'ordre d'insertion
# ================================================================== #
class TestOrdreInsertionIndependant:

    def test_ordre_insertion_different_meme_sortie(self):
        intv1 = [
            {"intervention_id": "i1", "lead_id": "L001", "type_travaux": "extension", "ville": "Paris"},
            {"intervention_id": "i2", "lead_id": "L002", "type_travaux": "isolation_thermique", "ville": "Lyon"},
            {"intervention_id": "i3", "lead_id": "L003", "type_travaux": "autre", "ville": "Marseille"},
        ]
        intv2 = [
            {"intervention_id": "i3", "lead_id": "L003", "type_travaux": "autre", "ville": "Marseille"},
            {"intervention_id": "i1", "lead_id": "L001", "type_travaux": "extension", "ville": "Paris"},
            {"intervention_id": "i2", "lead_id": "L002", "type_travaux": "isolation_thermique", "ville": "Lyon"},
        ]
        techs = ["t1", "t2"]
        fenetres = [{"debut": "2025-06-01T08:00:00+00:00", "fin": "2025-06-01T12:00:00+00:00"}]
        c1, _ = cedule_mod.generer_cedule(intv1, techs, fenetres, SEL)
        c2, _ = cedule_mod.generer_cedule(intv2, techs, fenetres, SEL)
        assert c1 == c2


# ================================================================== #
# 5. assignation ronde avec ressources limitées
# ================================================================== #
class TestAssignationRonde:

    def test_ronde_techniciens_fenetres_desordonnees_et_capacite_depassee(self):
        # 5 interventions, 2 techs désordonnés, 2 fenêtres désordonnées
        # On veut vérifier le round-robin et le non-ceduleage du dernier
        intvs = copy.deepcopy([
            {"intervention_id": "intv1", "lead_id": "L1", "type_travaux": "renovation_totale", "ville": "Paris"},
            {"intervention_id": "intv2", "lead_id": "L2", "type_travaux": "renovation_totale", "ville": "Paris"},
            {"intervention_id": "intv3", "lead_id": "L3", "type_travaux": "renovation_totale", "ville": "Paris"},
            {"intervention_id": "intv4", "lead_id": "L4", "type_travaux": "renovation_totale", "ville": "Paris"},
            {"intervention_id": "intv5", "lead_id": "L5", "type_travaux": "renovation_totale", "ville": "Paris"},
        ])
        # Tous même ville, même type, donc l'ordre sera par lead_id croissant:
        ordre_tri = sorted(intvs, key=lambda i: (cedule_mod.tokeniser_ville(SEL, i["ville"]), i["type_travaux"], i["lead_id"]))
        ids_ordre = [i["intervention_id"] for i in ordre_tri]

        techs_desordonnes = ["t2", "t1"]
        fens_desordonnees = [
            {"debut": "2025-06-03T08:00:00+00:00", "fin": "2025-06-03T12:00:00+00:00"},  # plus tard
            {"debut": "2025-06-02T08:00:00+00:00", "fin": "2025-06-02T12:00:00+00:00"},  # plus tôt
        ]

        c, verdict = cedule_mod.generer_cedule(intvs, techs_desordonnes, fens_desordonnees, SEL)
        assert verdict is None
        assert len(c["assignations"]) == 4
        assert len(c["non_cedulees"]) == 1

        # Techniciens triés : ["t1", "t2"]
        # Fenêtres triées : d'abord celle du 02 juin, puis 03 juin
        fen_attendue_debut = [a["fenetre"]["debut"] for a in c["assignations"]]
        # Les rangs 0 et 1 doivent avoir la fenêtre du 02 juin, les rangs 2 et 3 celle du 03 juin
        assert fen_attendue_debut[0] == "2025-06-02T08:00:00+00:00"
        assert fen_attendue_debut[1] == "2025-06-02T08:00:00+00:00"
        assert fen_attendue_debut[2] == "2025-06-03T08:00:00+00:00"
        assert fen_attendue_debut[3] == "2025-06-03T08:00:00+00:00"

        # Techniciens : rang0 -> t1, rang1 -> t2, rang2 -> t1, rang3 -> t2
        assert c["assignations"][0]["technicien_id"] == "t1"
        assert c["assignations"][1]["technicien_id"] == "t2"
        assert c["assignations"][2]["technicien_id"] == "t1"
        assert c["assignations"][3]["technicien_id"] == "t2"

        # Non-cedulee : doit être le dernier de l'ordre trié (ids_ordre[-1])
        non_ced = c["non_cedulees"][0]
        assert non_ced["intervention_id"] == ids_ordre[-1]
        assert "technicien_id" not in non_ced
        assert "fenetre" not in non_ced
        assert "ville_tokenisee" in non_ced
        assert non_ced["ville_tokenisee"] == cedule_mod.tokeniser_ville(SEL, ordre_tri[-1]["ville"])


# ================================================================== #
# 6. tri chronologique des fenêtres
# ================================================================== #
class TestTriFenetresChronologique:

    def test_ordre_chronologique_contredit_ordre_chaines(self):
        intv = [_interventions_basiques()[0]]
        tech = ["t"]
        fens = _fenetres_fuseaux_contradictoires()  # 09+02:00 puis 08+00:00
        c, _ = cedule_mod.generer_cedule(intv, tech, fens, SEL)
        fenetre_assignee = c["assignations"][0]["fenetre"]
        # La première chronologiquement est celle avec début 07:00Z (09:00+02:00)
        assert fenetre_assignee["debut"] == "2025-06-02T09:00:00+02:00"


# ================================================================== #
# 7. absence de ville en clair
# ================================================================== #
class TestAbsenceVilleEnClair:

    def test_aucune_ville_en_clair_dans_cedule(self):
        intv = _interventions_basiques()
        tech = _techniciens_basiques()
        fen = _fenetres_basiques()
        c, _ = cedule_mod.generer_cedule(intv, tech, fen, SEL)
        representation = repr(c)  # ou str
        for ville in VILLES_CLAIRES:
            assert ville not in representation, f"La ville '{ville}' apparaît dans la cédule"

    def test_ville_tokenisee_egale_tokeniser_ville(self):
        intv = _interventions_basiques()
        tech = _techniciens_basiques()
        fen = _fenetres_basiques()
        c, _ = cedule_mod.generer_cedule(intv, tech, fen, SEL)
        for assign in c["assignations"]:
            # Recalcul depuis les interventions originales
            expected_token = cedule_mod.tokeniser_ville(SEL, next(i["ville"] for i in intv if i["intervention_id"] == assign["intervention_id"]))
            assert assign["ville_tokenisee"] == expected_token


# ================================================================== #
# 8. chaque classe de rejet
# ================================================================== #
class TestRejets:

    # --- Contrat/validation au niveau des paramètres généraux ---

    def test_rejet_interventions_non_liste(self):
        _, v = cedule_mod.generer_cedule("pas_une_liste", ["t"], _fenetres_basiques(), SEL)
        assert v["code"] == "REJ-CONTRAT-INVALIDE"

    def test_rejet_techniciens_non_liste(self):
        _, v = cedule_mod.generer_cedule(_interventions_basiques(), "pas_une_liste", _fenetres_basiques(), SEL)
        assert v["code"] == "REJ-CONTRAT-INVALIDE"

    def test_rejet_fenetres_non_liste(self):
        _, v = cedule_mod.generer_cedule(_interventions_basiques(), ["t"], "pas_une_liste", SEL)
        assert v["code"] == "REJ-CONTRAT-INVALIDE"

    def test_rejet_sel_non_str(self):
        _, v = cedule_mod.generer_cedule([], ["t"], _fenetres_basiques(), 123)
        assert v["code"] == "REJ-CONTRAT-INVALIDE"

    def test_rejet_sel_vide(self):
        _, v = cedule_mod.generer_cedule([], ["t"], _fenetres_basiques(), "")
        assert v["code"] == "REJ-CHAMP-VIDE"

    # --- Interventions invalides ---

    def test_rejet_intervention_pas_dict(self):
        intv = ["string_in_interventions"]
        _, v = cedule_mod.generer_cedule(intv, ["t"], _fenetres_basiques(), SEL)
        assert v["code"] == "REJ-CONTRAT-INVALIDE"

    def test_rejet_intervention_cle_manquante(self):
        intv = copy.deepcopy(_interventions_basiques())
        del intv[0]["lead_id"]
        _, v = cedule_mod.generer_cedule(intv, ["t"], _fenetres_basiques(), SEL)
        assert v["code"] == "REJ-CONTRAT-INVALIDE"

    def test_rejet_intervention_cle_etrangere(self):
        intv = copy.deepcopy(_interventions_basiques())
        intv[0]["extra"] = "boom"
        _, v = cedule_mod.generer_cedule(intv, ["t"], _fenetres_basiques(), SEL)
        assert v["code"] == "REJ-CONTRAT-INVALIDE"

    def test_rejet_intervention_valeur_vide(self):
        intv = copy.deepcopy(_interventions_basiques())
        intv[0]["intervention_id"] = ""
        _, v = cedule_mod.generer_cedule(intv, ["t"], _fenetres_basiques(), SEL)
        assert v["code"] == "REJ-CHAMP-VIDE"

    def test_rejet_type_travaux_hors_enumere(self):
        intv = copy.deepcopy(_interventions_basiques())
        intv[0]["type_travaux"] = "demolition"
        _, v = cedule_mod.generer_cedule(intv, ["t"], _fenetres_basiques(), SEL)
        assert v["code"] == "REJ-ENUM-INVALIDE"

    def test_rejet_intervention_id_duplique(self):
        intv = copy.deepcopy(_interventions_basiques()[:2])
        intv.append(copy.deepcopy(intv[0]))  # même intervention_id
        _, v = cedule_mod.generer_cedule(intv, ["t"], _fenetres_basiques(), SEL)
        assert v["code"] == "REJ-CONTRAT-INVALIDE"
        assert "dupliqué" in v["detail"]

    # --- Techniciens invalides ---

    def test_rejet_technicien_non_str(self):
        _, v = cedule_mod.generer_cedule([], [123], _fenetres_basiques(), SEL)
        assert v["code"] == "REJ-CONTRAT-INVALIDE"

    def test_rejet_technicien_vide(self):
        _, v = cedule_mod.generer_cedule([], [""], _fenetres_basiques(), SEL)
        assert v["code"] == "REJ-CHAMP-VIDE"

    def test_rejet_technicien_doublon(self):
        _, v = cedule_mod.generer_cedule([], ["t", "t"], _fenetres_basiques(), SEL)
        assert v["code"] == "REJ-CONTRAT-INVALIDE"

    # --- Fenêtres invalides ---

    def test_rejet_fenetre_pas_dict(self):
        _, v = cedule_mod.generer_cedule([], ["t"], ["string"], SEL)
        assert v["code"] == "REJ-FENETRE-INVALIDE"

    def test_rejet_fenetre_cles_fausses(self):
        fen = [{"debut": "2025-01-01T00:00:00+00:00", "fin": "2025-01-01T01:00:00+00:00", "extra": 1}]
        _, v = cedule_mod.generer_cedule([], ["t"], fen, SEL)
        assert v["code"] == "REJ-FENETRE-INVALIDE"

    def test_rejet_fenetre_debut_sans_fuseau(self):
        fen = [{"debut": "2025-01-01T00:00:00", "fin": "2025-01-01T01:00:00+00:00"}]
        _, v = cedule_mod.generer_cedule([], ["t"], fen, SEL)
        assert v["code"] == "REJ-HORODATAGE-INVALIDE"

    def test_rejet_fenetre_debut_egal_fin(self):
        fen = [{"debut": "2025-01-01T00:00:00+00:00", "fin": "2025-01-01T00:00:00+00:00"}]
        _, v = cedule_mod.generer_cedule([], ["t"], fen, SEL)
        assert v["code"] == "REJ-FENETRE-INVALIDE"

    def test_rejet_fenetre_debut_superieur_fin(self):
        fen = [{"debut": "2025-01-02T00:00:00+00:00", "fin": "2025-01-01T00:00:00+00:00"}]
        _, v = cedule_mod.generer_cedule([], ["t"], fen, SEL)
        assert v["code"] == "REJ-FENETRE-INVALIDE"

    # --- Ressources manquantes pour du travail ---

    def test_rejet_interventions_non_vides_techniciens_vides(self):
        intv = _interventions_basiques()[:1]
        _, v = cedule_mod.generer_cedule(intv, [], _fenetres_basiques(), SEL)
        assert v["code"] == "REJ-FENETRE-INVALIDE"
        assert "aucune ressource" in v["detail"]

    def test_rejet_interventions_non_vides_fenetres_vides(self):
        intv = _interventions_basiques()[:1]
        _, v = cedule_mod.generer_cedule(intv, ["t"], [], SEL)
        assert v["code"] == "REJ-FENETRE-INVALIDE"
        assert "aucune ressource" in v["detail"]


# ================================================================== #
# 9. cas limites légaux
# ================================================================== #
class TestCasLimites:

    def test_interventions_vides_retourne_cedule_vide(self):
        c, v = cedule_mod.generer_cedule([], _techniciens_basiques(), _fenetres_basiques(), SEL)
        assert v is None
        assert c == {"assignations": [], "non_cedulees": []}

    def test_capacite_exacte_non_cedulees_vide(self):
        # 4 interventions, 2 techs, 2 fenêtres -> capacité 4
        intv = copy.deepcopy([
            {"intervention_id": "a", "lead_id": "L1", "type_travaux": "renovation_totale", "ville": "Lyon"},
            {"intervention_id": "b", "lead_id": "L2", "type_travaux": "renovation_totale", "ville": "Lyon"},
            {"intervention_id": "c", "lead_id": "L3", "type_travaux": "renovation_totale", "ville": "Lyon"},
            {"intervention_id": "d", "lead_id": "L4", "type_travaux": "renovation_totale", "ville": "Lyon"},
        ])
        c, v = cedule_mod.generer_cedule(intv, _techniciens_basiques(), _fenetres_basiques(), SEL)
        assert v is None
        assert len(c["assignations"]) == 4
        assert c["non_cedulees"] == []
        # capacité pleine : chaque technicien reçoit exactement une intervention par fenêtre
        paires = {(a["technicien_id"], a["fenetre"]["debut"]) for a in c["assignations"]}
        assert len(paires) == 4, "chaque couple (technicien, fenêtre) doit être unique"


# ================================================================== #
# 10. immuabilité des entrées
# ================================================================== #
class TestImmuabiliteEntrees:

    def test_entrees_non_mutees(self):
        intv_orig = _interventions_basiques()
        tech_orig = _techniciens_basiques()
        fen_orig = _fenetres_basiques()

        intv_copy = copy.deepcopy(intv_orig)
        tech_copy = copy.deepcopy(tech_orig)
        fen_copy = copy.deepcopy(fen_orig)

        cedule_mod.generer_cedule(intv_orig, tech_orig, fen_orig, SEL)

        # Vérifier qu'ils n'ont pas changé
        assert intv_orig == intv_copy
        assert tech_orig == tech_copy
        assert fen_orig == fen_copy
