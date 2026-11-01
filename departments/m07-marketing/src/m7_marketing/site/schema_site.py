"""Schéma de contenu d'un site web, versionné et indépendant du moteur de rendu (décision d'architecte r6, tranche 1).

Un site est DÉCRIT, jamais codé : pages, sections typées, services, zones desservies, témoignages, FAQ, coordonnées
NAP (nom, adresse, téléphone), appels à l'action, langues (fr-CA par défaut, en-CA en option), mentions légales et
confidentialité (Loi 25). Le premier moteur de rendu est en Python pur (`rendu_statique.py`) ; Astro sera un second
adaptateur du MÊME schéma (docs/sites-web.md). Le schéma ne contient donc aucun HTML, aucune classe CSS, aucun nom de
composant : seulement du contenu et ses liens.

Ce module valide la STRUCTURE (types, champs requis, références, traductions, NAP, couleurs et contraste de la
charte). Le CONTENU (promesses chiffrées, textes légaux, données personnelles, témoignages, copie d'un concurrent) est
contrôlé par `garde_contenu.py`. Chaque refus est typé : `{code, chemin, detail}`, jamais un booléen nu.

Le contrat publié pour les autres adaptateurs est `contracts/site-contenu.v1.schema.json` (JSON Schema) ; un test
vérifie que ses énumérés suivent les constantes ci-dessous. Ce module fait foi en cas d'écart.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from ..aeo.aeo_engine import TYPES_LOCALBUSINESS
from . import guardrail

SCHEMA_VERSION = "opsys.site/v1"

# Langues de la tranche 1 : le français du Québec d'abord (Charte de la langue française), l'anglais en option.
LANGUE_DEFAUT = "fr-CA"
LANGUES_PERMISES = ("fr-CA", "en-CA")

TYPES_SECTION = (
    "hero",
    "texte",
    "services",
    "service_detail",
    "zones",
    "temoignages",
    "faq",
    "coordonnees",
    "cta",
    "mentions_legales",
    "confidentialite",
)
# Sections dont le texte est légal par nature : une source juridique déclarée est exigée (garde_contenu).
TYPES_SECTION_LEGALE = ("mentions_legales", "confidentialite")

NATURES_SOURCE = ("juridique", "contrat", "registre_officiel", "mesure", "fournisseur", "profil_marque")
JOURS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
CIBLES_CTA = ("page", "telephone", "courriel")
FORMATS_IMAGE = ("svg", "png")

# Paires de la charte et ratio minimal WCAG 2.2 AA : 4,5:1 pour le texte (1.4.3), 3:1 pour l'indicateur de focus
# (1.4.11, contraste des composants). Les paires du gabarit sont en plus tenues à AAA par G-16 (guardrail.py).
PAIRES_CONTRASTE = (
    ("texte", "fond", 4.5, "texte courant sur le fond"),
    ("primaire", "fond", 4.5, "liens sur le fond"),
    ("texte_sur_primaire", "primaire", 4.5, "en-tête, pied de page et boutons"),
    ("focus", "fond", 3.0, "indicateur de focus sur le fond"),
    ("focus", "primaire", 3.0, "indicateur de focus sur l'en-tête et les boutons"),
)
COULEURS_CHARTE = ("fond", "texte", "primaire", "texte_sur_primaire", "focus")

# Codes de refus de la structure (les codes du contenu sont dans garde_contenu.py).
REJ_SCHEMA_VERSION = "REJ-SITE-SCHEMA-VERSION"
REJ_SCHEMA_CHAMP = "REJ-SITE-SCHEMA-CHAMP"
REJ_SCHEMA_CHAMP_INCONNU = "REJ-SITE-SCHEMA-CHAMP-INCONNU"
REJ_SCHEMA_LANGUE = "REJ-SITE-SCHEMA-LANGUE"
REJ_SCHEMA_TRADUCTION = "REJ-SITE-SCHEMA-TRADUCTION"
REJ_SCHEMA_SECTION = "REJ-SITE-SCHEMA-SECTION"
REJ_SCHEMA_REFERENCE = "REJ-SITE-SCHEMA-REFERENCE"
REJ_SCHEMA_IDENTIFIANT = "REJ-SITE-SCHEMA-IDENTIFIANT"
REJ_SCHEMA_SLUG = "REJ-SITE-SCHEMA-SLUG"
REJ_SCHEMA_NAP = "REJ-SITE-SCHEMA-NAP"
REJ_SCHEMA_COULEUR = "REJ-SITE-SCHEMA-COULEUR"
REJ_CONTRASTE = "REJ-SITE-CONTRASTE-INSUFFISANT"
REJ_SCHEMA_IMAGE = "REJ-SITE-SCHEMA-IMAGE"
REJ_SCHEMA_PAGES = "REJ-SITE-SCHEMA-PAGES"
REJ_FICTIF_DOMAINE = "REJ-SITE-FICTIF-DOMAINE-REEL"
REJ_FRANCAIS = "REJ-SITE-FRANCAIS-NON-PREDOMINANT"

CHAMPS_RACINE = (
    "schema", "site_id", "fictif", "domaine", "langues", "revision", "entreprise", "charte", "sources", "zones",
    "services", "temoignages", "faq", "cta", "pages", "images", "legal",
)

_IDENTIFIANT = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
_SEGMENT = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_SLUG = re.compile(rf"^(?:{_SEGMENT}(?:/{_SEGMENT})*)?$")
_DOMAINE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_TELEPHONE = re.compile(r"^\+1 \d{3} \d{3} \d{4}$")
_CODE_POSTAL = re.compile(r"^[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z] \d[ABCEGHJ-NPRSTV-Z]\d$")
_COURRIEL = re.compile(r"^[a-z0-9._-]{1,64}@([a-z0-9.-]{1,253})$")
_HEURE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_FICHIER_IMAGE = re.compile(rf"^images/[a-z0-9]+(?:-[a-z0-9]+)*\.(?:{'|'.join(FORMATS_IMAGE)})$")
_INITIALES = re.compile(r"^(?:[A-ZÀ-Ý]\.(?:-[A-ZÀ-Ý]\.)?)(?: [A-ZÀ-Ý]\.){0,2}$")
_DOMAINES_RESERVES = (".example", ".test", ".invalid", ".localhost")
# Bornes de longueur : celles du garde-fou de page (G-02 titre 10..70 une fois suffixé du nom, G-05 description).
DESCRIPTION_MIN, DESCRIPTION_MAX = 50, 300
TITRE_MAX = 60
TEXTE_MAX = 2000
# « Français nettement prédominant » : la version anglaise ne dit pas plus que la française (en caractères).
RATIO_ANGLAIS_MAX = 1.15


def refus(code: str, chemin: str, detail: str) -> dict[str, str]:
    """Un refus typé : le code stable, l'endroit du schéma, et quoi corriger."""
    return {"code": code, "chemin": chemin, "detail": detail}


def prefixe_langue(langue: str, langues: Sequence[str]) -> str:
    """Préfixe d'URL d'une langue : vide pour la langue par défaut (fr-CA, à la racine), `/en` pour en-CA."""
    return "" if langue == langues[0] else "/" + langue.split("-")[0]


def chemin_page(slug: str, langue: str, langues: Sequence[str]) -> str:
    """URL propre (chemin) d'une page : `/`, `/services/`, `/en/services/`."""
    prefixe = prefixe_langue(langue, langues)
    return f"{prefixe}/{slug}/" if slug else f"{prefixe}/"


def contrastes_charte(charte: Mapping[str, str]) -> list[dict[str, Any]]:
    """Chaque paire de la charte, son ratio WCAG calculé et son seuil AA. Lève ValueError si une couleur manque
    ou n'est pas hexadécimale (le schéma le refuse avant)."""
    resultat = []
    for avant, arriere, seuil, usage in PAIRES_CONTRASTE:
        ratio = guardrail.contrast_ratio(charte[avant], charte[arriere])
        resultat.append({
            "paire": f"{avant}/{arriere}",
            "usage": usage,
            "ratio": round(ratio, 2),
            "seuil_aa": seuil,
            "conforme_aa": ratio >= seuil,
            "conforme_aaa": ratio >= (7.0 if seuil == 4.5 else 4.5),
        })
    return resultat


class _Collecteur:
    def __init__(self, langues: Sequence[str]) -> None:
        self.refus: list[dict[str, str]] = []
        self.langues = tuple(langues)

    def ajouter(self, code: str, chemin: str, detail: str) -> None:
        self.refus.append(refus(code, chemin, detail))

    def objet(self, valeur: Any, chemin: str, requis: Sequence[str], optionnels: Sequence[str] = ()) -> bool:
        if not isinstance(valeur, Mapping):
            self.ajouter(REJ_SCHEMA_CHAMP, chemin, "objet attendu")
            return False
        for cle in requis:
            if cle not in valeur:
                self.ajouter(REJ_SCHEMA_CHAMP, f"{chemin}.{cle}", "champ requis absent")
        for cle in sorted(set(valeur) - set(requis) - set(optionnels)):
            self.ajouter(REJ_SCHEMA_CHAMP_INCONNU, f"{chemin}.{cle}", f"champ inconnu du schéma {SCHEMA_VERSION}")
        return True

    def chaine(self, valeur: Any, chemin: str, *, maximum: int = TEXTE_MAX) -> bool:
        if not isinstance(valeur, str) or not valeur.strip():
            self.ajouter(REJ_SCHEMA_CHAMP, chemin, "texte non vide attendu")
            return False
        if len(valeur) > maximum or re.search(r"[\x00-\x08\x0b-\x1f\x7f]", valeur):
            self.ajouter(REJ_SCHEMA_CHAMP, chemin, f"texte de {maximum} caractères au plus, sans caractère de contrôle")
            return False
        return True

    def liste(self, valeur: Any, chemin: str, *, vide_permise: bool = True) -> list[Any]:
        if not isinstance(valeur, list) or (not vide_permise and not valeur):
            self.ajouter(REJ_SCHEMA_CHAMP, chemin, "liste" + ("" if vide_permise else " non vide") + " attendue")
            return []
        return valeur

    def localise(self, valeur: Any, chemin: str, *, maximum: int = TEXTE_MAX, paragraphes: bool = False) -> None:
        """Un texte par langue du site, exactement : fr-CA toujours, en-CA si le site le déclare."""
        if not isinstance(valeur, Mapping):
            self.ajouter(REJ_SCHEMA_CHAMP, chemin, "objet {langue: texte} attendu")
            return
        for langue in self.langues:
            if langue not in valeur:
                self.ajouter(REJ_SCHEMA_TRADUCTION, f"{chemin}.{langue}", f"traduction {langue} absente")
        for langue in sorted(set(valeur) - set(self.langues)):
            self.ajouter(REJ_SCHEMA_LANGUE, f"{chemin}.{langue}", "langue non déclarée par le site")
        for langue in self.langues:
            if langue not in valeur:
                continue
            if paragraphes:
                for i, para in enumerate(self.liste(valeur[langue], f"{chemin}.{langue}", vide_permise=False)):
                    self.chaine(para, f"{chemin}.{langue}[{i}]", maximum=maximum)
            else:
                self.chaine(valeur[langue], f"{chemin}.{langue}", maximum=maximum)

    def identifiants(self, elements: Sequence[Any], chemin: str) -> set[str]:
        vus: set[str] = set()
        for i, element in enumerate(elements):
            ident = element.get("id") if isinstance(element, Mapping) else None
            if not isinstance(ident, str) or not _IDENTIFIANT.fullmatch(ident):
                self.ajouter(REJ_SCHEMA_IDENTIFIANT, f"{chemin}[{i}].id", "identifiant [a-z][a-z0-9-]* attendu")
            elif ident in vus:
                self.ajouter(REJ_SCHEMA_IDENTIFIANT, f"{chemin}[{i}].id", f"identifiant en double : {ident}")
            else:
                vus.add(ident)
        return vus

    def reference(self, valeur: Any, connus: set[str], chemin: str, nature: str) -> None:
        if valeur not in connus:
            self.ajouter(REJ_SCHEMA_REFERENCE, chemin, f"{nature} inconnu(e) : {valeur!r}")


def _date_iso(valeur: Any) -> bool:
    if not isinstance(valeur, str):
        return False
    try:
        return dt.date.fromisoformat(valeur).isoformat() == valeur
    except ValueError:
        return False


def _textes_par_langue(schema: Mapping[str, Any], langue: str) -> Iterator[str]:
    """Tous les textes localisés du schéma pour `langue` (mesure de prédominance du français)."""
    def parcourir(noeud: Any) -> Iterator[str]:
        if isinstance(noeud, Mapping):
            if langue in noeud and set(noeud) <= set(LANGUES_PERMISES):
                valeur = noeud[langue]
                if isinstance(valeur, str):
                    yield valeur
                elif isinstance(valeur, list):
                    yield from (v for v in valeur if isinstance(v, str))
                return
            for cle in sorted(noeud):
                yield from parcourir(noeud[cle])
        elif isinstance(noeud, list):
            for element in noeud:
                yield from parcourir(element)
    return parcourir(schema)


def valider_schema(schema: Any) -> list[dict[str, str]]:
    """La liste des refus de structure, dans l'ordre du schéma ; vide si la structure est valide."""
    if not isinstance(schema, Mapping):
        return [refus(REJ_SCHEMA_CHAMP, "$", "le schéma de site doit être un objet JSON")]
    if schema.get("schema") != SCHEMA_VERSION:
        recu = schema.get("schema")
        return [refus(REJ_SCHEMA_VERSION, "$.schema", f"version attendue {SCHEMA_VERSION!r}, reçu {recu!r}")]

    langues = schema.get("langues")
    if (
        not isinstance(langues, list) or not langues or langues[0] != LANGUE_DEFAUT
        or len(set(langues)) != len(langues) or any(lg not in LANGUES_PERMISES for lg in langues)
    ):
        return [refus(
            REJ_SCHEMA_LANGUE, "$.langues",
            f"liste de langues parmi {list(LANGUES_PERMISES)}, sans doublon, commençant par {LANGUE_DEFAUT}",
        )]
    c = _Collecteur(langues)
    c.objet(schema, "$", CHAMPS_RACINE)

    if not isinstance(schema.get("site_id"), str) or not _IDENTIFIANT.fullmatch(schema.get("site_id", "")):
        c.ajouter(REJ_SCHEMA_IDENTIFIANT, "$.site_id", "identifiant [a-z][a-z0-9-]* attendu")
    if not isinstance(schema.get("fictif"), bool):
        c.ajouter(REJ_SCHEMA_CHAMP, "$.fictif", "booléen attendu (true pour toute donnée de démonstration)")
    domaine = schema.get("domaine")
    if not isinstance(domaine, str) or not _DOMAINE.fullmatch(domaine):
        c.ajouter(REJ_SCHEMA_CHAMP, "$.domaine", "nom de domaine en minuscules attendu (sans schéma ni chemin)")
        domaine = None
    elif schema.get("fictif") is True and not domaine.endswith(_DOMAINES_RESERVES):
        c.ajouter(
            REJ_FICTIF_DOMAINE, "$.domaine",
            f"un site fictif utilise un domaine réservé ({', '.join(_DOMAINES_RESERVES)}), jamais un domaine réel",
        )
    revision = schema.get("revision")
    if c.objet(revision, "$.revision", ("date",)) and not _date_iso(revision.get("date")):
        c.ajouter(REJ_SCHEMA_CHAMP, "$.revision.date", "date ISO AAAA-MM-JJ attendue (aucune horloge interne)")

    _valider_charte(c, schema.get("charte"))
    sources = c.liste(schema.get("sources"), "$.sources")
    ids_sources = c.identifiants(sources, "$.sources")
    for i, source in enumerate(sources):
        chemin = f"$.sources[{i}]"
        if c.objet(source, chemin, ("id", "nature", "reference", "valide_par", "date")):
            if source.get("nature") not in NATURES_SOURCE:
                c.ajouter(REJ_SCHEMA_CHAMP, f"{chemin}.nature", f"nature parmi {list(NATURES_SOURCE)}")
            c.chaine(source.get("reference"), f"{chemin}.reference", maximum=300)
            c.chaine(source.get("valide_par"), f"{chemin}.valide_par", maximum=120)
            if not _date_iso(source.get("date")):
                c.ajouter(REJ_SCHEMA_CHAMP, f"{chemin}.date", "date ISO AAAA-MM-JJ attendue")

    def source_optionnelle(bloc: Mapping[str, Any], chemin: str) -> None:
        if "source" in bloc:
            c.reference(bloc["source"], ids_sources, f"{chemin}.source", "source")

    _valider_entreprise(c, schema.get("entreprise"), domaine, ids_sources)

    zones = c.liste(schema.get("zones"), "$.zones", vide_permise=False)
    ids_zones = c.identifiants(zones, "$.zones")
    for i, zone in enumerate(zones):
        if c.objet(zone, f"$.zones[{i}]", ("id", "nom")):
            c.chaine(zone.get("nom"), f"$.zones[{i}].nom", maximum=80)

    images = c.liste(schema.get("images"), "$.images")
    ids_images = c.identifiants(images, "$.images")
    fichiers_vus: set[str] = set()
    for i, image in enumerate(images):
        chemin = f"$.images[{i}]"
        if not c.objet(image, chemin, ("id", "fichier", "largeur", "hauteur", "alt")):
            continue
        fichier = image.get("fichier")
        if not isinstance(fichier, str) or not _FICHIER_IMAGE.fullmatch(fichier) or fichier in fichiers_vus:
            c.ajouter(REJ_SCHEMA_IMAGE, f"{chemin}.fichier", "images/<nom>.svg ou .png, unique")
        else:
            fichiers_vus.add(fichier)
        for dim in ("largeur", "hauteur"):
            valeur = image.get(dim)
            if not isinstance(valeur, int) or isinstance(valeur, bool) or not 1 <= valeur <= 4000:
                c.ajouter(REJ_SCHEMA_IMAGE, f"{chemin}.{dim}", "dimension entière en pixels (1 à 4000) obligatoire")
        if "alt" not in image:
            c.ajouter(REJ_SCHEMA_IMAGE, f"{chemin}.alt", "texte de remplacement obligatoire dans chaque langue")
        else:
            c.localise(image.get("alt"), f"{chemin}.alt", maximum=200)

    services = c.liste(schema.get("services"), "$.services", vide_permise=False)
    ids_services = c.identifiants(services, "$.services")
    for i, service in enumerate(services):
        chemin = f"$.services[{i}]"
        if not c.objet(service, chemin, ("id", "nom", "resume", "description"), ("source", "image")):
            continue
        c.localise(service.get("nom"), f"{chemin}.nom", maximum=TITRE_MAX)
        c.localise(service.get("resume"), f"{chemin}.resume", maximum=300)
        c.localise(service.get("description"), f"{chemin}.description", paragraphes=True)
        source_optionnelle(service, chemin)
        if "image" in service:
            c.reference(service["image"], ids_images, f"{chemin}.image", "image")

    temoignages = c.liste(schema.get("temoignages"), "$.temoignages")
    ids_temoignages = c.identifiants(temoignages, "$.temoignages")
    for i, temoignage in enumerate(temoignages):
        chemin = f"$.temoignages[{i}]"
        if not c.objet(temoignage, chemin, ("id", "texte", "initiales", "zone", "consentement"), ("service",)):
            continue
        c.localise(temoignage.get("texte"), f"{chemin}.texte", maximum=600)
        initiales = temoignage.get("initiales")
        if not isinstance(initiales, str) or not _INITIALES.fullmatch(initiales):
            c.ajouter(
                REJ_SCHEMA_CHAMP, f"{chemin}.initiales",
                "initiales seulement (ex. « M. T. ») : jamais un nom complet de client",
            )
        c.reference(temoignage.get("zone"), ids_zones, f"{chemin}.zone", "zone")
        if "service" in temoignage:
            c.reference(temoignage["service"], ids_services, f"{chemin}.service", "service")
        c.objet(temoignage.get("consentement"), f"{chemin}.consentement", ("statut", "preuve", "date"))

    faq = c.liste(schema.get("faq"), "$.faq")
    ids_faq = c.identifiants(faq, "$.faq")
    for i, question in enumerate(faq):
        chemin = f"$.faq[{i}]"
        if c.objet(question, chemin, ("id", "question", "reponse"), ("source",)):
            c.localise(question.get("question"), f"{chemin}.question", maximum=200)
            c.localise(question.get("reponse"), f"{chemin}.reponse", maximum=1000)
            source_optionnelle(question, chemin)

    pages = c.liste(schema.get("pages"), "$.pages", vide_permise=False)
    ids_pages = c.identifiants(pages, "$.pages")

    ctas = c.liste(schema.get("cta"), "$.cta")
    ids_cta = c.identifiants(ctas, "$.cta")
    for i, cta in enumerate(ctas):
        chemin = f"$.cta[{i}]"
        if not c.objet(cta, chemin, ("id", "libelle", "cible")):
            continue
        c.localise(cta.get("libelle"), f"{chemin}.libelle", maximum=60)
        cible = cta.get("cible")
        if not isinstance(cible, Mapping) or len(cible) != 1 or next(iter(cible)) not in CIBLES_CTA:
            c.ajouter(REJ_SCHEMA_CHAMP, f"{chemin}.cible", f"un seul champ parmi {list(CIBLES_CTA)}")
        elif "page" in cible:
            c.reference(cible["page"], ids_pages, f"{chemin}.cible.page", "page")
        elif cible[next(iter(cible))] is not True:
            c.ajouter(REJ_SCHEMA_CHAMP, f"{chemin}.cible", "telephone/courriel : true (la valeur vient de la NAP)")

    refs = {
        "service": ids_services, "zone": ids_zones, "temoignage": ids_temoignages, "question": ids_faq,
        "cta": ids_cta, "image": ids_images, "source": ids_sources,
    }
    _valider_pages(c, pages, refs)
    _valider_legal(c, schema.get("legal"))

    if not c.refus and len(langues) > 1:
        francais = sum(len(t) for t in _textes_par_langue(schema, LANGUE_DEFAUT))
        for langue in langues[1:]:
            autre = sum(len(t) for t in _textes_par_langue(schema, langue))
            if autre > francais * RATIO_ANGLAIS_MAX:
                c.ajouter(
                    REJ_FRANCAIS, "$.langues",
                    f"la version {langue} ({autre} caractères) dépasse la version française ({francais}) : "
                    "le français reste au moins équivalent (Charte de la langue française)",
                )
    return c.refus


def _valider_charte(c: _Collecteur, charte: Any) -> None:
    if not c.objet(charte, "$.charte", COULEURS_CHARTE):
        return
    invalides = [cle for cle in COULEURS_CHARTE if not guardrail._est_couleur_hex(charte.get(cle))]
    for cle in invalides:
        c.ajouter(REJ_SCHEMA_COULEUR, f"$.charte.{cle}", "couleur hexadécimale #rgb ou #rrggbb attendue")
    if invalides:
        return
    for paire in contrastes_charte(charte):
        if not paire["conforme_aa"]:
            c.ajouter(
                REJ_CONTRASTE, f"$.charte.{paire['paire']}",
                f"{paire['usage']} : {paire['ratio']}:1, {paire['seuil_aa']}:1 au moins (WCAG 2.2 AA)",
            )


def _valider_entreprise(c: _Collecteur, entreprise: Any, domaine: str | None, ids_sources: set[str]) -> None:
    requis = ("nom", "type_schema", "description", "nap", "heures")
    if not c.objet(entreprise, "$.entreprise", requis, ("licence_rbq",)):
        return
    c.chaine(entreprise.get("nom"), "$.entreprise.nom", maximum=80)
    if entreprise.get("type_schema") not in TYPES_LOCALBUSINESS:
        c.ajouter(REJ_SCHEMA_CHAMP, "$.entreprise.type_schema", f"type schema.org parmi {sorted(TYPES_LOCALBUSINESS)}")
    c.localise(entreprise.get("description"), "$.entreprise.description", maximum=DESCRIPTION_MAX)
    nap = entreprise.get("nap")
    if c.objet(nap, "$.entreprise.nap", ("telephone", "courriel", "adresse")):
        if "telephone" in nap and (not isinstance(nap["telephone"], str) or not _TELEPHONE.fullmatch(nap["telephone"])):
            c.ajouter(REJ_SCHEMA_NAP, "$.entreprise.nap.telephone", "format « +1 450 555 0142 » attendu")
        courriel = nap.get("courriel", "")
        trouve = _COURRIEL.fullmatch(courriel) if isinstance(courriel, str) else None
        if trouve is None and "courriel" in nap:
            c.ajouter(REJ_SCHEMA_NAP, "$.entreprise.nap.courriel", "courriel en minuscules attendu")
        elif domaine is not None and trouve.group(1) != domaine:
            c.ajouter(
                REJ_SCHEMA_NAP, "$.entreprise.nap.courriel", f"le courriel public est du domaine du site ({domaine})",
            )
        adresse = nap.get("adresse")
        if c.objet(adresse, "$.entreprise.nap.adresse", ("rue", "ville", "region", "code_postal", "pays")):
            for cle in ("rue", "ville"):
                c.chaine(adresse.get(cle), f"$.entreprise.nap.adresse.{cle}", maximum=120)
            if adresse.get("region") != "QC" or adresse.get("pays") != "CA":
                c.ajouter(REJ_SCHEMA_NAP, "$.entreprise.nap.adresse", "région QC et pays CA (tranche 1 : Québec)")
            if not isinstance(adresse.get("code_postal"), str) or not _CODE_POSTAL.fullmatch(adresse["code_postal"]):
                c.ajouter(REJ_SCHEMA_NAP, "$.entreprise.nap.adresse.code_postal", "code postal canadien « H7N 1A1 »")
    for i, plage in enumerate(c.liste(entreprise.get("heures"), "$.entreprise.heures")):
        chemin = f"$.entreprise.heures[{i}]"
        if not c.objet(plage, chemin, ("jours", "ouverture", "fermeture")):
            continue
        jours = plage.get("jours")
        if not isinstance(jours, list) or not jours or any(j not in JOURS for j in jours):
            c.ajouter(REJ_SCHEMA_CHAMP, f"{chemin}.jours", f"jours parmi {list(JOURS)}")
        ouverture, fermeture = plage.get("ouverture"), plage.get("fermeture")
        heures_valides = all(isinstance(h, str) and _HEURE.fullmatch(h) for h in (ouverture, fermeture))
        if not heures_valides or ouverture >= fermeture:
            c.ajouter(REJ_SCHEMA_CHAMP, chemin, "heures HH:MM, ouverture avant fermeture")
    if "licence_rbq" in entreprise:
        licence = entreprise["licence_rbq"]
        if c.objet(licence, "$.entreprise.licence_rbq", ("numero", "source")):
            if not isinstance(licence.get("numero"), str) or not re.fullmatch(r"\d{4}-\d{4}-\d{2}", licence["numero"]):
                c.ajouter(REJ_SCHEMA_NAP, "$.entreprise.licence_rbq.numero", "numéro RBQ « 0000-0000-00 »")
            c.reference(licence.get("source"), ids_sources, "$.entreprise.licence_rbq.source", "source")


def _valider_pages(c: _Collecteur, pages: Sequence[Any], refs: Mapping[str, set[str]]) -> None:
    chemins_vus: dict[str, str] = {}
    accueil = False
    types_vus: set[str] = set()
    services_detailles: set[str] = set()
    for i, page in enumerate(pages):
        chemin = f"$.pages[{i}]"
        if not c.objet(page, chemin, ("id", "slug", "titre", "description", "sections"), ("titre_nav", "navigation")):
            continue
        c.localise(page.get("titre"), f"{chemin}.titre", maximum=TITRE_MAX)
        if "titre_nav" in page:
            c.localise(page["titre_nav"], f"{chemin}.titre_nav", maximum=40)
        if "navigation" in page and not isinstance(page["navigation"], bool):
            c.ajouter(REJ_SCHEMA_CHAMP, f"{chemin}.navigation", "booléen attendu")
        description = page.get("description")
        c.localise(description, f"{chemin}.description", maximum=DESCRIPTION_MAX)
        if isinstance(description, Mapping):
            for langue, texte in sorted(description.items()):
                if isinstance(texte, str) and len(texte.strip()) < DESCRIPTION_MIN:
                    c.ajouter(
                        REJ_SCHEMA_CHAMP, f"{chemin}.description.{langue}", f"{DESCRIPTION_MIN} caractères au moins",
                    )
        slug = page.get("slug")
        if not isinstance(slug, Mapping) or set(slug) != set(c.langues):
            c.ajouter(REJ_SCHEMA_SLUG, f"{chemin}.slug", "un slug par langue du site")
        else:
            valeurs = {slug[lg] for lg in c.langues}
            if valeurs == {""}:
                accueil = True
            elif "" in valeurs:
                c.ajouter(REJ_SCHEMA_SLUG, f"{chemin}.slug", "la page d'accueil a un slug vide dans toutes les langues")
            for langue in c.langues:
                valeur = slug[langue]
                if not isinstance(valeur, str) or not _SLUG.fullmatch(valeur) or valeur in ("en", "images", "404.html"):
                    c.ajouter(REJ_SCHEMA_SLUG, f"{chemin}.slug.{langue}", "slug [a-z0-9-] (segments séparés par /)")
                    continue
                url = chemin_page(valeur, langue, c.langues)
                if url in chemins_vus:
                    c.ajouter(
                        REJ_SCHEMA_SLUG, f"{chemin}.slug.{langue}", f"URL {url} déjà prise par {chemins_vus[url]}",
                    )
                chemins_vus[url] = str(page.get("id"))
        for j, section in enumerate(c.liste(page.get("sections"), f"{chemin}.sections", vide_permise=False)):
            types_vus.add(_valider_section(c, section, f"{chemin}.sections[{j}]", refs, services_detailles))
    if not accueil:
        c.ajouter(REJ_SCHEMA_PAGES, "$.pages", "une page d'accueil (slug vide) est obligatoire")
    for requis in TYPES_SECTION_LEGALE:
        if requis not in types_vus:
            c.ajouter(REJ_SCHEMA_PAGES, "$.pages", f"une section {requis} est obligatoire (mentions légales et Loi 25)")


_CHAMPS_SECTION: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "hero": (("texte",), ("cta", "image")),
    "texte": (("titre", "paragraphes"), ("source",)),
    "services": (("titre",), ("services",)),
    "service_detail": (("service",), ()),
    "zones": (("titre",), ("texte",)),
    "temoignages": (("titre",), ("temoignages",)),
    "faq": (("titre",), ("questions",)),
    "coordonnees": (("titre",), ("cta",)),
    "cta": (("cta",), ("texte",)),
    "mentions_legales": (("titre", "paragraphes", "source"), ()),
    "confidentialite": (("titre", "paragraphes", "source"), ()),
}
_LISTES_SECTION = {"services": "service", "temoignages": "temoignage", "questions": "question"}


def _valider_section(
    c: _Collecteur, section: Any, chemin: str, refs: Mapping[str, set[str]], services_detailles: set[str]
) -> str:
    type_section = section.get("type") if isinstance(section, Mapping) else None
    if type_section not in _CHAMPS_SECTION:
        c.ajouter(REJ_SCHEMA_SECTION, f"{chemin}.type", f"type de section parmi {list(TYPES_SECTION)}")
        return ""
    requis, optionnels = _CHAMPS_SECTION[type_section]
    c.objet(section, chemin, ("type", *requis), (*optionnels, "ancre"))
    if "ancre" in section and (not isinstance(section["ancre"], str) or not _IDENTIFIANT.fullmatch(section["ancre"])):
        c.ajouter(REJ_SCHEMA_IDENTIFIANT, f"{chemin}.ancre", "ancre [a-z][a-z0-9-]* attendue")
    for cle in ("titre", "texte"):
        if cle in section and cle in (*requis, *optionnels):
            c.localise(section[cle], f"{chemin}.{cle}", maximum=TITRE_MAX if cle == "titre" else 600)
    if "paragraphes" in section:
        c.localise(section["paragraphes"], f"{chemin}.paragraphes", paragraphes=True)
    for cle, nature in (("source", "source"), ("cta", "cta"), ("image", "image"), ("service", "service")):
        if cle in section and cle in (*requis, *optionnels):
            valeurs = section[cle] if isinstance(section[cle], list) and cle == "cta" else [section[cle]]
            for valeur in valeurs:
                c.reference(valeur, refs[nature], f"{chemin}.{cle}", nature)
    if type_section == "service_detail":
        if section.get("service") in services_detailles:
            c.ajouter(REJ_SCHEMA_SECTION, f"{chemin}.service", "un service n'a qu'une page de détail")
        services_detailles.add(section.get("service"))
    for cle, nature in _LISTES_SECTION.items():
        if cle in section and cle in optionnels:
            for k, valeur in enumerate(c.liste(section[cle], f"{chemin}.{cle}", vide_permise=False)):
                c.reference(valeur, refs[nature], f"{chemin}.{cle}[{k}]", nature)
    return type_section


def _valider_legal(c: _Collecteur, legal: Any) -> None:
    if not c.objet(legal, "$.legal", ("responsable_rp", "traceurs_non_essentiels")):
        return
    responsable = legal.get("responsable_rp")
    if c.objet(responsable, "$.legal.responsable_rp", ("titre", "courriel")):
        c.localise(responsable.get("titre"), "$.legal.responsable_rp.titre", maximum=80)
        if not isinstance(responsable.get("courriel"), str) or not _COURRIEL.fullmatch(responsable["courriel"]):
            c.ajouter(REJ_SCHEMA_NAP, "$.legal.responsable_rp.courriel", "courriel de fonction en minuscules attendu")
    if not isinstance(legal.get("traceurs_non_essentiels"), bool):
        c.ajouter(REJ_SCHEMA_CHAMP, "$.legal.traceurs_non_essentiels", "booléen attendu")
