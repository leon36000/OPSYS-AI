"""Import MANUEL d'un export (CSV ou JSON) vers le registre des signaux, avec la même provenance et la même
fraîcheur que la lecture par API.

Sert deux besoins : les sources SANS API de lecture documentée (rapport « IA générative » de Search Console, rapport
« AI Performance » de Bing — R4 §10 « INCONNU » 1 et 2 —, journaux d'accès du serveur) et le repli quand un accès
n'est pas encore accordé (R4 §7, « export manuel si accès absents »).

Règles :
- le MAPPING des colonnes est FOURNI par l'appelant et validé : rien n'est deviné d'après les en-têtes ; une colonne
absente
  d'une ligne est un refus qui nomme la ligne ;
- dates AAAA-MM-JJ seulement ; nombres en entiers ou en décimaux écrits à la façon des API (« 1234.5 »), jamais « 1
234,5 » ni
  « 3,5 % » (ambigu) ; un flottant JSON est refusé ;
- 2 Mo et 20 000 lignes au plus (`REJ-SIGNAUX-IMPORT-TROP-GROS`, jamais tronqué) ;
- injection de formule de tableur neutralisée dans tout texte conservé (une cellule qui commence par `= + - @`,
tabulation ou
  retour devient `'…`) ; les textes passent par le masqueur de renseignements personnels ;
- TOUT OU RIEN : une ligne invalide refuse l'import entier ; les faits sont idempotents (même fichier = aucun
changement) et
  révisés si une valeur change ;
- l'état d'ingestion du flux `import` est écrit (fraîcheur) et l'événement `m7.signaux_marketing_constates` est
annoncé, mode
  `import_manuel`.

Ce module écrit au registre : il s'appelle depuis un outil N2 ou un exécuteur, jamais sans transaction.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from opsys import evenements, stockage

from . import curseurs, modele, registre
from .erreurs import ErreurSignaux, refus
from .minimisation import chemin_de_page, exiger_masqueur, texte_minimise

OCTETS_MAX = 2 * 1024 * 1024
LIGNES_MAX = 20_000
PRODUCTEUR = "m07-marketing"
TYPE_SIGNAUX = "m7.signaux_marketing_constates"
VERSION_FORMAT = "export-manuel/1"
DELIMITEURS = (",", ";", "\t")
_FORMULE = ("=", "+", "-", "@", "\t", "\r")
# Natures importables à la main, leur type de portée permis et leurs mesures permises (noms de mesures des faits).
NATURES_IMPORTABLES: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "rapport_ia_impressions": (("page", "site"), ("impressions", "clics", "citations", "pages_citees")),
    "visites_robots_ia": (("robot_ia",), ("visites", "lignes_lues", "ip_verifiees", "ok_2xx", "redirections_3xx",
                                          "erreurs_4xx", "erreurs_5xx")),
    "performance_recherche_jour": (("site",), ("clics", "impressions", "ctr", "position")),
    "requetes_periode": (("requete",), ("clics", "impressions", "ctr", "position")),
    "pages_periode": (("page",), ("clics", "impressions", "ctr", "position")),
    "audience_jour": (("site",), ("visites", "visiteurs", "pages_vues", "rebonds")),
    "referents_periode": (("referent",), ("visites",)),
}


def _invalide(detail: str) -> Exception:
    return refus("REJ-SIGNAUX-IMPORT-INVALIDE", detail, 422)


def neutraliser_formule(texte: str) -> str:
    """Une cellule qui serait lue comme une formule par un tableur est préfixée d'une apostrophe."""
    return "'" + texte if texte[:1] in _FORMULE else texte


@dataclasses.dataclass(frozen=True)
class CarteColonnes:
    portee_type: str
    portee_colonne: str | None
    portee_ref_fixe: str | None
    jour: str | None
    debut: str | None
    fin: str | None
    mesures: tuple[tuple[str, str], ...]
    echantillon: str


def valider_mapping(source: str, nature: str, mapping: Any) -> CarteColonnes:
    if source not in modele.SOURCES_IMPORT:
        raise refus("REJ-SIGNAUX-SOURCE-INCONNUE", f"source d'import attendue parmi {list(modele.SOURCES_IMPORT)}", 422)
    if nature not in NATURES_IMPORTABLES or nature not in modele.SOURCES[source].natures:
        raise _invalide(f"nature {nature!r} non importable pour {source} (importables : "
                        f"{sorted(set(NATURES_IMPORTABLES) & set(modele.SOURCES[source].natures))})")
    types_permis, mesures_permises = NATURES_IMPORTABLES[nature]
    if not isinstance(mapping, Mapping) or set(mapping) != {"portee", "periode", "mesures", "echantillon"}:
        raise _invalide("mapping des colonnes obligatoire : {portee, periode, mesures, echantillon} (rien n'est "
                        "deviné)")
    portee, periode, mesures = mapping["portee"], mapping["periode"], mapping["mesures"]
    if (not isinstance(portee, Mapping) or portee.get("type") not in types_permis
            or set(portee) not in ({"type", "colonne"}, {"type", "ref"})):
        raise _invalide(f"portee : {{type parmi {list(types_permis)}, colonne | ref}} attendu")
    colonne = portee.get("colonne")
    ref = portee.get("ref")
    if (colonne is not None and not (isinstance(colonne, str) and 0 < len(colonne) <= 80)) or \
            (ref is not None and not (isinstance(ref, str) and 0 < len(ref) <= 80)):
        raise _invalide("portee.colonne ou portee.ref : texte de 1 à 80 caractères")
    if not isinstance(periode, Mapping) or set(periode) not in ({"jour"}, {"debut", "fin"}) or any(
            not isinstance(v, str) or not 0 < len(v) <= 80 for v in periode.values()):
        raise _invalide("periode : {jour} ou {debut, fin} (noms de colonnes)")
    if (not isinstance(mesures, Mapping) or not 1 <= len(mesures) <= 12 or set(mesures) - set(mesures_permises)
            or any(not isinstance(v, str) or not 0 < len(v) <= 80 for v in mesures.values())):
        raise _invalide(f"mesures : 1 à 12 entrées parmi {list(mesures_permises)} -> nom de colonne")
    if mapping["echantillon"] not in modele.ECHANTILLONS:
        raise _invalide(f"echantillon : un de {list(modele.ECHANTILLONS)} (déclaré par l'appelant, jamais supposé)")
    return CarteColonnes(portee["type"], colonne, ref, periode.get("jour"), periode.get("debut"), periode.get("fin"),
                    tuple(sorted(mesures.items())), mapping["echantillon"])


def _date(valeur: Any, ligne: int, colonne: str):
    try:
        return modele.date_iso(str(valeur).strip(), f"ligne {ligne}, colonne {colonne!r}")
    except ErreurSignaux as exc:
        raise _invalide(exc.detail) from None


def _lignes_csv(texte: str, delimiteur: str) -> list[dict[str, Any]]:
    if delimiteur not in DELIMITEURS:
        raise _invalide(f"délimiteur parmi {list(DELIMITEURS)}")
    try:
        lecteur = csv.DictReader(io.StringIO(texte, newline=""), delimiter=delimiteur, strict=True)
        lignes = []
        for ligne in lecteur:
            if len(lignes) >= LIGNES_MAX:
                raise refus("REJ-SIGNAUX-IMPORT-TROP-GROS", f"plus de {LIGNES_MAX} lignes : découper l'export "
                            "(rien n'est tronqué en silence)", 413)
            if None in ligne or None in ligne.values():
                raise _invalide(f"ligne {len(lignes) + 2} : nombre de colonnes différent de l'en-tête")
            lignes.append(dict(ligne))
        return lignes
    except csv.Error:
        raise _invalide("CSV illisible (guillemets, taille de cellule ou format)") from None


def _nombre(valeur: Any, ligne: int, colonne: str) -> str:
    if isinstance(valeur, (bool, float)):
        raise _invalide(f"ligne {ligne}, colonne {colonne!r} : nombre en texte ou en entier (jamais un flottant JSON)")
    texte = str(valeur).strip() if valeur is not None else ""
    if not modele.decimal_valide(texte):
        raise _invalide(f"ligne {ligne}, colonne {colonne!r} : nombre écrit comme « 1234.5 » attendu (ni espace de "
                        "milliers, ni virgule décimale, ni %)")
    return texte


def importer(*, source: str, compte_ref: str, nature: str, mapping: Any, csv_texte: str | None = None,
             lignes: Sequence[Mapping[str, Any]] | None = None, delimiteur: str = ",", fictif: bool,
             maintenant: Callable[[], datetime], masqueur: Any) -> dict[str, Any]:
    """Importe un export. Exactement un de `csv_texte` ou `lignes`. À appeler hors transaction métier ou dedans (les
    écritures
    sont atomiques). Rend le bilan ; lève `ErreurSignaux` en cas de refus (rien n'est écrit)."""
    masqueur = exiger_masqueur(masqueur)
    if not modele.compte_valide(compte_ref):
        raise _invalide("compte_ref : minuscules, chiffres, point, tiret, souligné ; 2 à 64 caractères")
    if type(fictif) is not bool:
        raise _invalide("fictif : booléen attendu")
    cfg = valider_mapping(source, nature, mapping)
    if (csv_texte is None) == (lignes is None):
        raise _invalide("fournir exactement un de csv_texte ou lignes")
    if csv_texte is not None:
        if not isinstance(csv_texte, str) or len(csv_texte.encode("utf-8")) > OCTETS_MAX:
            raise refus("REJ-SIGNAUX-IMPORT-TROP-GROS", f"export de plus de {OCTETS_MAX} octets : le découper", 413)
        rangees = _lignes_csv(csv_texte, delimiteur)
        empreinte = hashlib.sha256(csv_texte.encode("utf-8")).hexdigest()
        point_acces = "csv"
    else:
        if not isinstance(lignes, Sequence) or isinstance(lignes, (str, bytes)):
            raise _invalide("lignes : liste d'objets attendue")
        if len(lignes) > LIGNES_MAX:
            raise refus("REJ-SIGNAUX-IMPORT-TROP-GROS", f"plus de {LIGNES_MAX} lignes : découper l'export", 413)
        rangees = [dict(r) if isinstance(r, Mapping) else None for r in lignes]
        if any(r is None for r in rangees):
            raise _invalide("chaque ligne est un objet")
        try:
            brut = json.dumps(rangees, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            raise _invalide("lignes non sérialisables en JSON") from None
        if len(brut.encode("utf-8")) > OCTETS_MAX:
            raise refus("REJ-SIGNAUX-IMPORT-TROP-GROS", f"export de plus de {OCTETS_MAX} octets : le découper", 413)
        empreinte, point_acces = hashlib.sha256(brut.encode("utf-8")).hexdigest(), "json"
    if not rangees:
        raise _invalide("aucune ligne à importer")
    instant = maintenant()
    if instant.tzinfo is None:
        raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", "horloge sans fuseau", 500)
    horodatage = instant.astimezone(UTC).isoformat().replace("+00:00", "Z")
    faits, debut_min, fin_max = [], None, None
    colonnes = {c for _, c in cfg.mesures} | {c for c in (cfg.portee_colonne, cfg.jour, cfg.debut, cfg.fin) if c}
    for numero, ligne in enumerate(rangees, start=2):  # la ligne 1 est l'en-tête
        absentes = sorted(c for c in colonnes if c not in ligne)
        if absentes:
            raise _invalide(f"ligne {numero} : colonnes absentes {absentes}")
        if cfg.jour:
            d = f = _date(ligne[cfg.jour], numero, cfg.jour)
        else:
            d, f = _date(ligne[cfg.debut], numero, cfg.debut), _date(ligne[cfg.fin], numero, cfg.fin)
            if d > f:
                raise _invalide(f"ligne {numero} : début après la fin")
        brut_ref = cfg.portee_ref_fixe if cfg.portee_ref_fixe is not None else str(ligne[cfg.portee_colonne]).strip()
        if not brut_ref:
            raise _invalide(f"ligne {numero} : portée vide")
        ref = chemin_de_page(masqueur, brut_ref) if cfg.portee_type == "page" else texte_minimise(masqueur, brut_ref,
            200)
        ref = neutraliser_formule(ref)
        mesures = {nom: _nombre(ligne[col], numero, col) for nom, col in cfg.mesures}
        faits.append(modele.brouillon_fait(
            source=source, compte_ref=compte_ref, nature=nature, portee_type=cfg.portee_type, portee_ref=ref,
            debut=d.isoformat(), fin=f.isoformat(), mesures=mesures, observe_le=horodatage, fictif=fictif,
            echantillon={"nature": cfg.echantillon, "n": None},
            provenance={"fournisseur": "export_manuel", "point_acces": point_acces, "version_api": VERSION_FORMAT,
                        "mode": "import_manuel", "empreinte_reponse": empreinte, "page": 0}))
        debut_min = min(debut_min or d, d)
        fin_max = max(fin_max or f, f)
    cle = curseurs.cle_etat(source, compte_ref, "import")
    with stockage.transaction():
        bilan = registre.enregistrer(stockage.maillons(*registre.REGISTRE), faits, horodatage)
        etat = curseurs.EtatIngestion(
            cle, source, compte_ref, "import", fenetre=f"{debut_min.isoformat()}/{fin_max.isoformat()}", curseur=None,
            termine=True, watermark=fin_max.isoformat(), derniere_lecture_reussie_le=horodatage,
            donnees_jusqu_au=fin_max.isoformat())
        curseurs.ecrire_etat(stockage.maillons(*registre.REGISTRE_CURSEURS), etat, horodatage)
        evenements.publier(TYPE_SIGNAUX, PRODUCTEUR, {
            "source": source, "compte_ref": compte_ref, "flux": "import", "mode": "import_manuel",
            "periode_debut": debut_min.isoformat(), "periode_fin": fin_max.isoformat(),
            "faits_nouveaux": bilan["nouveaux"], "faits_revises": bilan["revisions"],
            "faits_inchanges": bilan["inchanges"], "derniere_lecture_reussie_le": horodatage,
            "donnees_jusqu_au": fin_max.isoformat(), "fraicheur_fenetre_h": modele.SOURCES[source].fraicheur_h,
            "fictif": fictif,
        }, evenement_id=f"m7-signaux-{source}-{compte_ref}-import-{debut_min.isoformat()}/{fin_max.isoformat()}-"
                        f"{empreinte[:16]}-{horodatage}")
    return {"accepte": True, "source": source, "compte_ref": compte_ref, "nature": nature, "lignes_lues": len(rangees),
            "faits_nouveaux": bilan["nouveaux"], "faits_revises": bilan["revisions"],
            "faits_inchanges": bilan["inchanges"], "periode": {"debut": debut_min.isoformat(),
                                                               "fin": fin_max.isoformat()},
            "empreinte_fichier": empreinte, "mode": "import_manuel"}


__all__ = ["LIGNES_MAX", "NATURES_IMPORTABLES", "OCTETS_MAX", "TYPE_SIGNAUX", "importer", "neutraliser_formule",
           "valider_mapping"]
