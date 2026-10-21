import contextlib
import hashlib
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

import yaml

_M7 = Path(__file__).resolve().parents[3]
SEO_KNOWLEDGE_PATH = _M7 / "docs" / "seo-knowledge.v1.yaml"

# schema.org : HomeAndConstructionBusiness est un sous-type STRICT de LocalBusiness
# (https://schema.org/HomeAndConstructionBusiness). A-08 accepte LocalBusiness et ses
# sous-types explicitement connus du produit — jamais seulement le littéral "LocalBusiness" —
# pour rester cohérent avec site/guardrail.py règle G-15, qui accepte le même ensemble
# (contradiction interne corrigée des deux côtés à la fois, cf. R9 §1.4).
TYPES_LOCALBUSINESS = frozenset({"LocalBusiness", "HomeAndConstructionBusiness"})


# ---------------------------------------------------------------------------
# HTML parser used throughout the module
# ---------------------------------------------------------------------------
_VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
                  "meta", "param", "source", "track", "wbr"}


class _ArtifactParser(HTMLParser):
    def __init__(self, strict=False):
        super().__init__()
        self._strict = strict
        self._tag_stack = []
        self.title = None
        self.meta_desc = None
        self.h1_texts = []
        self.internal_links = 0
        self.jsonld_scripts = []
        self.has_data_source = False
        self.has_cite_blockquote = False
        self.time_datetime = None
        self.text_parts = []

        self._in_title = False
        self._in_h1 = False
        self._in_script = False
        self._in_style = False
        self._current_data = []
        self._script_type = None

    def error(self, message):
        if self._strict:
            raise ValueError(f"parse_error: {message}")

    def close_and_check(self):
        self.close()
        if self._tag_stack:
            raise ValueError(f"parse_error: balises non fermées: {', '.join(self._tag_stack)}")

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag not in _VOID_ELEMENTS:
            self._tag_stack.append(tag)
        if tag == "title":
            self._in_title = True
            self._current_data = []
        elif tag == "h1":
            self._in_h1 = True
            self._current_data = []
        elif tag == "meta":
            if attrs_dict.get("name", "").lower() == "description":
                self.meta_desc = attrs_dict.get("content", "")
        elif tag == "a":
            href = attrs_dict.get("href", "")
            if href.startswith("/"):
                self.internal_links += 1
        elif tag == "script":
            if attrs_dict.get("type") == "application/ld+json":
                self._in_script = True
                self._current_data = []
                self._script_type = "ld+json"
            else:
                self._in_script = True
        elif tag == "style":
            self._in_style = True
        elif tag == "blockquote":
            if "cite" in attrs_dict:
                self.has_cite_blockquote = True
        elif tag == "time":
            dt = attrs_dict.get("datetime")
            if dt:
                self.time_datetime = dt
        if "data-source" in attrs_dict:
            self.has_data_source = True

    def handle_endtag(self, tag):
        if tag not in _VOID_ELEMENTS:
            # Dépilage tolérant : retire jusqu'au tag correspondant s'il est ouvert
            try:
                pos = len(self._tag_stack) - 1 - self._tag_stack[::-1].index(tag)
            except ValueError:
                pass
            else:
                self._tag_stack = self._tag_stack[:pos]
        if tag == "title":
            self.title = "".join(self._current_data).strip()
            self._in_title = False
        elif tag == "h1":
            self.h1_texts.append("".join(self._current_data).strip())
            self._in_h1 = False
        elif tag == "script":
            if self._in_script and self._script_type == "ld+json":
                script_text = "".join(self._current_data).strip()
                parsed = None
                # Fail-soft voulu (parsed=None, brut conservé) ; rétréci à
                # ValueError (JSONDecodeError) pour ne plus masquer les
                # erreurs de programmation.
                with contextlib.suppress(ValueError):
                    parsed = json.loads(script_text)
                self.jsonld_scripts.append({"raw": script_text, "parsed": parsed})
            self._in_script = False
            self._script_type = None
        elif tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_style or self._in_script:
            if self._in_script and self._script_type == "ld+json":
                self._current_data.append(data)
            return
        if self._in_title or self._in_h1:
            self._current_data.append(data)
        else:
            self.text_parts.append(data)


def _parse_html(html_string, strict=False):
    parser = _ArtifactParser(strict=strict)
    parser.feed(html_string)
    return parser


# ---------------------------------------------------------------------------
# Knowledge loading and inheritance helpers
# ---------------------------------------------------------------------------
def load_seo_knowledge(path):
    with open(path, "rb") as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()
    content = yaml.safe_load(data)
    return content, sha


# Liaison règle -> tactique seo-knowledge (structure réelle : surfaces.<s>.tactiques[].tactique).
# Seules les liaisons SÉMANTIQUEMENT VRAIES sont déclarées ; « Crawlabilité des bots IA »
# (candidat_a_verifier) n'est opérationnalisée par AUCUNE règle on-page : elle est mesurée par
# S010 C-06 (robots.txt) — absence de liaison = héritage « valide » (pas de plafonnement artificiel).
_RULE_TACTIQUE = {
    "A-04": ("google_aio", "Rendu"),
    "A-06": ("perplexity", "Citations"),
    "A-07": ("perplexity", "Citations"),
    "A-08": ("perplexity", "Cohérence"),
    "A-09": ("perplexity", "Fraîcheur"),
    "A-10": ("assistants_ia", "Cohérence"),
}


def _get_inherited_status(rule_id, knowledge):
    mapping = _RULE_TACTIQUE.get(rule_id)
    if mapping is None:
        return "valide"
    surface, keyword = mapping
    if "surfaces" not in knowledge or surface not in knowledge["surfaces"]:
        return "valide"
    for tactic in knowledge["surfaces"][surface].get("tactiques", []):
        if isinstance(tactic, dict) and keyword.lower() in tactic.get("tactique", "").lower():
            return tactic.get("statut", "valide")
    return "valide"


def _apply_inheritance(initial_verdict, inherited_status):
    if inherited_status == "candidat_a_verifier" and initial_verdict == "conforme":
        return "candidat_a_verifier"
    return initial_verdict


def _mk_verdict(rule_id, surface, origin, inherited_status, measured_fact, verdict):
    return {
        "rule_id": rule_id,
        "surface": surface,
        "origin": origin,
        "inherited_status": inherited_status,
        "measured_fact": measured_fact,
        "verdict": _apply_inheritance(verdict, inherited_status),
    }


# ---------------------------------------------------------------------------
# Individual rule functions
# ---------------------------------------------------------------------------
def _a01(data, artifact, knowledge):
    if not data.title:
        measured = "title_missing"
        verdict = "non_conforme"
    else:
        length = len(data.title)
        measured = f"title_len={length}"
        verdict = "conforme" if length <= 60 else "non_conforme"
    inherited = _get_inherited_status("A-01", knowledge)
    return _mk_verdict("A-01", "google_aio", "google_officielle_2026", inherited, measured, verdict)


def _a02(data, artifact, knowledge):
    if not data.meta_desc:
        measured = "meta_description_missing"
        verdict = "non_conforme"
    else:
        length = len(data.meta_desc)
        measured = f"meta_description_len={length}"
        verdict = "conforme" if length <= 160 else "non_conforme"
    inherited = _get_inherited_status("A-02", knowledge)
    return _mk_verdict("A-02", "google_aio", "google_officielle_2026", inherited, measured, verdict)


def _a03(data, artifact, knowledge):
    non_empty_h1s = [h for h in data.h1_texts if h]
    count = len(non_empty_h1s)
    if count == 1:
        measured = "h1_count=1"
        verdict = "conforme"
    else:
        measured = f"h1_count={count}"
        verdict = "non_conforme"
    inherited = _get_inherited_status("A-03", knowledge)
    return _mk_verdict("A-03", "google_aio", "google_officielle_2026", inherited, measured, verdict)


def _a04(data, artifact, knowledge):
    if data.jsonld_scripts:
        measured = "schema_org_present"
        verdict = "conforme"
    else:
        measured = "schema_org_missing"
        verdict = "non_conforme"
    inherited = _get_inherited_status("A-04", knowledge)
    return _mk_verdict("A-04", "google_aio", "google_officielle_2026", inherited, measured, verdict)


def _a05(data, artifact, knowledge):
    internal = data.internal_links
    measured = f"internal_links={internal}"
    verdict = "conforme" if internal >= 3 else "non_conforme"
    inherited = _get_inherited_status("A-05", knowledge)
    return _mk_verdict("A-05", "google_aio", "google_officielle_2026", inherited, measured, verdict)


def _a06(data, artifact, knowledge):
    text = " ".join(data.text_parts)
    has_number = bool(re.search(r"\d+[\s%]", text))
    if has_number:
        if data.has_data_source:
            measured = "stat_chiffree_sourcee"
            verdict = "conforme"
        else:
            measured = "stat_chiffree_sans_source_explicite"
            verdict = "candidat_a_verifier"
    else:
        measured = "aucune_stat_chiffree"
        verdict = "non_conforme"
    inherited = _get_inherited_status("A-06", knowledge)
    return _mk_verdict("A-06", "perplexity", "princeton", inherited, measured, verdict)


def _a07(data, artifact, knowledge):
    text = " ".join(data.text_parts)
    has_blockquote_cite = data.has_cite_blockquote
    has_guillemet = bool(re.search(r"«[^»]+»\s*-\s*\S", text))
    if has_blockquote_cite or has_guillemet:
        measured = "citation_attribuee"
        verdict = "conforme"
    else:
        measured = "citation_non_attribuee"
        verdict = "non_conforme"
    inherited = _get_inherited_status("A-07", knowledge)
    return _mk_verdict("A-07", "perplexity", "princeton", inherited, measured, verdict)


def _a08(data, artifact, knowledge):
    # Look for LocalBusiness in JSON-LD scripts
    lb = None
    for script_info in data.jsonld_scripts:
        parsed = script_info["parsed"]
        if isinstance(parsed, dict) and parsed.get("@type") in TYPES_LOCALBUSINESS:
            lb = parsed
            break
    if not lb:
        measured = "pas_de_localbusiness_jsonld"
        verdict = "non_conforme"
    else:
        lb_tel = lb.get("telephone", "")
        lb_name = lb.get("name", "")
        lb_tel_norm = re.sub(r"[\s\-\.\(\)]", "", lb_tel).lower()
        lb_name_norm = lb_name.strip().lower()

        text = " ".join(data.text_parts)
        # Extract telephone number (E.164-like) and the following name fragment
        tel_match = re.search(r"(\+[\d\s\-\.\(\)]+)", text)
        if tel_match:
            txt_tel = tel_match.group(1)
            txt_tel_norm = re.sub(r"[\s\-\.\(\)]", "", txt_tel).lower()
            after_tel = text[tel_match.end() :]
            parts = after_tel.split(",")
            txt_name = parts[-1].strip() if len(parts) > 1 else after_tel.strip()
            txt_name_norm = txt_name.lower()
        else:
            txt_tel_norm = None
            txt_name_norm = None

        if txt_tel_norm is None:
            measured = "pas_de_telephone_dans_texte"
            verdict = "non_conforme"
        else:
            tel_ok = txt_tel_norm == lb_tel_norm
            name_ok = txt_name_norm == lb_name_norm
            if tel_ok and name_ok:
                measured = "nap_coherent"
                verdict = "conforme"
            else:
                measured = "nap_incoherent"
                verdict = "non_conforme"

    inherited = _get_inherited_status("A-08", knowledge)
    return _mk_verdict("A-08", "perplexity", "princeton", inherited, measured, verdict)


def _a09(data, artifact, knowledge):
    time_dt_str = data.time_datetime
    if not time_dt_str:
        measured = "time_missing"
        verdict = "non_conforme"
    else:
        try:
            artifact_ts_str = artifact["timestamp"]
            artifact_dt = datetime.fromisoformat(artifact_ts_str.replace("Z", "+00:00"))
            if "T" in time_dt_str:
                time_dt = datetime.fromisoformat(time_dt_str.replace("Z", "+00:00"))
            else:
                time_dt = datetime.fromisoformat(time_dt_str)
            diff_months = (artifact_dt.year - time_dt.year) * 12 + (artifact_dt.month - time_dt.month)
            diff_months = abs(diff_months)
            if diff_months <= 12:
                measured = f"date_fraiche_{diff_months}mois"
                verdict = "conforme"
            else:
                measured = f"date_obsolete_{diff_months}mois"
                verdict = "non_conforme"
        except Exception:
            measured = "datetime_invalide"
            verdict = "non_conforme"
    inherited = _get_inherited_status("A-09", knowledge)
    return _mk_verdict("A-09", "perplexity", "princeton", inherited, measured, verdict)


def _a10(data, artifact, knowledge):
    from pathlib import Path
    item = artifact.get("content_item") or {}
    item_brand = item.get("brand_ref")
    if not item_brand:
        measured = "pas_de_brand_ref_item"
        verdict = "non_conforme"
    else:
        contract_path = Path(__file__).resolve().parents[3] / "contracts" / "brand-contract.v1.yaml"
        try:
            expected_brand = hashlib.sha256(contract_path.read_bytes()).hexdigest()
        except FileNotFoundError:
            measured = "contrat_brand_absent"
            verdict = "non_conforme"
        else:
            if item_brand == expected_brand:
                measured = "brand_ref_coherent"
                verdict = "conforme"
            else:
                measured = "brand_ref_divergent"
                verdict = "non_conforme"
    inherited = _get_inherited_status("A-10", knowledge)
    return _mk_verdict("A-10", "assistants_ia", "princeton", inherited, measured, verdict)



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_site_artifact(html_path, sk_path, timestamp):
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    # Detect malformed HTML via strict parser
    parser = _ArtifactParser(strict=True)
    parser.feed(html)  # may raise ValueError("parse_error:...")
    parser.close_and_check()
    # Extract jsonld artifacts
    jsonld_artifacts = []
    for script_info in parser.jsonld_scripts:
        parsed = script_info["parsed"]
        jsonld_artifacts.append(parsed if parsed is not None else script_info["raw"])
    _, sk_sha = load_seo_knowledge(sk_path)
    return {
        "html": html,
        "jsonld": jsonld_artifacts,
        "timestamp": timestamp,
        "seo_knowledge_sha256": sk_sha,
        "surface": "google_aio",
    }


def build_item_artifact(item, sk_path, timestamp):
    title = item.get("title", "")
    body = item.get("body", "")
    html = f"<html><head><title>{title}</title></head><body><h1>{title}</h1><p>{body}</p></body></html>"
    _, sk_sha = load_seo_knowledge(sk_path)
    return {
        "html": html,
        "jsonld": [],
        "timestamp": timestamp,
        "seo_knowledge_sha256": sk_sha,
        "content_item": item,
    }


def evaluate(artifact):
    knowledge, _ = load_seo_knowledge(SEO_KNOWLEDGE_PATH)
    html = artifact["html"]

    # Parse HTML (non-strict – we don’t fail, the caller tests well-formedness elsewhere)
    data = _parse_html(html, strict=False)

    # Each surface → list of rule functions
    rules = {
        "google_aio": [_a01, _a02, _a03, _a04, _a05],
        "perplexity": [_a06, _a07, _a08, _a09],
        "assistants_ia": [_a10],
    }

    surface_reports = {}
    for surface, rule_funcs in rules.items():
        verdicts = []
        for func in rule_funcs:
            verdicts.append(func(data, artifact, knowledge))
        verdicts.sort(key=lambda v: v["rule_id"])
        surface_reports[surface] = verdicts

    return {
        "surface_reports": surface_reports,
        "seo_knowledge_sha256": artifact.get("seo_knowledge_sha256", ""),
        "timestamp": artifact["timestamp"],
    }
