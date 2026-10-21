
import copy
import hashlib
from pathlib import Path

import yaml
from m7_marketing.aeo import aeo_engine

_M7 = Path(__file__).resolve().parents[2]


SEO_KNOWLEDGE_PATH = _M7 / "docs" / "seo-knowledge.v1.yaml"


def _load_seo_knowledge_local():
    with open(SEO_KNOWLEDGE_PATH, 'rb') as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()
    content = yaml.safe_load(data)
    return content, sha


def _artifact(html, surface, timestamp="2026-06-01T00:00:00Z", content_item=None):
    _, sha = _load_seo_knowledge_local()
    return {
        "surface": surface,
        "html": html,
        "jsonld": [],
        "content_item": content_item,
        "timestamp": timestamp,
        "seo_knowledge_sha256": sha
    }


# ---------- A-01 : title ≤60 ----------
def test_a01_conforme():
    html = "<html><head><title>Mon Titre SEO</title></head><body></body></html>"
    art = _artifact(html, "google_aio")
    verdicts = aeo_engine.evaluate(art)["surface_reports"]["google_aio"]
    v = [v for v in verdicts if v["rule_id"] == "A-01"][0]
    assert v["verdict"] == "conforme"

def test_a01_non_conforme():
    html = "<html><head><title>" + "x" * 61 + "</title></head><body></body></html>"
    art = _artifact(html, "google_aio")
    verdicts = aeo_engine.evaluate(art)["surface_reports"]["google_aio"]
    v = [v for v in verdicts if v["rule_id"] == "A-01"][0]
    assert v["verdict"] == "non_conforme"


# ---------- A-02 : meta description ≤160 ----------
def test_a02_conforme():
    html = (
        '<html><head><meta name="description" '
        'content="Description SEO de moins de 160 caractères."></head><body></body></html>'
    )
    art = _artifact(html, "google_aio")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["google_aio"] if v["rule_id"] == "A-02"][0]
    assert v["verdict"] == "conforme"

def test_a02_non_conforme():
    html = '<html><head><meta name="description" content="' + "d" * 161 + '"></head><body></body></html>'
    art = _artifact(html, "google_aio")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["google_aio"] if v["rule_id"] == "A-02"][0]
    assert v["verdict"] == "non_conforme"


# ---------- A-03 : h1 unique ----------
def test_a03_conforme():
    html = "<html><body><h1>Titre unique</h1></body></html>"
    art = _artifact(html, "google_aio")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["google_aio"] if v["rule_id"] == "A-03"][0]
    assert v["verdict"] == "conforme"

def test_a03_non_conforme():
    # pas de h1
    html = "<html><body><h2>Pas de H1</h2></body></html>"
    art = _artifact(html, "google_aio")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["google_aio"] if v["rule_id"] == "A-03"][0]
    assert v["verdict"] == "non_conforme"


# ---------- A-04 : schema.org présent ----------
def test_a04_conforme():
    html = """<html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"WebSite","name":"Test"}
    </script></head><body></body></html>"""
    art = _artifact(html, "google_aio")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["google_aio"] if v["rule_id"] == "A-04"][0]
    assert v["verdict"] == "conforme"

def test_a04_non_conforme():
    html = "<html><head></head><body></body></html>"
    art = _artifact(html, "google_aio")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["google_aio"] if v["rule_id"] == "A-04"][0]
    assert v["verdict"] == "non_conforme"


# ---------- A-05 : ≥3 liens internes ----------
def test_a05_conforme():
    html = '<html><body><a href="/page1"></a><a href="/page2"></a><a href="/page3"></a></body></html>'
    art = _artifact(html, "google_aio")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["google_aio"] if v["rule_id"] == "A-05"][0]
    assert v["verdict"] == "conforme"

def test_a05_non_conforme():
    html = '<html><body><a href="/page1"></a></body></html>'
    art = _artifact(html, "google_aio")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["google_aio"] if v["rule_id"] == "A-05"][0]
    assert v["verdict"] == "non_conforme"


# ---------- A-06 : statistique chiffrée sourcée ----------
def test_a06_conforme():
    html = '<p>87 % <span data-source="Étude X">d\'augmentation</span></p>'
    art = _artifact(html, "perplexity")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["perplexity"] if v["rule_id"] == "A-06"][0]
    assert v["verdict"] == "conforme"

def test_a06_candidat_sans_source():
    html = '<p>87 % augmentation</p>'
    art = _artifact(html, "perplexity")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["perplexity"] if v["rule_id"] == "A-06"][0]
    assert v["verdict"] == "candidat_a_verifier"

def test_a06_non_conforme_absent():
    html = '<p>Aucun chiffre ici.</p>'
    art = _artifact(html, "perplexity")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["perplexity"] if v["rule_id"] == "A-06"][0]
    assert v["verdict"] == "non_conforme"


# ---------- A-07 : citation attribuée ----------
def test_a07_conforme_blockquote():
    html = '<blockquote cite="https://example.com">Une citation</blockquote>'
    art = _artifact(html, "perplexity")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["perplexity"] if v["rule_id"] == "A-07"][0]
    assert v["verdict"] == "conforme"

def test_a07_conforme_guillemets_auteur():
    html = '<p>« Une citation » - Auteur</p>'
    art = _artifact(html, "perplexity")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["perplexity"] if v["rule_id"] == "A-07"][0]
    assert v["verdict"] == "conforme"

def test_a07_non_conforme():
    html = '<p>Pas de citation.</p>'
    art = _artifact(html, "perplexity")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["perplexity"] if v["rule_id"] == "A-07"][0]
    assert v["verdict"] == "non_conforme"


# ---------- A-08 : NAP cohérent entre texte et JSON-LD LocalBusiness ----------
def test_a08_conforme():
    html = """<html><body>
    <p>Contact : +1234567890, MonEntreprise</p>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"LocalBusiness","name":"MonEntreprise","telephone":"+1234567890"}
    </script>
    </body></html>"""
    art = _artifact(html, "perplexity")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["perplexity"] if v["rule_id"] == "A-08"][0]
    assert v["verdict"] == "conforme"

def test_a08_non_conforme():
    html = """<html><body>
    <p>Contact : +9876543210, AutreEntreprise</p>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"LocalBusiness","name":"MonEntreprise","telephone":"+1234567890"}
    </script>
    </body></html>"""
    art = _artifact(html, "perplexity")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["perplexity"] if v["rule_id"] == "A-08"][0]
    assert v["verdict"] == "non_conforme"


def test_a08_conforme_homeandconstructionbusiness():
    """RED — bug corrigé (R9 §1.4) : A-08 exigeait auparavant le littéral strict
    "LocalBusiness", alors que site/generator.py (après correctif) émet désormais
    "HomeAndConstructionBusiness" (sous-type STRICT de LocalBusiness, schema.org) — une
    contradiction interne qui rendait le site généré structurellement incapable de passer
    A-08. HomeAndConstructionBusiness doit être accepté au même titre que LocalBusiness."""
    html = """<html><body>
    <p>Contact : +1234567890, MonEntreprise</p>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"HomeAndConstructionBusiness","name":"MonEntreprise","telephone":"+1234567890"}
    </script>
    </body></html>"""
    art = _artifact(html, "perplexity")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["perplexity"] if v["rule_id"] == "A-08"][0]
    assert v["verdict"] == "conforme"


def test_a08_non_conforme_type_hors_ensemble_accepte():
    """Un @type hors de l'ensemble accepté (ni LocalBusiness ni un sous-type connu) reste
    non_conforme — l'élargissement à HomeAndConstructionBusiness n'ouvre pas la porte à
    n'importe quel type."""
    html = """<html><body>
    <p>Contact : +1234567890, MonEntreprise</p>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Organization","name":"MonEntreprise","telephone":"+1234567890"}
    </script>
    </body></html>"""
    art = _artifact(html, "perplexity")
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["perplexity"] if v["rule_id"] == "A-08"][0]
    assert v["verdict"] == "non_conforme"


# ---------- A-09 : <time datetime> ≤12 mois du timestamp fourni ----------
def test_a09_conforme():
    ts = "2026-06-15T00:00:00Z"
    recent_date = "2026-01-15"
    html = f'<time datetime="{recent_date}">January 2026</time>'
    art = _artifact(html, "perplexity", timestamp=ts)
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["perplexity"] if v["rule_id"] == "A-09"][0]
    assert v["verdict"] == "conforme"

def test_a09_non_conforme():
    ts = "2026-06-15T00:00:00Z"
    old_date = "2024-01-15"
    html = f'<time datetime="{old_date}">Old</time>'
    art = _artifact(html, "perplexity", timestamp=ts)
    v = [v for v in aeo_engine.evaluate(art)["surface_reports"]["perplexity"] if v["rule_id"] == "A-09"][0]
    assert v["verdict"] == "non_conforme"


def build_item_artifact(item, surface, timestamp="2026-06-01T00:00:00Z"):
    """Helper pour créer un artifact avec un content_item (règle A-10)."""
    html = f"<html><body><p>{item['body']}</p></body></html>"
    return _artifact(html, surface, timestamp=timestamp, content_item=item)








def test_propagation_candidat():
    sk, _ = aeo_engine.load_seo_knowledge(SEO_KNOWLEDGE_PATH)
    sk_mod = copy.deepcopy(sk)

    # Trouver la tactique perplexity contenant « Fraîcheur »
    tactiques = sk_mod.get("surfaces", {}).get("perplexity", {}).get("tactiques", [])
    fraicheur_trouvee = False
    for value in tactiques:
        if isinstance(value, dict) and "Fraîcheur" in value.get("tactique", ""):
            value["statut"] = "candidat_a_verifier"
            fraicheur_trouvee = True
            break
    assert fraicheur_trouvee, "Tactique 'Fraîcheur' non trouvée dans le dépôt perplexity"

    # Vérification de l'héritage
    assert aeo_engine._get_inherited_status("A-09", sk_mod) == "candidat_a_verifier"
    assert aeo_engine._get_inherited_status("A-09", sk) == "valide"

    # Vérification de _apply_inheritance
    assert aeo_engine._apply_inheritance("conforme", "candidat_a_verifier") == "candidat_a_verifier"
    assert aeo_engine._apply_inheritance("non_conforme", "candidat_a_verifier") == "non_conforme"

    # Intégration : construire un artifact perplexity avec <time datetime="2026-06-01">
    html = "<html><body><time datetime=\"2026-06-01\">Juin 2026</time></body></html>"
    artifact = {
        "html": html,
        "surface": "perplexity",
        "timestamp": "2026-07-25T00:00:00+00:00",
        "content_item": None,
    }
    data = aeo_engine._parse_html(html, artifact)
    verdict_obj = aeo_engine._a09(data, artifact, sk_mod)
    assert verdict_obj["verdict"] == "candidat_a_verifier"



def test_rapport_trie_et_deterministe():
    html = "<html><head><title>Test de tri</title></head><body><p>Texte</p></body></html>"
    art = _artifact(html, "perplexity")
    rapport1 = aeo_engine.evaluate(art)
    rapport2 = aeo_engine.evaluate(art)
    assert rapport1 == rapport2, "Les rapports doivent être identiques (déterministes)"

    # Vérifier le tri des rule_ids dans chaque surface_reports
    for surface, reports in rapport1["surface_reports"].items():
        rule_ids = [r["rule_id"] for r in reports]
        assert rule_ids == sorted(rule_ids), f"rule_ids non triés pour {surface}: {rule_ids}"

    # Vérifier que "score" n'apparaît nulle part dans la sérialisation
    import json
    serialized = json.dumps(rapport1).lower()
    assert "score" not in serialized, "Le mot 'score' est présent dans le rapport"


TIMESTAMP = "2026-06-15T12:00:00Z"

def test_a10_conforme():
    contract_path = _M7 / "contracts" / "brand-contract.v1.yaml"
    expected_brand = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    item = {
        "title": "Test conforme A-10",
        "body": "corps test",
        "brand_ref": expected_brand,
        "tactics_applied": [],
    }
    art = aeo_engine.build_item_artifact(item, SEO_KNOWLEDGE_PATH, TIMESTAMP)
    reports = aeo_engine.evaluate(art)["surface_reports"]["assistants_ia"]
    v = [v for v in reports if v["rule_id"] == "A-10"][0]
    assert v["verdict"] == "conforme"


def test_a10_non_conforme():
    wrong_ref = hashlib.sha256(b"different").hexdigest()
    item = {
        "title": "Test non conforme A-10",
        "body": "corps test",
        "brand_ref": wrong_ref,
        "tactics_applied": [],
    }
    art = aeo_engine.build_item_artifact(item, SEO_KNOWLEDGE_PATH, TIMESTAMP)
    reports = aeo_engine.evaluate(art)["surface_reports"]["assistants_ia"]
    v = [v for v in reports if v["rule_id"] == "A-10"][0]
    assert v["verdict"] == "non_conforme"
