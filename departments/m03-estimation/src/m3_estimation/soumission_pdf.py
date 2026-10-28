"""Brouillon de soumission client de M3 en PDF (PLAN T2.3-f, DEFINITION-PRODUIT.md §7-M3 M3.13).

Même contenu que ``soumission.generer_brouillon_html`` — les deux partent de
``soumission.contenu_client`` (liste blanche : ni ``cout_*`` ni ``taux_marge``, jamais) — rendu en
PDF avec ReportLab (BSD-3-Clause, Python pur, roue sans bibliothèque système : ni Pango ni Cairo).
Extra ``soumission`` de ``pyproject.toml`` (``reportlab==4.5.1``), import PARESSEUX, version
épinglée vérifiée à l'exécution (``pdf_installe``) : le rendu d'un PDF dépend de la version de la
brique, et c'est elle qui rend « mêmes entrées, mêmes octets » vrai. Choix de la brique et licences :
``docs/research/INGREDIENTS.md``. fpdf2 (LGPL-3.0) a été écartée : ses polices de base n'encodent que
le Latin-1 et refusent « œ » (main-d'œuvre), « — » et « ’ » sans police TrueType à livrer.

Fail-closed :

    * brique absente ou d'une autre version : un verdict qui dit quoi installer (l'extra
      ``soumission``), jamais un HTML renommé en PDF ;
    * champ requis absent, ligne sans les clés client, horodatage sans fuseau, montant qui ne
      tombe pas juste au cent, caractère hors de la police du PDF : un verdict qui dit quoi fournir
      ou quoi corriger. Un caractère que la police ne sait pas dessiner ne devient jamais un
      carré « ■ » silencieux (ReportLab le ferait sans erreur).

Le code calcule, le PDF affiche : aucun prix, total, taxe ni arrondi n'est produit ici. Les montants
sont repris du devis (``Decimal``, ou texte décimal) et seulement MIS EN FORME à la québécoise
(« 1 234,56 $ », espace insécable, virgule décimale) ; un montant qui exigerait un arrondi est refusé,
jamais arrondi. Les taxes (TPS/TVQ) ne sont pas calculées par M3 (M5 en est la source de vérité,
DEFINITION-PRODUIT.md §8) : le document dit « taxes en sus », comme le brouillon HTML.

Le texte du client ou d'un modèle est une DONNÉE. ReportLab interprète un mini-langage de balises dans
ses paragraphes (``<b>``, ``<font>``, et ``<img src=...>`` qui OUVRE UN FICHIER LOCAL) : tout texte
libre passe par ``_paragraphe``, qui l'échappe, et les cellules numériques sont des chaînes que la
table dessine sans les interpréter. Le texte est normalisé en NFC puis vérifié contre Windows-1252
(le jeu de la police standard Helvetica du PDF : accents, « œ », « — », « ’ », « € », guillemets
français).

Déterminisme : mode ``invariant`` de ReportLab (aucune horloge, identifiant du fichier tiré du
contenu) et date de création TIRÉE DE LA DONNÉE (l'``horodatage`` du devis, ISO-8601 avec fuseau),
jamais de l'horloge ; polices standard non incorporées ; aucun aléa. « Mêmes octets » vaut pour une
même version de ReportLab et de zlib (compression des flux) ; le texte extrait, lui, ne dépend
d'aucune des deux.

AUCUN ENVOI : ce module rend des OCTETS, il ne les transmet à personne (SOUL.md : envoyer un devis au
client est une action externe, gatée, N4). La mention BROUILLON est portée par TOUTE page : le devis ne
modélise aucune approbation (statuts brouillon, envoye, accepte), donc rien ne permet de la lever. Module
pur (ADR-0009) : aucun import ``opsys``, aucune horloge interne (``datetime.fromisoformat`` PARSE une date
fournie, il ne LIT jamais l'horloge), aucun accès réseau.
"""

from __future__ import annotations

import io
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html import escape
from importlib import import_module, metadata
from typing import Any

from . import soumission, verdicts

__all__ = [
    "NOM_BRIQUE",
    "TYPE_MIME",
    "VERSION_BRIQUE",
    "formater_montant",
    "formater_quantite",
    "generer_brouillon_pdf",
    "pdf_installe",
]

NOM_BRIQUE = "reportlab"
VERSION_BRIQUE = "4.5.1"  # épinglée : les octets du PDF changent d'une version à l'autre
TYPE_MIME = "application/pdf"

_ESPACE_INSECABLE = "\u00a0"
_CENT = Decimal("0.01")
_SEPARATEURS_FR_CA = str.maketrans({",": _ESPACE_INSECABLE, ".": ","})
# Bornes d'AFFICHAGE (protègent le rendu d'un exposant démesuré, ex. 1E+999999999) : ce ne sont pas
# des valeurs métier. Jusqu'à 10^15 (exclu) devant la virgule, six décimales derrière.
_ADJUSTED_MAX = 14
_DECIMALES_MAX = 6
_ENCODAGE_POLICE = "cp1252"
_BLANCS = "\t\n\r\u000b\u000c"
_MOIS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
_LIBELLES_STATUT = {"brouillon": "brouillon", "envoye": "envoyé", "accepte": "accepté"}
_NOTE_MONTANTS = "Montants en dollars canadiens (CAD). Taxes (TPS/TVQ) en sus."


# -- la brique -------------------------------------------------------------------------------------
def _version_brique() -> tuple[str | None, str]:
    """``(version, "")`` si ReportLab est installé à la version épinglée, sinon ``(None, raison)``."""
    try:
        version = metadata.version(NOM_BRIQUE)
    except metadata.PackageNotFoundError:
        return None, f"{NOM_BRIQUE} absent"
    if version != VERSION_BRIQUE:
        return None, f"{NOM_BRIQUE} {version} trouvé, {VERSION_BRIQUE} exigé"
    return version, ""


def pdf_installe() -> tuple[bool, str]:
    """``(True, version)`` si la brique PDF est utilisable, sinon ``(False, raison)``. Jamais d'exception."""
    version, raison = _version_brique()
    if version is None:
        return False, raison
    try:
        import_module("reportlab.platypus")
    except ImportError:
        return False, f"{NOM_BRIQUE} installé mais non importable"
    return True, version


# -- mise en forme (québécoise) --------------------------------------------------------------------
def _afficherable(valeur: Decimal) -> bool:
    return (
        valeur.is_finite()
        and valeur.adjusted() <= _ADJUSTED_MAX
        and valeur.as_tuple().exponent >= -_DECIMALES_MAX
    )


def formater_montant(valeur: Decimal) -> str:
    """``Decimal('1234.5')`` -> ``'1 234,50 $'`` (espaces insécables). Lève ``ValueError`` si ``valeur``
    n'est pas fini, dépasse les bornes d'affichage ou exigerait un arrondi : un montant est repris tel
    que le code l'a calculé, jamais arrondi en silence."""
    if not isinstance(valeur, Decimal) or not _afficherable(valeur):
        raise ValueError("montant non affichable")
    try:
        au_cent = valeur.quantize(_CENT)
    except InvalidOperation as erreur:
        raise ValueError("montant non affichable") from erreur
    if au_cent != valeur:
        raise ValueError("montant à plus de deux décimales : aucun arrondi n'est fait ici")
    if au_cent.is_zero():
        au_cent = abs(au_cent)
    return format(au_cent, ",.2f").translate(_SEPARATEURS_FR_CA) + _ESPACE_INSECABLE + "$"


def formater_quantite(valeur: Decimal) -> str:
    """``Decimal('12.5')`` -> ``'12,5'`` : les décimales fournies, ni plus ni moins. Lève ``ValueError``
    si ``valeur`` n'est pas fini ou dépasse les bornes d'affichage."""
    if not isinstance(valeur, Decimal) or not _afficherable(valeur):
        raise ValueError("quantité non affichable")
    if valeur.is_zero():
        valeur = abs(valeur)
    return format(valeur, ",f").translate(_SEPARATEURS_FR_CA)


def _decimal_du_devis(valeur: Any, champ: str) -> tuple[Decimal | None, dict | None]:
    """Un montant ou une quantité du devis : ``Decimal`` ou texte décimal, jamais un nombre JSON."""
    if isinstance(valeur, str):
        try:
            valeur = Decimal(valeur)
        except InvalidOperation:
            valeur = None
    if not isinstance(valeur, Decimal) or not _afficherable(valeur):
        return None, verdicts.construire_verdict(
            "REJ-SOUMISSION-PDF-MONTANT-INVALIDE",
            detail=f"{champ} doit être un Decimal ou un texte décimal fini (jamais un nombre JSON)",
        )
    return valeur, None


def _montant(valeur: Any, champ: str) -> tuple[str | None, dict | None]:
    decimal, verdict = _decimal_du_devis(valeur, champ)
    if verdict is not None:
        return None, verdict
    try:
        return formater_montant(decimal), None
    except ValueError:
        return None, verdicts.construire_verdict(
            "REJ-SOUMISSION-PDF-MONTANT-INVALIDE",
            detail=f"{champ} doit tomber juste au cent : le PDF reprend le montant du devis sans l'arrondir",
        )


def _quantite(valeur: Any, champ: str) -> tuple[str | None, dict | None]:
    decimal, verdict = _decimal_du_devis(valeur, champ)
    if verdict is not None:
        return None, verdict
    return formater_quantite(decimal), None


def _date_lisible(instant: datetime) -> str:
    """« 28 septembre 2026, 14 h 00 (UTC-04:00) » : l'heure LOCALE de la donnée, jamais convertie."""
    jour = "1er" if instant.day == 1 else str(instant.day)
    decalage = instant.utcoffset()
    minutes = int(decalage.total_seconds() // 60)
    signe = "-" if minutes < 0 else "+"
    heures, reste = divmod(abs(minutes), 60)
    return (
        f"{jour} {_MOIS[instant.month - 1]} {instant.year}, "
        f"{instant.hour}{_ESPACE_INSECABLE}h{_ESPACE_INSECABLE}{instant.minute:02d} "
        f"(UTC{signe}{heures:02d}:{reste:02d})"
    )


def _date_pdf(instant: datetime) -> str:
    """Date de création au format PDF (``D:AAAAMMJJhhmmss+HH'mm'``), tirée de la donnée."""
    minutes = int(instant.utcoffset().total_seconds() // 60)
    signe = "-" if minutes < 0 else "+"
    heures, reste = divmod(abs(minutes), 60)
    return (
        f"D:{instant.year:04d}{instant.month:02d}{instant.day:02d}"
        f"{instant.hour:02d}{instant.minute:02d}{instant.second:02d}{signe}{heures:02d}'{reste:02d}'"
    )


def _lire_horodatage(valeur: Any) -> tuple[datetime | None, dict | None]:
    """L'horodatage du devis (ISO-8601 AVEC fuseau) : il date le document et fixe la date de création
    du PDF. Sans lui, la date de création serait celle de l'horloge, donc jamais les mêmes octets."""
    attendu = "horodatage du devis en ISO-8601 avec fuseau, ex. 2026-09-28T14:00:00-04:00"
    if not isinstance(valeur, str):
        return None, verdicts.construire_verdict("REJ-SOUMISSION-PDF-HORODATAGE-INVALIDE", detail=attendu)
    try:
        instant = datetime.fromisoformat(valeur)
    except ValueError:
        return None, verdicts.construire_verdict(
            "REJ-SOUMISSION-PDF-HORODATAGE-INVALIDE", detail=f"{attendu} (reçu : {valeur!r})"
        )
    if instant.utcoffset() is None:
        return None, verdicts.construire_verdict(
            "REJ-SOUMISSION-PDF-HORODATAGE-INVALIDE", detail=f"{attendu} (fuseau absent : {valeur!r})"
        )
    return instant, None


# -- texte libre = donnée --------------------------------------------------------------------------
def _dessinable(caractere: str) -> bool:
    """Vrai si la police standard du PDF (Windows-1252) dessine ce caractère : ni contrôle, ni hors jeu."""
    if unicodedata.category(caractere) == "Cc":
        return False
    try:
        caractere.encode(_ENCODAGE_POLICE)
    except UnicodeEncodeError:
        return False
    return True


def _texte(valeur: Any, champ: str, code_invalide: str, *, multiligne: bool = False,
           vide: bool = False) -> tuple[str | None, dict | None]:
    """Texte libre du devis, prêt à dessiner : NFC, blancs ramenés à une espace, contrôlé contre la police
    du PDF. Non textuel, vide ou hors police : un verdict qui nomme le champ (jamais la valeur, sauf les
    points de code fautifs)."""
    if not isinstance(valeur, str) or (not vide and valeur.strip() == ""):
        return None, verdicts.construire_verdict(code_invalide, detail=f"{champ} doit être un texte non vide")
    fautifs: list[str] = []
    morceaux: list[str] = []
    normalise = unicodedata.normalize("NFC", valeur)
    if multiligne:
        normalise = normalise.replace("\r\n", "\n").replace("\r", "\n")
    for caractere in normalise:
        if multiligne and caractere == "\n":
            morceaux.append("\n")
        elif caractere in _BLANCS:
            morceaux.append(" ")
        elif _dessinable(caractere):
            morceaux.append(caractere)
        else:
            point = f"U+{ord(caractere):04X}"
            if point not in fautifs:
                fautifs.append(point)
    if fautifs:
        return None, verdicts.construire_verdict(
            "REJ-SOUMISSION-PDF-CARACTERE-NON-SUPPORTE",
            detail=(
                f"{champ} : caractères que la police du PDF ne dessine pas ({', '.join(fautifs[:8])}) ; "
                "remplacer par des caractères du français (Windows-1252)"
            ),
        )
    return "".join(morceaux), None


def _paragraphe(texte: str, style: Any, *, multiligne: bool = False) -> Any:
    """SEUL passage d'un texte libre vers un paragraphe ReportLab : échappé (``& < >``), donc affiché
    tel quel, jamais interprété comme balise (``<img src=...>`` ouvrirait un fichier local)."""
    from reportlab.platypus import Paragraph

    protege = escape(texte, quote=False)
    if multiligne:
        protege = protege.replace("\n", "<br/>")
    return Paragraph(protege, style)


# -- contenu -> pages ------------------------------------------------------------------------------
def _preparer(devis: dict[str, Any]) -> tuple[dict[str, Any] | None, dict | None]:
    """Le contenu du PDF, entièrement validé et mis en forme (chaînes prêtes à dessiner)."""
    contenu, verdict = soumission.contenu_client(devis)
    if verdict is not None:
        return None, verdict

    devis_id, verdict = _texte(contenu["devis_id"], "devis_id", "REJ-CONTRAT-INVALIDE")
    if verdict is not None:
        return None, verdict
    statut, verdict = _texte(contenu["statut"], "statut", "REJ-CONTRAT-INVALIDE")
    if verdict is not None:
        return None, verdict
    instant, verdict = _lire_horodatage(contenu["horodatage"])
    if verdict is not None:
        return None, verdict
    total, verdict = _montant(contenu["prix_total"], "prix_total")
    if verdict is not None:
        return None, verdict

    lignes: list[dict[str, str]] = []
    for index, ligne in enumerate(contenu["lignes"]):
        etiquette = f"ligne {index}"
        description, verdict = _texte(ligne["description"], f"{etiquette} : description", "REJ-DEVIS-LIGNE-INVALIDE")
        if verdict is not None:
            return None, verdict
        unite, verdict = _texte(ligne["unite"], f"{etiquette} : unite", "REJ-DEVIS-LIGNE-INVALIDE")
        if verdict is not None:
            return None, verdict
        quantite, verdict = _quantite(ligne["quantite"], f"{etiquette} : quantite")
        if verdict is not None:
            return None, verdict
        prix_unitaire, verdict = _montant(ligne["prix_unitaire"], f"{etiquette} : prix_unitaire")
        if verdict is not None:
            return None, verdict
        prix_ligne, verdict = _montant(ligne["prix_ligne"], f"{etiquette} : prix_ligne")
        if verdict is not None:
            return None, verdict
        lignes.append({
            "description": description,
            "quantite": f"{quantite}{_ESPACE_INSECABLE}{unite}",
            "prix_unitaire": prix_unitaire,
            "prix_ligne": prix_ligne,
        })

    resultat = {
        "devis_id": devis_id,
        "statut": _LIBELLES_STATUT.get(statut, statut),
        "date_lisible": _date_lisible(instant),
        "date_pdf": _date_pdf(instant),
        "lignes": lignes,
        "prix_total": total,
    }
    if "modele_soumission" in contenu:
        modele = {}
        for cle, valeur in contenu["modele_soumission"].items():
            texte, verdict = _texte(valeur, f"modèle : {cle}", "REJ-CONTRAT-INVALIDE",
                                   multiligne=cle != "titre", vide=cle == "clauses")
            if verdict is not None:
                return None, verdict
            modele[cle] = texte
        resultat["modele_soumission"] = modele
    return resultat, None


def _rendre(contenu: dict[str, Any]) -> bytes:
    """Dessine le PDF (Lettre, une colonne de lignes qui se répète d'une page à l'autre)."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle

    largeur, hauteur = letter
    marge = 54
    rouge = colors.HexColor("#b00020")
    gris = colors.HexColor("#555555")
    devis_id = contenu["devis_id"]

    titre = ParagraphStyle("titre", fontName="Helvetica-Bold", fontSize=16, leading=20, spaceAfter=6)
    mention = ParagraphStyle("mention", fontName="Helvetica-Bold", fontSize=9.5, leading=12, textColor=rouge)
    normal = ParagraphStyle("normal", fontName="Helvetica", fontSize=9.5, leading=12)
    entete = ParagraphStyle("entete", parent=normal, fontName="Helvetica-Bold")
    entete_droite = ParagraphStyle("entete_droite", parent=entete, alignment=TA_RIGHT)
    petit = ParagraphStyle("petit", parent=normal, fontSize=8.5, leading=11, textColor=gris)

    def decorer(canvas: Any, _doc: Any) -> None:
        canvas.setDateFormatter(lambda *_ignore: contenu["date_pdf"])  # date de la donnée, jamais l'horloge
        canvas.saveState()
        canvas.setFillColor(rouge)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(marge, hauteur - 40, "BROUILLON")
        canvas.setFillColor(gris)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(marge, hauteur - 52, "Non envoyé, sujet à approbation.")
        canvas.drawString(marge, 30, f"Soumission {devis_id} — BROUILLON")
        canvas.drawRightString(largeur - marge, 30, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    largeurs = (222, 88, 91, 91)  # 492 pt : la largeur utile du cadre (612 - 2 x 54 - 2 x 6 de marge interne)
    donnees: list[list[Any]] = [[
        _paragraphe("Description", entete),
        _paragraphe("Quantité", entete),
        _paragraphe("Prix unitaire", entete_droite),
        _paragraphe("Prix", entete_droite),
    ]]
    for ligne in contenu["lignes"]:
        donnees.append([
            _paragraphe(ligne["description"], normal),
            _paragraphe(ligne["quantite"], normal),
            ligne["prix_unitaire"],
            ligne["prix_ligne"],
        ])
    donnees.append(["Prix total", "", "", contenu["prix_total"]])
    dernier = len(donnees) - 1
    table = Table(donnees, colWidths=largeurs, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("GRID", (0, 0), (-1, dernier - 1), 0.5, colors.HexColor("#999999")),
        ("ALIGN", (2, 0), (3, dernier), "RIGHT"),
        ("SPAN", (0, dernier), (2, dernier)),
        ("ALIGN", (0, dernier), (2, dernier), "RIGHT"),
        ("FONTNAME", (0, dernier), (-1, dernier), "Helvetica-Bold"),
        ("LINEABOVE", (0, dernier), (-1, dernier), 1, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    sortie = io.BytesIO()
    document = SimpleDocTemplate(
        sortie,
        pagesize=letter,
        leftMargin=marge,
        rightMargin=marge,
        topMargin=72,
        bottomMargin=54,
        title=f"Soumission brouillon {devis_id}",
        author="OPSYS-AI",
        subject="Soumission brouillon",
        creator="OPSYS-AI M3 Estimation",
        lang="fr-CA",
        invariant=1,
        pageCompression=1,
    )
    elements = [
        _paragraphe(f"Soumission {devis_id}", titre),
        _paragraphe(soumission.MENTION_BROUILLON, mention),
        Spacer(1, 6),
        _paragraphe(f"Statut : {contenu['statut']} — daté du {contenu['date_lisible']}", normal),
        Spacer(1, 10),
    ]
    if "modele_soumission" in contenu:
        modele = contenu["modele_soumission"]
        elements.extend([
            _paragraphe(modele["titre"], entete),
            Spacer(1, 6),
            _paragraphe(modele["description"], normal, multiligne=True),
            Spacer(1, 10),
        ])
    elements.extend([
        table,
        Spacer(1, 8),
        _paragraphe(_NOTE_MONTANTS, petit),
    ])
    if "modele_soumission" in contenu and contenu["modele_soumission"]["clauses"]:
        elements.extend([
            Spacer(1, 10),
            _paragraphe("Clauses", entete),
            _paragraphe(contenu["modele_soumission"]["clauses"], normal, multiligne=True),
        ])
    document.build(
        elements,
        onFirstPage=decorer,
        onLaterPages=decorer,
    )
    return sortie.getvalue()


def _rendre_ou_verdict(contenu: dict[str, Any]) -> tuple[bytes | None, dict | None]:
    """Frontière de la brique tierce : une ligne plus haute qu'une page est un verdict qui dit quoi faire ;
    toute autre exception devient un verdict SANS son message (il peut citer le texte du client)."""
    erreur_de_mise_en_page = import_module("reportlab.platypus.doctemplate").LayoutError
    try:
        return _rendre(contenu), None
    except erreur_de_mise_en_page:
        return None, verdicts.construire_verdict(
            "REJ-SOUMISSION-PDF-RENDU-IMPOSSIBLE",
            detail="une ligne du devis est plus haute qu'une page : raccourcir sa description",
        )
    except Exception:
        return None, verdicts.construire_verdict(
            "REJ-SOUMISSION-PDF-RENDU-IMPOSSIBLE",
            detail=f"le PDF n'a pas pu être dessiné (erreur de la brique {NOM_BRIQUE}) : signaler l'incident",
        )


def generer_brouillon_pdf(devis: dict[str, Any]) -> tuple[bytes | None, dict | None]:
    """Assemble le brouillon PDF depuis un devis (état courant de ``devis_durable``), ou rend un verdict
    nommé : brique absente (quoi installer), champ manquant ou invalide (quoi fournir). Ne calcule ni
    prix ni taxe : reprend TEL QUEL ce que ``devis_durable.creer_devis`` a déjà calculé et arrondi."""
    installe, raison = pdf_installe()
    if not installe:
        return None, verdicts.construire_verdict(
            "REJ-SOUMISSION-PDF-BRIQUE-ABSENTE",
            detail=(
                f"brique PDF indisponible ({raison}) : installer l'extra soumission "
                f"(pip install 'opsys-ai[soumission]', {NOM_BRIQUE}=={VERSION_BRIQUE})"
            ),
        )
    contenu, verdict = _preparer(devis)
    if verdict is not None:
        return None, verdict
    return _rendre_ou_verdict(contenu)
