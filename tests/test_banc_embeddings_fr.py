"""Banc de mesure des embeddings en français québécois (install/qualification/embeddings_fr) : tests DÉTERMINISTES.

Aucune clé, aucun réseau réel : un faux serveur HTTP local (127.0.0.1, port éphémère) joue la passerelle LiteLLM. Les
métriques sont vérifiées sur des mini-jeux à valeurs connues calculées à la main ; le chargeur de corpus, la fusion RRF,
la perturbation de requêtes, le cache, le juge de reclassement et l'exécution de bout en bout sont couverts, avec des
cas d'abus (clé qui fuit dans une erreur, redirection, réponse malformée, corpus non fictif). Le test contre la vraie
passerelle est dans tests/test_banc_embeddings_fr_reel.py (opt-in). Données fictives.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "install" / "qualification"))

from embeddings_fr import banc, juge, lexical_local, metriques, passerelle  # noqa: E402
from embeddings_fr import cache as mod_cache  # noqa: E402
from embeddings_fr import corpus as mod_corpus  # noqa: E402

CLE_FICTIVE = "sk-fictive-ne-pas-divulguer-0123456789"
DOSSIER_CORPUS = RACINE / "docs" / "qualification" / "corpus-embeddings-fr"


# ===== métriques (valeurs connues)
def test_rappel_a_k_valeurs_connues():
    classement = ["A", "X", "B", "Y", "C"]
    pertinents = {"A", "B", "Z"}
    assert metriques.rappel_a_k(classement, pertinents, 1) == pytest.approx(1 / 3)
    assert metriques.rappel_a_k(classement, pertinents, 2) == pytest.approx(1 / 3)
    assert metriques.rappel_a_k(classement, pertinents, 3) == pytest.approx(2 / 3)
    assert metriques.rappel_a_k(classement, pertinents, 10) == pytest.approx(2 / 3)  # Z n'est jamais retrouvé
    with pytest.raises(ValueError):
        metriques.rappel_a_k(classement, set(), 3)
    with pytest.raises(ValueError):
        metriques.rappel_a_k(classement, pertinents, 0)


def test_rang_reciproque_valeurs_connues():
    assert metriques.rang_reciproque(["X", "Y", "B"], {"B"}) == pytest.approx(1 / 3)
    assert metriques.rang_reciproque(["B", "X"], {"B", "X"}) == 1.0
    assert metriques.rang_reciproque(["X", "Y", "B"], {"B"}, k=2) == 0.0  # hors des k premiers
    assert metriques.rang_reciproque([], {"B"}) == 0.0
    with pytest.raises(ValueError):
        metriques.rang_reciproque(["A"], set())


def test_ndcg_valeurs_connues():
    gains = {"A": 2.0, "B": 1.0}
    ideal = 2.0 / math.log2(2) + 1.0 / math.log2(3)
    assert metriques.ndcg_a_k(["A", "B", "X"], gains, 10) == pytest.approx(1.0)
    obtenu = 1.0 / math.log2(2) + 2.0 / math.log2(4)  # B au rang 1, A au rang 3
    assert metriques.ndcg_a_k(["B", "X", "A"], gains, 10) == pytest.approx(obtenu / ideal)
    assert metriques.ndcg_a_k(["X", "Y"], gains, 10) == 0.0
    # k coupe le classement : A au rang 3 est hors de k=2
    assert metriques.ndcg_a_k(["B", "X", "A"], gains, 2) == pytest.approx((1.0 / math.log2(2)) / ideal)
    # un gain nul n'entre pas dans l'idéal
    assert metriques.ndcg_a_k(["A"], {"A": 2.0, "Z": 0.0}, 10) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        metriques.ndcg_a_k(["A"], {}, 10)
    with pytest.raises(ValueError):
        metriques.ndcg_a_k(["A"], {"A": 0.0}, 10)


def test_ndcg_idéal_tronqué_à_k():
    gains = {"A": 2.0, "B": 2.0, "C": 2.0}
    # k = 2 : l'idéal ne compte que deux gains ; un classement parfait sur 2 vaut 1
    assert metriques.ndcg_a_k(["A", "B", "C"], gains, 2) == pytest.approx(1.0)


def test_moyenne_et_quantile():
    assert metriques.moyenne([1, 2, 6]) == 3.0
    assert metriques.quantile([1, 2, 3, 4], 0.5) == pytest.approx(2.5)
    assert metriques.quantile([1, 2, 3, 4], 0.25) == pytest.approx(1.75)
    assert metriques.quantile([4, 1, 3, 2], 0.0) == 1 and metriques.quantile([4, 1, 3, 2], 1.0) == 4
    assert metriques.quantile([7], 0.9) == 7
    for mauvais in ((lambda: metriques.moyenne([])), (lambda: metriques.quantile([], 0.5)),
                    (lambda: metriques.quantile([1], 1.5)), (lambda: metriques.quantile([1], -0.1))):
        with pytest.raises(ValueError):
            mauvais()


def test_intervalle_bootstrap_proprietes():
    valeurs = [0.0, 1.0] * 20
    bas, haut = metriques.intervalle_bootstrap(valeurs, graine=1, repetitions=500)
    assert bas == metriques.intervalle_bootstrap(valeurs, graine=1, repetitions=500)[0]  # reproductible
    assert 0.0 <= bas < 0.5 < haut <= 1.0
    constant = metriques.intervalle_bootstrap([0.3] * 10, graine=3, repetitions=50)
    assert constant == (pytest.approx(0.3), pytest.approx(0.3))
    large = metriques.intervalle_bootstrap([0.0, 1.0] * 5, graine=2, repetitions=500)
    etroit = metriques.intervalle_bootstrap([0.0, 1.0] * 200, graine=2, repetitions=500)
    assert (large[1] - large[0]) > (etroit[1] - etroit[0])  # plus de questions, intervalle plus serré
    plus_confiant = metriques.intervalle_bootstrap(valeurs, graine=1, repetitions=500, niveau=0.5)
    assert (plus_confiant[1] - plus_confiant[0]) < (haut - bas)
    # couverture : pour 20 zéros et 20 uns (moyenne 0,5, erreur-type 0,079), l'intervalle à 95 % vaut environ ±0,15,
    # à 90 % environ ±0,125, à 50 % environ ±0,05 (valeurs relevées ; elles encadrent le bon quantile)
    for niveau, largeur in ((0.95, 0.30), (0.90, 0.25), (0.50, 0.10)):
        b, h = metriques.intervalle_bootstrap(valeurs, graine=7, repetitions=4000, niveau=niveau)
        assert h - b == pytest.approx(largeur, abs=0.03) and (b + h) / 2 == pytest.approx(0.5, abs=0.02)
    with pytest.raises(ValueError):
        metriques.intervalle_bootstrap([], graine=1)
    with pytest.raises(ValueError):
        metriques.intervalle_bootstrap([1.0], graine=1, niveau=1.0)


def test_difference_appariee():
    a = [0.5, 0.7, 0.9, 1.0]
    assert metriques.difference_appariee(a, a, graine=1, repetitions=50) == (0.0, 0.0, 0.0)
    ecart, bas, haut = metriques.difference_appariee([x + 0.1 for x in a], a, graine=1, repetitions=50)
    assert ecart == pytest.approx(0.1) and bas == pytest.approx(0.1) and haut == pytest.approx(0.1)
    ecart, _, _ = metriques.difference_appariee(a, [x + 0.2 for x in a], graine=1, repetitions=50)
    assert ecart == pytest.approx(-0.2)  # le signe est a - b
    with pytest.raises(ValueError, match="longueurs différentes"):
        metriques.difference_appariee([1.0], [1.0, 2.0], graine=1)


# ===== fusion RRF
def test_rrf_valeurs_connues_et_ordre():
    scores = metriques.fusion_rrf([["A", "B"], ["B", "C"]], k=60)
    assert scores["A"] == pytest.approx(1 / 61)
    assert scores["B"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["C"] == pytest.approx(1 / 62)
    assert metriques.fusionner([["A", "B"], ["B", "C"]], 60) == ["B", "A", "C"]
    assert metriques.fusion_rrf([["A"]], k=0) == {"A": 1.0}  # rang 1, k=0
    assert metriques.fusion_rrf([], k=60) == {}
    with pytest.raises(ValueError):
        metriques.fusion_rrf([["A"]], k=-1)


def test_rrf_egalite_departagee_par_identifiant_et_listes_asymetriques():
    assert metriques.fusionner([["B"], ["A"]], 60) == ["A", "B"]  # même score : ordre alphabétique
    # un document absent d'une liste n'est pas pénalisé en négatif : il garde seulement le score de l'autre liste
    scores = metriques.fusion_rrf([["A", "B", "C"], ["C"]], k=60)
    assert scores["C"] == pytest.approx(1 / 63 + 1 / 61)
    assert metriques.classer(scores)[0] == "C"


def test_rrf_le_parametre_k_change_le_classement():
    listes = [["A", "B"], ["C", "D", "B"]]
    assert metriques.fusionner(listes, 60)[0] == "B"  # k grand : la présence dans deux listes l'emporte
    assert metriques.fusionner(listes, 0)[:2] == ["A", "C"]  # k nul : le rang 1 d'une liste l'emporte
    assert metriques.fusionner(listes)[0] == "B"  # k par défaut = 60


def test_rrf_ponderee():
    scores = metriques.fusion_rrf([["A", "B"], ["B", "C"]], k=60, poids=[0.5, 1.0])
    assert scores["A"] == pytest.approx(0.5 / 61)
    assert scores["B"] == pytest.approx(0.5 / 62 + 1.0 / 61)
    assert scores["C"] == pytest.approx(1.0 / 62)
    assert metriques.fusion_rrf([["A"], ["A"]], 60, [1.0, 1.0]) == metriques.fusion_rrf([["A"], ["A"]], 60)
    # un poids nul retire la liste ; le classement suit alors la seule autre liste
    assert metriques.fusionner([["B", "A"], ["A", "B"]], 60, [0.0, 1.0]) == ["A", "B"]
    assert metriques.fusionner([["B", "A"], ["A", "B"]], 60, [1.0, 0.0]) == ["B", "A"]
    for mauvais in ([1.0], [1.0, -1.0], [1.0, 1.0, 1.0]):
        with pytest.raises(ValueError):
            metriques.fusion_rrf([["A"], ["B"]], 60, mauvais)


def test_rrf_concorde_avec_la_recherche_du_produit():
    from opsys.connaissances.recherche import rrf as rrf_produit

    listes = [["a", "b", "c", "d"], ["c", "a", "e"], ["e"]]
    mien, produit = metriques.fusion_rrf(listes, 60), rrf_produit(listes, 60)
    assert mien.keys() == produit.keys()
    for cle in mien:
        assert mien[cle] == pytest.approx(produit[cle])


def test_cosinus():
    assert metriques.cosinus([1, 0], [0, 1]) == 0.0
    assert metriques.cosinus([1, 2], [2, 4]) == pytest.approx(1.0)
    assert metriques.cosinus([1, 0], [-3, 0]) == pytest.approx(-1.0)
    with pytest.raises(ValueError):
        metriques.cosinus([0, 0], [1, 0])
    with pytest.raises(ValueError):
        metriques.cosinus([1], [1, 2])


def test_auc_et_faux_acceptes():
    assert metriques.auc([3, 4], [1, 2]) == 1.0
    assert metriques.auc([1, 2], [3, 4]) == 0.0
    assert metriques.auc([1], [1]) == 0.5
    assert metriques.auc([3, 1], [2]) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        metriques.auc([], [1])
    positifs = [x / 10 for x in range(1, 11)]  # 0,1 ... 1,0
    seuil, faux = metriques.faux_acceptes_au_rappel(positifs, [0.1, 0.5], 0.9)
    assert seuil == pytest.approx(0.19) and faux == pytest.approx(0.5)  # 0,5 passe le seuil, 0,1 non
    seuil, faux = metriques.faux_acceptes_au_rappel(positifs, [0.1, 0.5], 1.0)
    assert seuil == pytest.approx(0.1) and faux == 1.0  # rappel total : le seuil descend au plus petit positif
    with pytest.raises(ValueError):
        metriques.faux_acceptes_au_rappel(positifs, [0.1], 0.0)


# ===== corpus
def _ecrire_corpus(dossier: Path, passages: dict, requetes: list, *, fictif=True, schema_p=None, schema_q=None):
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "passages_a.yaml").write_text(yaml.safe_dump({
        "schema": schema_p or mod_corpus.SCHEMA_PASSAGES, "fictif": fictif, "categories": {"test": passages}},
        allow_unicode=True), encoding="utf-8")
    (dossier / "requetes.yaml").write_text(yaml.safe_dump({
        "schema": schema_q or mod_corpus.SCHEMA_REQUETES, "fictif": fictif, "requetes": requetes}, allow_unicode=True),
        encoding="utf-8")
    return dossier


PASSAGES_MINI = {"G001": "gouttière en aluminium de cinq pouces", "G002": "soffite ventilé du grenier",
                 "G003": "facture payée par virement Interac"}
REQUETES_MINI = [{"id": "Q001", "type": "paraphrase", "texte": "pose de gouttière", "pertinents": ["G001"],
                  "partiels": ["G002"]},
                 {"id": "Q002", "type": "negative", "texte": "recette de tarte", "pertinents": []}]


def test_corpus_reel_charge_et_a_la_taille_annoncee():
    c = mod_corpus.charger_corpus(DOSSIER_CORPUS)
    assert 200 <= len(c.passages) <= 400 and 60 <= len(c.requetes) <= 120
    assert {q.type for q in c.requetes} == set(mod_corpus.TYPES_REQUETE)  # toutes les difficultés demandées y sont
    negatives = [q for q in c.requetes if q.negative]
    assert len(negatives) >= 10 and all(not q.pertinents and not q.partiels for q in negatives)
    assert all(q.pertinents for q in c.requetes if not q.negative)
    assert len(c.empreinte) == 64 and c.empreinte == mod_corpus.charger_corpus(DOSSIER_CORPUS).empreinte
    # un passage n'est jamais à la fois pertinent et partiel ; tous les jugements pointent un passage existant
    for q in c.requetes:
        assert not (q.pertinents & q.partiels) and (q.pertinents | q.partiels) <= set(c.passages)
    assert {re.sub(r"\d+", "", i) for i in c.passages} == {"G", "R", "S", "U", "P", "F", "V", "N"}


def test_corpus_reel_ne_contient_aucune_donnee_reelle_evidente():
    c = mod_corpus.charger_corpus(DOSSIER_CORPUS)
    ensemble = " ".join(list(c.passages.values()) + [q.texte for q in c.requetes])
    assert "@" not in ensemble.replace("@alunord.example.test", "")  # le seul courriel est de domaine .test
    sans_fictif = ensemble.replace("450-555-0147", "")  # le seul numéro est fictif (555-01xx)
    assert not re.search(r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b", sans_fictif)
    for fichier in DOSSIER_CORPUS.glob("*.yaml"):
        assert "fictif: true" in fichier.read_text(encoding="utf-8")


def test_chargeur_accepte_un_mini_corpus(tmp_path):
    c = mod_corpus.charger_corpus(_ecrire_corpus(tmp_path / "c", PASSAGES_MINI, REQUETES_MINI))
    assert c.passages["G001"].startswith("gouttière") and c.categories["G001"] == "test"
    q1, q2 = c.requetes
    assert q1.gains() == {"G002": 1.0, "G001": 2.0} and not q1.negative and q2.negative


@pytest.mark.parametrize("modification,fragment", [
    (lambda p, r: (p, r, {"fictif": False}), "fictif"),
    (lambda p, r: (p, r, {"schema_p": "autre/v1"}), "schéma"),
    (lambda p, r: (p, r, {"schema_q": "autre/v1"}), "schéma"),
    (lambda p, r: ({**p, "g004": "minuscule"}, r, {}), "identifiant de passage"),
    (lambda p, r: ({**p, "G004": "   "}, r, {}), "texte non vide"),
    (lambda p, r: ({**p, "G004": "x" * 1300}, r, {}), "texte non vide"),
    (lambda p, r: ({**p, "G004": "écrire à jean@exemple.com"}, r, {}), "courriel non fictive"),
    (lambda p, r: (p, [*r, {**r[0]}], {}), "requête en double"),
    (lambda p, r: (p, [{**r[0], "id": "R1"}], {}), "identifiant de requête"),
    (lambda p, r: (p, [{**r[0], "type": "inconnu"}], {}), "type parmi"),
    (lambda p, r: (p, [{**r[0], "pertinents": ["G999"]}], {}), "inexistant"),
    (lambda p, r: (p, [{**r[0], "partiels": ["G001"]}], {}), "à la fois pertinent et partiel"),
    (lambda p, r: (p, [{**r[0], "pertinents": ["G001", "G001"]}], {}), "doublon"),
    (lambda p, r: (p, [{**r[1], "pertinents": ["G001"]}], {}), "negative"),
    (lambda p, r: (p, [{**r[0], "type": "negative"}], {}), "negative"),
    (lambda p, r: (p, [{**r[1], "partiels": ["G001"]}], {}), "partiels"),
    (lambda p, r: (p, [{**r[0], "texte": "x" * 301}], {}), "texte de 1 à 300"),
    (lambda p, r: (p, [{**r[0], "texte": "contact a@vrai.com"}], {}), "courriel non fictive"),
])
def test_chargeur_refuse_les_corpus_trompeurs(tmp_path, modification, fragment):
    passages, requetes, options = modification(dict(PASSAGES_MINI), [dict(q) for q in REQUETES_MINI])
    dossier = _ecrire_corpus(tmp_path / "c", passages, requetes, **options)
    with pytest.raises(mod_corpus.ErreurCorpus, match=fragment):
        mod_corpus.charger_corpus(dossier)


def test_chargeur_refuse_un_dossier_vide_et_un_id_en_double_entre_fichiers(tmp_path):
    with pytest.raises(mod_corpus.ErreurCorpus, match="aucun fichier"):
        mod_corpus.charger_corpus(tmp_path)
    dossier = _ecrire_corpus(tmp_path / "c", PASSAGES_MINI, REQUETES_MINI)
    (dossier / "passages_b.yaml").write_text(yaml.safe_dump({
        "schema": mod_corpus.SCHEMA_PASSAGES, "fictif": True, "categories": {"autre": {"G001": "doublon"}}}),
        encoding="utf-8")
    with pytest.raises(mod_corpus.ErreurCorpus, match="passage en double"):
        mod_corpus.charger_corpus(dossier)


def test_perturbation_deterministe_et_visible():
    texte = "Comment éviter que le revêtement de vinyle ondule après la pose ?"
    p1, p2 = mod_corpus.perturber_requete(texte), mod_corpus.perturber_requete(texte)
    assert p1 == p2 != texte
    assert len(p1.split(" ")) == len(texte.split(" "))
    assert "é" not in p1 and "è" not in p1  # accents retirés
    assert mod_corpus.perturber_requete(texte, graine=1) != mod_corpus.perturber_requete(texte, graine=2)
    assert mod_corpus.perturber_requete("facture 2026-1187 solde 2 415 $") != "facture 2026-1187 solde 2 415 $"
    for graine in range(60):  # nombres et identifiants à chiffres jamais touchés, quelle que soit la graine
        assert "2026-1187" in mod_corpus.perturber_requete("facture 2026-1187 solde 2 415 $", graine)
        assert "S-2026-0452" in mod_corpus.perturber_requete("soumission S-2026-0452 copropriété", graine).split(" ")
    court = "et la"
    assert mod_corpus.perturber_requete(court) == court  # aucun mot de 5 lettres : rien à perturber
    # chaque requête réelle de plus de 5 lettres est effectivement modifiée
    corpus = mod_corpus.charger_corpus(DOSSIER_CORPUS)
    for q in corpus.requetes:
        if any(len(m) >= 5 and m.isalpha() for m in q.texte.split(" ")):
            assert mod_corpus.perturber_requete(q.texte) != q.texte, q.identifiant
    # une permutation de deux lettres identiques ne passe pas inaperçue
    for graine in range(40):
        assert mod_corpus.perturber_requete("pellicule appelle", graine) != "pellicule appelle"


# ===== BM25 local
def test_lexique_bm25_du_depot():
    lx = lexical_local.Lexique({"A": "gouttière en aluminium prélaqué", "B": "soffite ventilé",
                                "C": "facture du fournisseur"})
    assert lexical_local.identifiants(lx.classer("gouttiere"))[0] == "A"  # insensible aux accents
    assert lexical_local.identifiants(lx.classer("Gouttières")) == ["A"]  # pluriel replié par le radical
    assert lx.classer("le la de") == []  # que des mots vides
    assert lx.classer("recette tarte") == []
    # sémantique OU : un seul terme en commun suffit, le passage qui en a plus passe devant
    ordre = lexical_local.identifiants(lx.classer("facture soffite ventilé", couverture=None))
    assert ordre[0] == "B" and set(ordre) == {"B", "C"}
    # le filtre de couverture écarte un passage qui ne couvre pas assez de termes de la question
    longue = "facture soffite ventilé inconnu1 inconnu2 inconnu3"
    assert lexical_local.identifiants(lx.classer(longue, couverture=0.5)) == []
    assert lexical_local.identifiants(lx.classer(longue, couverture=None))
    # injection de syntaxe FTS5 : sans effet
    assert lx.classer('NEAR("a" "b") OR * ^ ) (') == []
    assert lexical_local.identifiants(lx.classer('gouttiere" OR "soffite')) in (["A", "B"], ["B", "A"])
    lx.fermer()


# ===== faux serveur de passerelle
class _Etat:
    def __init__(self) -> None:
        self.requetes: list[dict] = []
        self.entetes: list[dict] = []
        self.mode = "normal"
        self.compteur_pannes = 0
        self.depense = 0.0
        self.reponse_discussion = '{"notes": [3, 0, 1]}'
        self.autre_hote_recu = False


def _vecteur_factice(texte: str, dimension: int = 32, input_type: str | None = None) -> list[float]:
    v = [0.0] * dimension
    for mot in re.findall(r"\w+", texte.lower()):
        h = int(hashlib.sha256(mot.encode()).hexdigest()[:8], 16)
        v[h % dimension] += 1.0 if (h >> 8) & 1 else -1.0
    if input_type == "query":
        v[0] += 0.01
    if not any(v):
        v[0] = 1.0
    return v


@pytest.fixture()
def serveur():
    etat = _Etat()
    autre = ThreadingHTTPServer(("127.0.0.1", 0), type("Autre", (BaseHTTPRequestHandler,), {
        "do_POST": lambda s: (setattr(etat, "autre_hote_recu", True), s.send_response(200), s.end_headers()),
        "do_GET": lambda s: (setattr(etat, "autre_hote_recu", True), s.send_response(200), s.end_headers()),
        "log_message": lambda *a: None}))

    class Gestionnaire(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence
            pass

        def _json(self, code: int, objet) -> None:
            corps = json.dumps(objet).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

        def do_GET(self):
            etat.entetes.append(dict(self.headers))
            self._json(200, {"info": {"spend": etat.depense}})

        def do_POST(self):
            longueur = int(self.headers.get("Content-Length", 0))
            corps = json.loads(self.rfile.read(longueur))
            etat.requetes.append({"chemin": self.path, **corps})
            etat.entetes.append(dict(self.headers))
            if etat.mode == "http400":
                return self._json(400, {"erreur": "mauvaise requête", "echo": self.headers.get("Authorization")})
            if etat.mode == "http500_une_fois" and etat.compteur_pannes == 0:
                etat.compteur_pannes += 1
                return self._json(500, {"erreur": "panne", "echo": self.headers.get("Authorization")})
            if etat.mode == "http500_toujours":
                return self._json(500, {"erreur": "panne", "echo": self.headers.get("Authorization")})
            if etat.mode == "redirection":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{autre.server_address[1]}/vol")
                self.end_headers()
                return None
            if etat.mode == "non_json":
                self.send_response(200)
                self.send_header("Content-Length", "3")
                self.end_headers()
                self.wfile.write(b"<<<")
                return None
            if self.path == "/v1/chat/completions":
                return self._json(200, {"choices": [{"message": {"content": etat.reponse_discussion}}],
                                        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.0001}})
            entrees = corps["input"]
            donnees = [{"index": i, "embedding": _vecteur_factice(t, input_type=corps.get("input_type"))}
                       for i, t in enumerate(entrees)]
            if etat.mode == "mauvais_nombre":
                donnees = donnees[:-1]
            if etat.mode == "vecteur_nul":
                donnees[0]["embedding"] = [0.0] * 32
            if etat.mode == "vecteur_nan":
                donnees[0]["embedding"][0] = float("nan")
            if etat.mode == "dimensions_mixtes":
                donnees[0]["embedding"] = donnees[0]["embedding"][:5]
            if etat.mode == "index_incoherent":
                donnees[0]["index"] = 7
            if etat.mode == "inverse":
                donnees = list(reversed(donnees))
            jetons = sum(len(re.findall(r"\w+", t)) for t in entrees)
            return self._json(200, {"data": donnees, "usage": {"prompt_tokens": jetons, "total_tokens": jetons}})

    principal = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
    for s in (principal, autre):
        threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    etat.url = f"http://127.0.0.1:{principal.server_address[1]}"
    yield etat
    for s in (principal, autre):
        s.shutdown()
        s.server_close()


def _client(serveur, **kw) -> passerelle.ClientPasserelle:
    return passerelle.ClientPasserelle(serveur.url, CLE_FICTIVE, dormir=lambda s: None, **kw)


# ===== client de passerelle
def test_client_embeddings_et_cle_dans_l_entete_seulement(serveur):
    reponse = _client(serveur).embeddings("opsys-embed-voyage-4", ["gouttière qui coule", "soffite pourri"])
    assert len(reponse.vecteurs) == 2 and len(reponse.vecteurs[0]) == 32 and reponse.jetons == 5
    assert reponse.secondes >= 0
    assert serveur.entetes[0]["Authorization"] == f"Bearer {CLE_FICTIVE}"
    assert CLE_FICTIVE not in json.dumps(serveur.requetes)  # la clé ne part jamais dans le corps
    assert serveur.requetes[0]["encoding_format"] == "float" and "input_type" not in serveur.requetes[0]


def test_client_envoie_input_type_et_remet_les_vecteurs_dans_l_ordre(serveur):
    serveur.mode = "inverse"
    textes = ["un", "deux mots", "trois mots ici"]
    reponse = _client(serveur).embeddings("m", textes, input_type="query")
    assert serveur.requetes[-1]["input_type"] == "query"
    attendu = [_vecteur_factice(t, input_type="query") for t in textes]
    assert reponse.vecteurs == attendu  # l'index de la réponse, pas l'ordre d'arrivée, fait foi


def test_client_ne_fuit_pas_la_cle_dans_les_erreurs(serveur):
    serveur.mode = "http400"
    with pytest.raises(passerelle.ErreurPasserelle) as exc:
        _client(serveur).embeddings("m", ["x"])
    assert CLE_FICTIVE not in str(exc.value) and exc.value.http_status == 400 and "***" in str(exc.value)
    assert len(serveur.requetes) == 1  # une erreur client n'est pas rejouée


def test_client_relance_une_panne_transitoire_puis_abandonne(serveur):
    serveur.mode = "http500_une_fois"
    assert len(_client(serveur).embeddings("m", ["x"]).vecteurs) == 1 and len(serveur.requetes) == 2
    serveur.requetes.clear()
    serveur.mode = "http500_toujours"
    with pytest.raises(passerelle.ErreurPasserelle) as exc:
        _client(serveur).embeddings("m", ["x"])
    assert len(serveur.requetes) == 1 + passerelle.RELANCES and CLE_FICTIVE not in str(exc.value)


def test_client_ne_suit_aucune_redirection(serveur):
    serveur.mode = "redirection"
    with pytest.raises(passerelle.ErreurPasserelle):
        _client(serveur).embeddings("m", ["x"])
    assert serveur.autre_hote_recu is False  # la clé n'a pas été envoyée à l'hôte désigné par la redirection


@pytest.mark.parametrize("mode", ["mauvais_nombre", "vecteur_nul", "vecteur_nan", "dimensions_mixtes",
                                  "index_incoherent", "non_json"])
def test_client_refuse_une_reponse_malformee(serveur, mode):
    serveur.mode = mode
    with pytest.raises(passerelle.ErreurPasserelle):
        _client(serveur).embeddings("m", ["un texte", "deux textes"])


def test_client_valide_ses_entrees():
    for url in ("ftp://x", "http://user:mdp@127.0.0.1", "pas une url", ""):
        with pytest.raises(passerelle.ErreurPasserelle):
            passerelle.ClientPasserelle(url, CLE_FICTIVE)
    with pytest.raises(passerelle.ErreurPasserelle):
        passerelle.ClientPasserelle("http://127.0.0.1:1", "")
    client = passerelle.ClientPasserelle("http://127.0.0.1:1", CLE_FICTIVE)
    for textes in ([], [""], ["  "], ["x"] * (passerelle.LOT_MAX + 1)):
        with pytest.raises(passerelle.ErreurPasserelle):
            client.embeddings("m", textes)
    with pytest.raises(passerelle.ErreurPasserelle):
        client.discussion("m", [{"role": "user", "content": "x"}], max_tokens=0)


def test_client_injoignable_ne_fuit_pas_la_cle():
    client = passerelle.ClientPasserelle("http://127.0.0.1:9", CLE_FICTIVE, delai_s=2, dormir=lambda s: None)
    with pytest.raises(passerelle.ErreurPasserelle) as exc:
        client.embeddings("m", ["x"])
    assert CLE_FICTIVE not in str(exc.value)


def test_lire_cle(tmp_path):
    fichier = tmp_path / "cle"
    fichier.write_text("  " + CLE_FICTIVE + "\n", encoding="utf-8")
    assert passerelle.lire_cle(fichier) == CLE_FICTIVE
    for contenu in ("", "  \n", "deux mots", "a" * 600, "avec\x07controle"):
        fichier.write_text(contenu, encoding="utf-8")
        with pytest.raises(passerelle.ErreurPasserelle) as exc:
            passerelle.lire_cle(fichier)
        assert CLE_FICTIVE not in str(exc.value)
    with pytest.raises(passerelle.ErreurPasserelle):
        passerelle.lire_cle(tmp_path / "absent")


def test_depense_et_discussion(serveur):
    serveur.depense = 1.25
    client = _client(serveur)
    assert client.depense() == 1.25
    reponse = client.discussion("opsys-haiku-5-5", [{"role": "user", "content": "x"}], max_tokens=50)
    assert reponse.texte.startswith("{") and reponse.jetons_entree == 100 and reponse.jetons_sortie == 10
    assert reponse.cout_usd == 0.0001
    assert serveur.requetes[-1]["max_tokens"] == 50 and serveur.requetes[-1]["reasoning_effort"] == "none"
    serveur.mode = "http400"
    assert client.depense() == 1.25  # GET non affecté
    injoignable = passerelle.ClientPasserelle("http://127.0.0.1:9", CLE_FICTIVE, delai_s=1, dormir=lambda s: None)
    assert injoignable.depense() is None


# ===== cache
def test_cache_vecteurs_journal_et_refus_dans_le_depot(tmp_path):
    cache = mod_cache.Cache(tmp_path / "c")
    cle = mod_cache.cle_vecteur("m", "query: ", None, "texte")
    assert cache.lire(cle) is None
    cache.ecrire(cle, "m", [0.5, -1.25, 3.0])
    assert cache.lire(cle) == [0.5, -1.25, 3.0]
    assert len({mod_cache.cle_vecteur("m", "", None, "t"), mod_cache.cle_vecteur("m", "p", None, "t"),
                mod_cache.cle_vecteur("m", "", "query", "t"), mod_cache.cle_vecteur("n", "", None, "t"),
                mod_cache.cle_vecteur("m", "", None, "u")}) == 5  # chaque paramètre change la clé
    cache.journaliser_appel("m", "cfg", "requete-unitaire", 1, 0.25, 7)
    cache.journaliser_appel("m", "cfg", "document-lot", 64, 1.5, None)
    assert [a["role"] for a in cache.appels("cfg")] == ["requete-unitaire", "document-lot"]
    assert len(cache.appels("cfg", "document-lot")) == 1 and cache.appels("autre") == []
    cache.ecrire_jugement("k", "m", "{}")
    assert cache.lire_jugement("k") == "{}" and cache.lire_jugement("absent") is None
    cache.fermer()
    with pytest.raises(mod_cache.ErreurCache):
        mod_cache.Cache(RACINE / "docs" / "cache-interdit")
    with pytest.raises(mod_cache.ErreurCache):
        mod_cache.Cache(RACINE)


# ===== plonger (cache + lots + sonde)
CONFIG_TEST = banc.Config("test", "m-test", "essai")


def test_plonger_lots_sonde_prefixes_et_cache(serveur, tmp_path):
    cache = mod_cache.Cache(tmp_path / "c")
    client = _client(serveur)
    config = banc.Config("e5", "m-e5", "essai", prefixe_requete="query: ", prefixe_document="passage: ")
    textes = [f"texte numero {i}" for i in range(7)]
    v = banc.plonger(client, cache, config, textes, "requete", taille_lot=3, sonde=2)
    assert len(v) == 7
    envois = [r["input"] for r in serveur.requetes]
    assert [len(e) for e in envois] == [1, 1, 3, 2]  # 2 unitaires (sonde) puis lots de 3 et 2
    assert all(t.startswith("query: ") for e in envois for t in e)  # préfixe de requête appliqué
    roles = [a["role"] for a in cache.appels("e5")]
    assert roles == ["requete-unitaire"] * 2 + ["requete-lot"] * 2
    # deuxième passage : tout vient du cache, aucun appel
    n = len(serveur.requetes)
    assert banc.plonger(client, cache, config, textes, "requete", taille_lot=3, sonde=2) == v
    assert len(serveur.requetes) == n
    # le même texte comme document a un autre préfixe : autre vecteur, nouvel appel
    banc.plonger(client, cache, config, textes[:1], "document")
    assert serveur.requetes[-1]["input"] == ["passage: texte numero 0"]
    # doublons : un seul appel par texte distinct
    serveur.requetes.clear()
    banc.plonger(client, cache, config, ["nouveau", "nouveau"], "requete")
    assert sum(len(r["input"]) for r in serveur.requetes) == 1


def test_plonger_input_type_selon_le_role(serveur, tmp_path):
    cache = mod_cache.Cache(tmp_path / "c")
    client = _client(serveur)
    config = banc.Config("t", "m-t", "essai", input_type=True)
    banc.plonger(client, cache, config, ["a b"], "requete")
    banc.plonger(client, cache, config, ["a b"], "document")
    assert [r["input_type"] for r in serveur.requetes] == ["query", "document"]
    with pytest.raises(banc.ErreurBanc):
        banc.plonger(client, cache, config, ["a b"], "autre")


def test_plonger_sans_appel_refuse_un_cache_incomplet(tmp_path):
    cache = mod_cache.Cache(tmp_path / "c")
    with pytest.raises(banc.ErreurBanc, match="--sans-appel"):
        banc.plonger(None, cache, CONFIG_TEST, ["jamais vu"], "requete")


def test_plonger_vecteurs_identiques_au_premier_appel_et_depuis_le_cache(serveur, tmp_path):
    client = _client(serveur)
    premier = banc.plonger(client, mod_cache.Cache(tmp_path / "c"), CONFIG_TEST, ["a b c"], "document")
    relu = banc.plonger(None, mod_cache.Cache(tmp_path / "c"), CONFIG_TEST, ["a b c"], "document")
    assert premier == relu  # même arrondi float32 dans les deux cas : la mesure se rejoue à l'identique


# ===== systèmes évalués (valeurs connues)
def _mini_corpus() -> mod_corpus.Corpus:
    passages = {"A": "gouttière aluminium", "B": "soffite ventilé", "C": "facture virement"}
    requetes = (
        mod_corpus.Requete("Q001", "paraphrase", "eau du toit", frozenset({"A"}), frozenset({"B"})),
        mod_corpus.Requete("Q002", "paraphrase", "air du grenier", frozenset({"B"}), frozenset()),
        mod_corpus.Requete("Q003", "negative", "recette de tarte", frozenset(), frozenset()))
    return mod_corpus.Corpus(passages, dict.fromkeys(passages, "t"), requetes, "0" * 64)


def test_evaluer_systemes_valeurs_connues():
    corpus = _mini_corpus()
    docs = {"A": [1.0, 0.0, 0.0], "B": [0.0, 1.0, 0.0], "C": [0.0, 0.0, 1.0]}
    rq = {"Q001": [0.6, 0.8, 0.0], "Q002": [0.8, 0.6, 0.0], "Q003": [0.0, 0.0, 0.3]}
    rp = {"Q001": [0.0, 1.0, 0.0], "Q002": [0.0, 1.0, 0.0], "Q003": [0.0, 0.0, 1.0]}
    lx = lexical_local.Lexique(corpus.passages)
    ev = banc.evaluer_systemes(corpus, lx, docs, rq, rp, {q.identifiant: q.texte for q in corpus.requetes})
    vec = ev["enregistrements"]["vec"]
    # Q001 : cosinus A=0,6 B=0,8 C=0 -> B, A, C ; pertinent A au rang 2
    assert vec["Q001"]["top10"][:2] == ["B", "A"] and vec["Q001"]["rr"] == 0.5 and vec["Q001"]["r1"] == 0.0
    assert vec["Q001"]["r5"] == 1.0
    gains = {"B": 1.0, "A": 2.0}
    attendu = (1.0 / math.log2(2) + 2.0 / math.log2(3)) / (2.0 / math.log2(2) + 1.0 / math.log2(3))
    assert vec["Q001"]["ndcg"] == pytest.approx(attendu) and gains  # le partiel B au rang 1 rapporte quand même
    # Q002 : cosinus A=0,8 B=0,6 -> A, B ; pertinent B au rang 2
    assert vec["Q002"]["rr"] == 0.5
    assert "Q003" not in vec and "Q003" in ev["negatifs"]["vec"]  # la négative n'entre pas dans les moyennes
    assert ev["tetes"]["vec"]["sans"] == [pytest.approx(0.3)] and sorted(ev["tetes"]["vec"]["avec"]) == [
        pytest.approx(0.8), pytest.approx(0.8)]
    # variante perturbée : vecteurs propres à cette variante
    assert ev["enregistrements"]["vec_pert"]["Q001"]["top10"][0] == "B"
    # le lexical ne voit que les mots communs : « eau du toit » n'en partage aucun avec le corpus
    assert ev["enregistrements"]["lex"]["Q001"]["top10"] == []
    # l'hybride fusionne : sans liste lexicale, il retombe sur l'ordre vectoriel
    assert ev["enregistrements"]["hyb"]["Q001"]["top10"][:2] == ["B", "A"]
    lx.fermer()


def test_hybride_rattrape_ce_que_le_vectoriel_manque():
    passages = {"A": "gouttière aluminium", "B": "soffite ventilé", "C": "facture virement"}
    requetes = (mod_corpus.Requete("Q001", "faute", "gouttière", frozenset({"A"}), frozenset()),)
    corpus = mod_corpus.Corpus(passages, dict.fromkeys(passages, "t"), requetes, "0" * 64)
    docs = {"A": [0.0, 0.0, 1.0], "B": [1.0, 0.0, 0.0], "C": [0.0, 1.0, 0.0]}
    rq = {"Q001": [0.9, 0.1, 0.1]}  # le vecteur se trompe (B d'abord, A dernier)
    lx = lexical_local.Lexique(passages)
    ev = banc.evaluer_systemes(corpus, lx, docs, rq, rq, {"Q001": "gouttière"})
    assert ev["enregistrements"]["vec"]["Q001"]["top10"][0] == "B"
    assert ev["enregistrements"]["lex"]["Q001"]["top10"] == ["A"]
    assert ev["enregistrements"]["hyb"]["Q001"]["top10"][0] == "A"  # 1/61 + 1/63 contre 1/61 pour B
    assert ev["enregistrements"]["hyb"]["Q001"]["rr"] == 1.0
    lx.fermer()


def test_abstention_seuil_latence_cout_et_taille():
    sortie = banc.abstention({"avec": [0.9, 0.8, 0.7, 0.6], "sans": [0.1, 0.65]})
    assert sortie["auc"] == pytest.approx((4 + 3) / 8)
    assert sortie["n_avec"] == 4 and sortie["n_sans"] == 2
    assert sortie["tete_mediane_avec"] == pytest.approx(0.75) and sortie["tete_mediane_sans"] == pytest.approx(0.375)
    docs = {"A": [1.0, 0.0], "B": [0.0, 1.0]}
    corpus = _mini_corpus()
    rq = {"Q001": [0.2, 0.1], "Q002": [0.0, 1.0], "Q003": [0.5, 0.5]}
    seuil = banc.analyse_seuil_produit(corpus, docs, rq)
    # pertinents : (Q001 -> A cos 0,2 < 0,30), (Q002 -> B cos 1,0) : la moitié sous le seuil ; la négative passe (0,5)
    assert seuil == {"seuil": 0.30, "pertinents_sous_le_seuil": 0.5, "sans_reponse_au_dessus_du_seuil": 1.0}
    # frontière : un cosinus de 0,30 pile n'est PAS sous le seuil (strict) et une négative à 0,30 pile le passe (>=)
    pile = banc.analyse_seuil_produit(corpus, {"A": [1.0, 0.0], "B": [0.0, 1.0]},
                                      {"Q001": [0.3, 0.0], "Q002": [0.0, 0.3], "Q003": [0.3, 0.0]})
    assert pile["pertinents_sous_le_seuil"] == 0.0 and pile["sans_reponse_au_dessus_du_seuil"] == 1.0
    appels = [{"role": "requete-unitaire", "secondes": s, "textes": 1, "jetons": 10, "modele": "m"}
              for s in (0.1, 0.2, 0.3, 0.4, 1.0)]
    appels += [{"role": "document-lot", "secondes": 2.0, "textes": 50, "jetons": 5000, "modele": "m"},
               {"role": "document-lot", "secondes": 1.0, "textes": 50, "jetons": 5000, "modele": "m"}]
    lat = banc.latence(appels)
    assert lat["requete_isolee"]["n"] == 5 and lat["requete_isolee"]["p50_s"] == 0.3
    assert lat["requete_isolee"]["p95_s"] == pytest.approx(0.88) and lat["requete_isolee"]["max_s"] == 1.0
    assert lat["documents_par_lot"] == {"appels": 2, "textes": 100, "secondes_par_texte": 0.03}
    c = banc.cout(appels, {"entree": "0.00000006", "sortie": "0"}, 100)
    assert c["jetons_documents"] == 10000 and c["jetons_requetes"] == 50
    assert c["usd_mesure"] == pytest.approx(10050 * 0.00000006)
    assert c["usd_par_million_de_jetons"] == pytest.approx(0.06)
    assert c["jetons_par_passage"] == 100.0
    assert c["usd_pour_100000_passages_de_meme_taille"] == pytest.approx(0.6)
    sans_jetons = banc.cout([{**appels[0], "jetons": None}], {"entree": "1", "sortie": "0"}, 1)
    assert sans_jetons["jetons_inconnus"] is True and "usd_mesure" not in sans_jetons  # pas de coût inventé
    assert banc._taille_vecteur(1024) == {"dimension": 1024, "octets_float32": 4096, "mo_pour_100000_passages": 390.6}


def test_comparer_et_resume():
    a = {"Q1": {"rr": 1.0}, "Q2": {"rr": 1.0}, "Q3": {"rr": 1.0}, "Q4": {"rr": 1.0}}
    b = {"Q1": {"rr": 0.5}, "Q2": {"rr": 0.5}, "Q3": {"rr": 0.5}, "Q4": {"rr": 0.5}}
    c = banc.comparer(a, b)
    assert c["ecart"] == 0.5 and c["distinguable"] is True and c["n"] == 4
    nul = banc.comparer(a, a)
    assert nul["ecart"] == 0.0 and nul["distinguable"] is False
    partiel = banc.comparer(a, {"Q1": {"rr": 0.0}})  # seules les questions communes comptent
    assert partiel["n"] == 1 and partiel["ecart"] == 1.0
    r = banc.resume([{"rr": 1.0, "r1": 1.0, "r5": 1.0, "r10": 1.0, "ndcg": 1.0},
                     {"rr": 0.0, "r1": 0.0, "r5": 0.0, "r10": 0.0, "ndcg": 0.0}])
    assert r["n"] == 2 and r["mrr@10"]["moyenne"] == 0.5 and r["mrr@10"]["ic95"][0] <= 0.5 <= r["mrr@10"]["ic95"][1]
    with pytest.raises(banc.ErreurBanc):
        banc.resume([])


# ===== juge
def test_juge_analyse_des_notes():
    assert juge.analyser_notes('{"notes": [3, 0, 2]}', 3) == [3, 0, 2]
    assert juge.analyser_notes('Voici : {"notes":[1,1]} merci', 2) == [1, 1]
    for mauvais in ('{"notes": [3, 0]}', '{"notes": [3, 0, 4]}', '{"notes": [3, 0, -1]}', '{"notes": [3, 0, 1.5]}',
                    '{"notes": [3, 0, true]}', '{"notes": [3, 0, "2"]}', '{"autre": [1, 2, 3]}', "pas de json",
                    "{pas json}", '[3, 0, 1]', ""):
        assert juge.analyser_notes(mauvais, 3) is None, mauvais


def test_consigne_du_juge_epinglee_par_son_empreinte():
    """Consigne des preuves publiées : la modifier change les clés du cache et rend les 300 jugements non rejouables."""
    import hashlib

    assert hashlib.sha256(juge.SYSTEME.encode()).hexdigest() == (
        "04792910be6865b75079d10c2565c73e8635874112ba3339c521feb985c272c1")
    assert juge.CONSIGNE.is_file() and juge.SYSTEME and not juge.SYSTEME.endswith("\n")


def test_juge_reclassement_et_presentation():
    assert juge.reclasser(["A", "B", "C", "D"], {"A": 0, "B": 3, "C": 3, "D": 1}) == ["B", "C", "D", "A"]
    assert juge.reclasser(["A", "B"], {"A": 1, "B": 1}) == ["A", "B"]  # égalité : rang initial conservé
    assert juge.reclasser(["A", "B"], {}) == ["A", "B"]
    ids = [f"P{i:03d}" for i in range(10)]
    ordre = juge.ordre_presentation(ids, "Q001|m")
    assert sorted(ordre) == ids and ordre == juge.ordre_presentation(ids, "Q001|m")
    assert ordre != ids and ordre != juge.ordre_presentation(ids, "Q002|m")
    assert juge.ordre_presentation(list(reversed(ids)), "Q001|m") == ordre  # indépendant de l'ordre d'entrée


def test_juger_cache_et_reponse_illisible(serveur, tmp_path):
    cache = mod_cache.Cache(tmp_path / "c")
    client = _client(serveur)
    passages = {"A": "texte a", "B": "texte b", "C": "texte c"}
    notes = juge.juger(client, cache, "opsys-haiku-5-5", "Q001", "question", ["A", "B", "C"], passages)
    ordre = juge.ordre_presentation(["A", "B", "C"], "Q001|opsys-haiku-5-5")
    assert notes == dict(zip(ordre, [3, 0, 1], strict=True))  # les notes suivent l'ordre de PRÉSENTATION
    message = serveur.requetes[-1]["messages"][1]["content"]
    assert message.index("texte " + ordre[0][0].lower()) < message.index("texte " + ordre[1][0].lower())
    assert "Q001" not in message and "A" not in re.sub(r"Question|Passages", "", message).replace("texte a", "")
    n = len(serveur.requetes)
    assert juge.juger(client, cache, "opsys-haiku-5-5", "Q001", "question", ["A", "B", "C"], passages) == notes
    assert len(serveur.requetes) == n  # deuxième appel servi par le cache
    assert cache.appels("juge")[0]["jetons"] == 100 and cache.appels("juge")[0]["jetons_sortie"] == 10
    serveur.reponse_discussion = "je ne sais pas"
    assert juge.juger(client, cache, "opsys-haiku-5-5", "Q002", "autre", ["A", "B", "C"], passages) is None
    with pytest.raises(RuntimeError):  # --sans-appel : jugement absent du cache
        juge.juger(None, cache, "opsys-haiku-5-5", "Q009", "nouvelle", ["A", "B", "C"], passages)


# ===== exécution de bout en bout
TARIFS = {"usd_par_jeton": {"m-un": {"entree": "0.00000002", "sortie": "0"},
                            "m-deux": {"entree": "0.0000002", "sortie": "0"},
                            "opsys-haiku-5-5": {"entree": "0.0000001", "sortie": "0.0000005"}},
          "contexte_maximal_amont": {"m-un": 512}}


def test_executer_de_bout_en_bout_avec_faux_serveur(serveur, tmp_path):
    corpus = mod_corpus.charger_corpus(DOSSIER_CORPUS)
    cache = mod_cache.Cache(tmp_path / "c")
    configs = (banc.Config("un", "m-un", "premier"), banc.Config("deux", "m-deux", "second", input_type=True))
    serveur.depense = 0.0
    r = banc.executer(corpus, cache, _client(serveur), configs=configs, tarifs=TARIFS, modele_juge="opsys-haiku-5-5",
                      sonde=5, etiquette="essai")
    assert r["schema"] == banc.SCHEMA_RESULTATS and r["corpus"]["requetes"] == len(corpus.requetes)
    assert r["corpus"]["requetes_sans_reponse"] == 12 and r["corpus"]["fictif"] is True
    for ident in ("un", "deux"):
        b = r["configurations"][ident]
        assert b["vecteur"]["dimension"] == 32 and b["latence"]["requete_isolee"]["n"] == 5
        for systeme in ("vecteurs", "hybride"):
            m = b[systeme]["propre"]
            assert m["n"] == 92
            for cle in ("mrr@10", "rappel@1", "rappel@5", "rappel@10", "ndcg@10"):
                assert 0.0 <= m[cle]["ic95"][0] <= m[cle]["moyenne"] <= m[cle]["ic95"][1] <= 1.0
            assert m["rappel@1"]["moyenne"] <= m["rappel@5"]["moyenne"] <= m["rappel@10"]["moyenne"]
            assert set(b[systeme]["par_type"]) == {t for t in mod_corpus.TYPES_REQUETE if t != "negative"}
        assert b["cout"]["jetons_documents"] > 0 and b["cout"]["usd_mesure"] > 0
        assert 0.0 <= b["abstention"]["auc"] <= 1.0 and "seuil_produit" in b
        assert b["hybride_bm25_demi_poids_exploratoire"]["avertissement"].startswith("choisi APRÈS")
        assert set(r["comparaisons"][ident]) == {"vecteurs_contre_bm25_mrr", "hybride_contre_bm25_mrr",
                                                 "hybride_contre_vecteurs_mrr", "hybride_contre_bm25_ndcg"}
    entre = r["entre_modeles_mrr"]
    assert set(entre) == {"un", "deux"} and set(entre["un"]) == {"deux"}
    assert entre["un"]["deux"]["ecart"] == pytest.approx(-entre["deux"]["un"]["ecart"], abs=1e-4)  # antisymétrie
    assert "ligne − colonne" in banc.tableau_entre_modeles(r) and "·" in banc.tableau_entre_modeles(r)
    assert r["configurations"]["un"]["cout"]["usd_par_million_de_jetons"] == pytest.approx(0.02)
    assert r["configurations"]["deux"]["cout"]["usd_par_million_de_jetons"] == pytest.approx(0.2)
    assert r["systemes_locaux"]["bm25_fts5"]["propre"]["n"] == 92
    assert "double_hachage" in r["systemes_locaux"]
    j = r["juge"]
    assert "lex" in j["sources"] and len(j["sources"]) == 3
    assert {c.split(":")[1] for c in j["sources"] if c != "lex"} == {"vec", "hyb"}
    for s in j["sources"].values():
        assert s["questions_avec_reponse"] == 92 and s["questions_sans_reponse"] == 12
        assert s["reponses_illisibles"] >= 0 and "mrr_apres_moins_avant" in s
    assert j["usd_estime_par_tarif"] > 0 and j["appels_cumules"] > 0
    assert j["usd_rapporte_par_la_passerelle"] == pytest.approx(0.0001 * j["appels_cumules"])
    # le résultat se sérialise, et ne contient ni la clé ni un vecteur
    texte = json.dumps(r, ensure_ascii=False)
    assert CLE_FICTIVE not in texte and "0.0123456" not in texte
    # rejouer sans appel donne les MÊMES métriques (cache + journal), à l'horodatage près
    r2 = banc.executer(corpus, cache, None, configs=configs, tarifs=TARIFS, sonde=5, etiquette="essai")
    assert r2["configurations"]["un"]["vecteurs"] == r["configurations"]["un"]["vecteurs"]
    assert r2["configurations"]["deux"]["hybride"] == r["configurations"]["deux"]["hybride"]
    assert r2["configurations"]["un"]["cout"] == r["configurations"]["un"]["cout"]


def test_executer_isole_la_panne_d_une_configuration(serveur, tmp_path):
    corpus = mod_corpus.charger_corpus(DOSSIER_CORPUS)
    serveur.mode = "http400"
    r = banc.executer(corpus, mod_cache.Cache(tmp_path / "c"), _client(serveur),
                      configs=(banc.Config("un", "m-un", "premier"),), tarifs=TARIFS, sonde=0)
    assert "erreur" in r["configurations"]["un"] and CLE_FICTIVE not in json.dumps(r)
    assert r["systemes_locaux"]["bm25_fts5"]["propre"]["n"] == 92  # le local est mesuré malgré la panne


def test_tableau_markdown_et_cli_verifier(serveur, tmp_path, capsys):
    corpus = mod_corpus.charger_corpus(DOSSIER_CORPUS)
    r = banc.executer(corpus, mod_cache.Cache(tmp_path / "c"), _client(serveur),
                      configs=(banc.Config("un", "m-un", "premier"),), tarifs=TARIFS, sonde=0)
    tableau = banc.tableau_markdown(r)
    assert tableau.count("\n") >= 4 and "BM25 FTS5" in tableau and "un + BM25 (RRF)" in tableau
    assert banc.main(["verifier"]) == 0
    assert '"corpus": "valide"' in capsys.readouterr().out


def test_tableaux_complets_sur_le_resultat_reel_publie():
    """Les tableaux du rapport se régénèrent depuis le JSON de preuve publié, avec les valeurs qu'il contient."""
    preuves = sorted((RACINE / "docs" / "qualification" / "preuves-embeddings-fr").glob("mesure-*.json"))
    assert preuves, "aucune preuve publiée"
    for chemin in preuves:
        r = json.loads(chemin.read_text(encoding="utf-8"))
        assert r["schema"] == banc.SCHEMA_RESULTATS and r["corpus"]["fictif"] is True
        assert CLE_FICTIVE not in chemin.read_text(encoding="utf-8")
        texte = banc.tableaux_complets(r)
        for titre in ("Qualité de classement", "MRR@10 par type de question", "Écarts appariés entre modèles",
                      "Hybride contre vecteurs seuls",
                      "Robustesse aux fautes", "Questions sans réponse", "Exploitation", "Reclassement par juge"):
            assert f"### {titre}" in texte or titre in texte
        premier = next(iter(r["configurations"].values()))
        assert f"{premier['vecteurs']['propre']['mrr@10']['moyenne']:.3f}" in texte


def test_tableaux_valeurs_formatees():
    assert banc._ecart({"ecart": 0.0244, "ic95": [-0.0028, 0.0546]}) == "+0.024 [-0.003 ; +0.055]"
    assert banc._ic({"moyenne": 0.5, "ic95": [0.25, 0.75]}) == "0.500 [0.250 ; 0.750]"
    assert banc._oui(True) == "oui" and banc._oui(False) == "non"
    assert banc._tableau(["a", "b"], [[1, 2]]) == "| a | b |\n|---|---|\n| 1 | 2 |"
    assert banc.tableau_juge({"corpus": {}}) == "(aucun reclassement exécuté)"


def test_cli_mesurer_exige_url_et_cle_et_n_ecrase_jamais(serveur, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(passerelle.ENV_URL, raising=False)
    monkeypatch.delenv(passerelle.ENV_CLE_FICHIER, raising=False)
    cache, sortie = tmp_path / "cache", tmp_path / "sortie"
    assert banc.main(["mesurer", "--cache", str(cache), "--sortie", str(sortie)]) == 2  # ni URL ni clé : refus
    cle = tmp_path / "cle"
    cle.write_text(CLE_FICTIVE, encoding="utf-8")
    argv = ["mesurer", "--cache", str(cache), "--sortie", str(sortie), "--url", serveur.url, "--cle-fichier", str(cle),
            "--configs", "voyage-4", "--sonde", "0"]
    assert banc.main(argv) == 0
    sortie_texte = capsys.readouterr().out
    assert CLE_FICTIVE not in sortie_texte and "voyage-4 (vecteurs)" in sortie_texte
    fichiers = list(sortie.glob("mesure-*.json"))
    assert len(fichiers) == 1 and CLE_FICTIVE not in fichiers[0].read_text(encoding="utf-8")
    assert banc.main(["rapport", "--resultats", str(fichiers[0])]) == 0
    # sans appel : le cache suffit (aucune panne même serveur coupé), et un fichier de plus apparaît
    serveur.mode = "http500_toujours"
    n = len(serveur.requetes)
    import time
    time.sleep(1.1)  # horodatage à la seconde : un nom de preuve distinct
    rejeu = ["mesurer", "--cache", str(cache), "--sortie", str(sortie), "--configs", "voyage-4", "--sonde", "0",
             "--sans-appel"]
    assert banc.main(rejeu) == 0
    assert len(serveur.requetes) == n and len(list(sortie.glob("mesure-*.json"))) == 2


def test_configurations_couvrent_les_quatre_modeles_demandes():
    modeles = {c.modele for c in banc.CONFIGURATIONS}
    assert modeles == {"opsys-embed-e5-multilingue", "opsys-embed-gemini-2", "opsys-embed-voyage-4",
                       "opsys-embed-voyage-4-lite"}
    assert len({c.identifiant for c in banc.CONFIGURATIONS}) == len(banc.CONFIGURATIONS)
    tarifs = json.loads((RACINE / "install" / "qualification" / "embeddings_fr" / "tarifs.json").read_text("utf-8"))
    assert all(m in tarifs["usd_par_jeton"] for m in modeles) and "opsys-haiku-5-5" in tarifs["usd_par_jeton"]
    e5 = next(c for c in banc.CONFIGURATIONS if c.identifiant == "e5-large-prefixes")
    assert e5.prefixe_requete == "query: " and e5.prefixe_document == "passage: "


def test_aucun_secret_dans_les_fichiers_du_banc():
    cle_reelle = Path("/tmp/claude-1000/-tmp/67e51219-6449-4d92-98d1-fbc071b4eb81/scratchpad/secrets/litellm_opsys.key")
    dossier = RACINE / "install" / "qualification" / "embeddings_fr"
    fichiers = [f for f in dossier.rglob("*") if f.is_file() and f.suffix in {".py", ".yaml", ".json", ".md"}]
    fichiers.append(Path(__file__))
    fichiers += list((RACINE / "docs" / "qualification").glob("*EMBEDDINGS*"))
    fichiers += list((RACINE / "docs" / "qualification" / "preuves-embeddings-fr").glob("*"))
    assert len(fichiers) >= 10
    reelle = cle_reelle.read_text(encoding="utf-8").strip() if cle_reelle.exists() else None
    for f in fichiers:
        contenu = f.read_text(encoding="utf-8", errors="replace")
        if reelle:
            assert reelle not in contenu, f.name
        assert not re.search(r"sk-[A-Za-z0-9]{20,}", contenu.replace(CLE_FICTIVE, "")), f.name


# ===== réglages repris du produit : le banc mesure CE que le produit fait, pas une variante
def test_reglages_du_banc_egaux_a_ceux_de_la_recherche_du_produit():
    from opsys.connaissances.recherche import Reglages

    produit = Reglages()
    assert produit.rrf_k == banc.RRF_K and produit.candidats == banc.PROFONDEUR
    assert produit.seuil_vectoriel == banc.SEUIL_VECTORIEL_PRODUIT
    assert produit.seuil_couverture == lexical_local.COUVERTURE_PAR_DEFAUT


def test_lexique_couverture_a_la_frontiere():
    lx = lexical_local.Lexique({"A": "gouttière aluminium", "B": "facture virement"})
    # « gouttiere zzz » : un terme sur deux trouvé dans A -> couverture exactement 0,5 : retenu à 0,5, écarté à 0,6
    assert lexical_local.identifiants(lx.classer("gouttiere zzzz", couverture=0.5)) == ["A"]
    assert lx.classer("gouttiere zzzz", couverture=0.6) == []
    lx.fermer()
