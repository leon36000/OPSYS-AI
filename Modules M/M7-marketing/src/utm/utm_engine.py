import re
import unicodedata
import urllib.parse
from pathlib import Path

import yaml

__all__ = [
    "generer_lien_utm",
    "valider_lien_utm",
    "construire_campaign",
    "normaliser_slug",
    "utm_pour_content_item",
    "utm_pour_fenetre",
]

_CONTRAT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "contracts"
    / "utm-convention.v1.yaml"
)


def _charger_contrat():
    with open(_CONTRAT_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ----------------------------------------------------------------------
#  Fonctions publiques de base
# ----------------------------------------------------------------------
def normaliser_slug(slug_brut: str) -> str:
    """Normalise un slug pour usage dans une campagne UTM.

    Translittération : NFD, suppression des diacritiques, minuscules,
    tout caractère non alphanumérique → tiret, fusion des tirets multiples,
    suppression des tirets aux extrémités.
    """
    if not isinstance(slug_brut, str):
        raise TypeError("slug_brut doit être une chaîne")
    nfd = unicodedata.normalize("NFD", slug_brut)
    # supprimer les diacritiques
    ascii_str = nfd.encode("ascii", "ignore").decode("ascii")
    lower = ascii_str.lower()
    # remplacer tout non [a-z0-9] par un tiret
    tiret = re.sub(r"[^a-z0-9]", "-", lower)
    # fusionner les tirets multiples
    fusion = re.sub(r"-+", "-", tiret)
    # supprimer les tirets en début/fin
    return fusion.strip("-")


def construire_campaign(origine: str, slug_brut: str, annee: int) -> str:
    """Construit une chaîne ``utm_campaign`` valide : origine-slug-annee."""
    if origine not in {"fenetre", "workflow", "contenu"}:
        raise ValueError(
            f"Origine invalide : {origine}. Attendu fenetre, workflow ou contenu."
        )
    if not isinstance(annee, int) or not (2020 <= annee <= 2099):
        raise ValueError(
            f"Année invalide : {annee}. Doit être entre 2020 et 2099."
        )
    slug = normaliser_slug(slug_brut)
    if not slug:
        raise ValueError("Le slug normalisé est vide après traitement.")
    # Déduplication : si le slug se termine déjà par "-<annee>", on retire le suffixe
    suffix = f"-{annee}"
    if slug.endswith(suffix):
        slug = slug[:-len(suffix)]
        if not slug:
            raise ValueError(
                "Le slug ne peut pas être réduit à l'année seule après déduplication."
            )
    return f"{origine}-{slug}-{annee}"




def generer_lien_utm(
    url_base: str,
    source: str,
    medium: str,
    campaign: str,
    content: str | None = None,
) -> str:
    """Produit un lien UTM canonique à partir d'une URL de base."""
    if not isinstance(url_base, str):
        raise TypeError("url_base doit être une chaîne")
    parsed = urllib.parse.urlsplit(url_base)

    # Récupérer les paramètres de query existants dans l'ordre
    qs_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)

    # Retirer tous les paramètres préfixés par utm_
    filtered_pairs = [(k, v) for k, v in qs_pairs if not k.startswith("utm_")]

    # Construire les nouveaux paramètres UTM dans l'ordre canonique
    utm_pairs = [
        ("utm_source", source),
        ("utm_medium", medium),
        ("utm_campaign", campaign),
    ]
    if content is not None:
        utm_pairs.append(("utm_content", content))

    # Fusionner : originaux d'abord, puis UTM en fin
    all_pairs = filtered_pairs + utm_pairs

    # Encodage strict des valeurs (espaces → %20)
    new_query = urllib.parse.urlencode(
        all_pairs, quote_via=urllib.parse.quote, safe=""
    )

    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
    )


# ----------------------------------------------------------------------
#  Validateur
# ----------------------------------------------------------------------
def valider_lien_utm(url: str) -> list:
    """Valide un lien UTM selon les règles U-01 à U-12.

    Retourne une liste de triplets ``(code, verdict, detail)``.
    """
    if not isinstance(url, str):
        raise TypeError("url doit être une chaîne")

    contrat = _charger_contrat()
    enums_sources = contrat["enums"]["utm_source"]
    enums_mediums = contrat["enums"]["utm_medium"]
    campaign_max_len = contrat["format"]["campaign"]["max_length"]
    content_max_len = contrat["format"]["content"]["max_length"]
    annee_min = contrat["format"]["annee"]["min"]
    annee_max = contrat["format"]["annee"]["max"]
    campaign_regex = contrat["format"]["campaign"]["regex"]
    alphabet_content = contrat["format"]["content"]["alphabet"]
    alphabet_global = contrat["format"]["caracteres_autorises_valeurs"]

    verdicts = []
    parsed = urllib.parse.urlsplit(url)
    qs_dict = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    qs_list = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)

    # ------------------------------------------------------------------
    # U-01 : schéma HTTPS
    # ------------------------------------------------------------
    if parsed.scheme == "https":
        verdicts.append(("U-01", "ok", ""))
    else:
        verdicts.append(("U-01", "fail", f"Schéma non HTTPS : {parsed.scheme}"))

    # ------------------------------------------------------------------
    # U-10 : pas de clé UTM dupliquée
    # ------------------------------------------------------------
    utm_keys_in_order = [k for k, _ in qs_list if k.startswith("utm_")]
    duplicates = {k for k in utm_keys_in_order if utm_keys_in_order.count(k) > 1}
    if duplicates:
        verdicts.append(
            ("U-10", "fail", f"Clés UTM dupliquées : {', '.join(sorted(duplicates))}")
        )
    else:
        verdicts.append(("U-10", "ok", ""))

    # Valeurs extraites (None si absente)
    src = qs_dict.get("utm_source", [None])[0]
    med = qs_dict.get("utm_medium", [None])[0]
    cam = qs_dict.get("utm_campaign", [None])[0]
    cont = qs_dict.get("utm_content", [None])[0]

    # ------------------------------------------------------------------
    # U-02 : source présente et dans l'enum
    # ------------------------------------------------------------
    if src is None:
        verdicts.append(("U-02", "fail", "utm_source absent"))
    elif src in enums_sources:
        verdicts.append(("U-02", "ok", ""))
    else:
        verdicts.append(("U-02", "fail", f"utm_source non autorisé : {src}"))

    # ------------------------------------------------------------------
    # U-03 : medium présent et dans l'enum
    # ------------------------------------------------------------
    if med is None:
        verdicts.append(("U-03", "fail", "utm_medium absent"))
    elif med in enums_mediums:
        verdicts.append(("U-03", "ok", ""))
    else:
        verdicts.append(("U-03", "fail", f"utm_medium non autorisé : {med}"))

    # ------------------------------------------------------------------
    # U-04 : campagne conforme au format
    # ------------------------------------------------------------
    if cam is None:
        verdicts.append(("U-04", "fail", "utm_campaign absent"))
    elif re.match(campaign_regex, cam):
        verdicts.append(("U-04", "ok", ""))
    else:
        verdicts.append(
            ("U-04", "fail", f"utm_campaign ne correspond pas au format : {cam}")
        )

    # ------------------------------------------------------------------
    # U-05 : longueur max de la campagne
    # ------------------------------------------------------------
    if cam is not None and len(cam) > campaign_max_len:
        verdicts.append(
            ("U-05", "fail", f"utm_campaign trop long : {len(cam)} > {campaign_max_len}")
        )
    else:
        verdicts.append(("U-05", "ok", ""))

    # ------------------------------------------------------------------
    # U-06 : encodage % correct
    # ------------------------------------------------------------
    encoding_fail = False
    original_query = parsed.query
    # Détection de séquence % mal formée
    if original_query and re.search(r"%(?![0-9A-Fa-f]{2})", original_query):
        encoding_fail = True
    else:
        # Re-encodage de chaque valeur UTM et comparaison
        for k, v in urllib.parse.parse_qsl(original_query, keep_blank_values=True):
            if k.startswith("utm_"):
                re_encoded = urllib.parse.quote(v, safe="")
                if f"{k}={re_encoded}" not in original_query:
                    encoding_fail = True
                    break
    if encoding_fail:
        verdicts.append(("U-06", "fail", "Encodage % incorrect"))
    else:
        verdicts.append(("U-06", "ok", ""))

    # ------------------------------------------------------------------
    # U-07 : caractères autorisés dans les valeurs
    # ------------------------------------------------------------
    def _value_ok(val, pattern):
        if val is None:
            return True
        return bool(re.match(f"^{pattern}$", val))

    global_bad = False
    for val in (src, med, cam, cont):
        if val is not None and not _value_ok(val, alphabet_global):
            global_bad = True
            break
    if global_bad:
        verdicts.append(("U-07", "fail", "Caractère interdit dans une valeur UTM"))
    else:
        verdicts.append(("U-07", "ok", ""))

    # ------------------------------------------------------------------
    # U-08 : ordre canonique des paramètres UTM
    # ------------------------------------------------------------
    CANONICAL_ORDER = ["utm_source", "utm_medium", "utm_campaign", "utm_content"]
    utm_keys_present = [k for k, _ in qs_list if k in CANONICAL_ORDER]
    expected_order = [k for k in CANONICAL_ORDER if k in utm_keys_present]
    if utm_keys_present == expected_order:
        verdicts.append(("U-08", "ok", ""))
    else:
        verdicts.append(("U-08", "warn", "Ordre des paramètres UTM non canonique"))

    # ------------------------------------------------------------------
    # U-09 : utm_content (optionnel)
    # ------------------------------------------------------------
    if cont is not None:
        if len(cont) > content_max_len:
            verdicts.append(
                ("U-09", "fail", f"utm_content trop long : {len(cont)} > {content_max_len}")
            )
        elif not _value_ok(cont, alphabet_content):
            verdicts.append(("U-09", "fail", "utm_content contient des caractères interdits"))
        else:
            verdicts.append(("U-09", "ok", ""))
    else:
        verdicts.append(("U-09", "ok", ""))

    # ------------------------------------------------------------------
    # U-11 : année dans les bornes
    # ------------------------------------------------------------
    if cam is not None:
        parts = cam.rsplit("-", 1)  # le dernier segment est l'année
        if len(parts) == 2:
            try:
                annee = int(parts[-1])
            except ValueError:
                annee = None
            if annee is None:
                verdicts.append(("U-11", "fail", "Année de campagne non numérique"))
            elif (annee < annee_min or annee > annee_max):
                verdicts.append(
                    ("U-11", "fail",
                     f"Année hors intervalle [{annee_min}, {annee_max}] : {annee}")
                )
            else:
                verdicts.append(("U-11", "ok", ""))
        else:
            verdicts.append(
                ("U-11", "fail", "Format de campagne non reconnu pour extraction année")
            )
    else:
        verdicts.append(
            ("U-11", "fail", "Campagne absente, impossible de vérifier l'année")
        )

    # ------------------------------------------------------------------
    # U-12 : slug non vide après normalisation
    # ------------------------------------------------------------
    if cam is not None:
        # origine-slug-annee => slug = tout sauf le premier et le dernier élément
        segments = cam.split("-")
        if len(segments) >= 3:
            slug = "-".join(segments[1:-1])
            if not slug:
                verdicts.append(("U-12", "fail", "Slug vide"))
            else:
                verdicts.append(("U-12", "ok", ""))
        else:
            verdicts.append(
                ("U-12", "fail", "Format de campagne non reconnu pour slug")
            )
    else:
        verdicts.append(
            ("U-12", "fail", "Campagne absente, impossible de vérifier le slug")
        )

    return verdicts


# ----------------------------------------------------------------------
#  Intégrations S006 / S008
# ----------------------------------------------------------------------
def utm_pour_content_item(item: dict, url_base: str = "https://opsys-ai.ca/") -> str:
    """Génère un lien UTM pour un content‑item (S006)."""
    mapping = {
        ("google_aio", "seo", "page_seo"): ("google", "organique"),
        ("perplexity", "seo", "article_blog"): ("perplexity", "organique"),
        ("assistants_ia", "social", "post_social"): ("site", "referral"),
        ("google_aio", "ppc", "fiche_gbp"): ("gbp", "cpc"),
    }
    surface = item["surface"]
    pillar = item["pillar"]
    content_type = item.get("content_type") or item.get("type")
    timestamp = item.get("timestamp")
    if not timestamp:
        raise ValueError("Timestamp requis pour extraire l'année")
    annee = int(timestamp[:4])
    source, medium = mapping.get((surface, pillar, content_type), (None, None))
    if source is None:
        raise ValueError(
            f"Aucun mapping pour ({surface}, {pillar}, {content_type})"
        )
    title = item.get("title", "")
    campaign = construire_campaign("contenu", title, annee)
    url = item.get("url") or url_base
    return generer_lien_utm(url, source, medium, campaign)


def utm_pour_fenetre(fenetre: dict, timestamp: str, source: str, medium: str,
                     url_base: str = "https://opsys-ai.ca/") -> str:
    """Génère un lien UTM pour une fenêtre marketing (S008)."""
    fenetre_id = fenetre["fenetre_id"]
    annee = int(timestamp[:4])
    campaign = construire_campaign("fenetre", fenetre_id, annee)
    url = fenetre.get("url") or url_base
    return generer_lien_utm(url, source, medium, campaign)
