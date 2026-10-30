"""Interpréteur déterministe des questions « et si… » vers des chocs du catalogue de scénarios (M9.8).

Module pur : aucune horloge, aucun hasard, aucun modèle. Une question française est NORMALISÉE (minuscules, accents
retirés par ``unicodedata``, espaces insécables et apostrophes typographiques ramenés), puis confrontée à des MOTIFS
(expressions régulières) propres à chacun des chocs de ``scenarios.CHOCS``. Chaque correspondance devient une
PROPOSITION ``{choc, parametres, parametres_a_fournir, extrait}`` :

* un paramètre n'est retenu que s'il est DIT dans l'extrait (« 25 % », « 48 000 $ », « deux employés », « 7 jours ») ;
  un paramètre non dit est listé dans ``parametres_a_fournir`` — jamais deviné, jamais une valeur par défaut ;
* chaque paramètre retenu passe la validation du catalogue (``scenarios.valider_parametre``) : hors bornes, la question
  est REFUSÉE avec le refus nommé du catalogue ;
* un pourcentage s'écrit en chiffres (« 25 % », « 25% », « 25 pour cent ») ; « vingt-cinq pour cent » est REFUSÉ
  (``REJ-QUESTION-POURCENTAGE-EN-LETTRES``) ; un nombre signé (« -25 % ») est REFUSÉ : le sens du choc dit la
  direction ;
* le texte de la question est une DONNÉE : aucune instruction qu'il contient n'est suivie ; seule la correspondance de
  motifs produit des propositions ; la question est bornée à ``MAX_QUESTION`` caractères.

Sans correspondance : ``statut`` = ``QUESTION_NON_RECONNUE`` et la liste des chocs disponibles. L'évaluation des
propositions complètes reste celle de ``scenarios.evaluer`` (bases citées par la personne).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import Decimal

from . import scenarios

VERSION = "2026-10-29.1"
MAX_QUESTION = 500
_LIMITES = (
    "Interprétation par motifs fixes : une formulation non prévue n'est pas reconnue, elle n'est jamais devinée.",
    "Le texte de la question est une donnée : aucune instruction qu'il contient n'est suivie.",
    "Une proposition n'est pas un calcul : l'évaluation exige des bases citées (m9_evaluer_scenarios).",
)
_MOTS_NOMBRES = {
    "un": 1,
    "une": 1,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "onze": 11,
    "douze": 12,
    "treize": 13,
    "quatorze": 14,
    "quinze": 15,
    "seize": 16,
    "vingt": 20,
    "trente": 30,
}
_ENTIER = r"\d{1,4}|" + "|".join(sorted(_MOTS_NOMBRES, key=len, reverse=True))
_DECIMAL = r"\d{1,6}(?:[.,]\d{1,6})?"
_POURCENT = r"(?:%|pour ?cent\b)"
_DE = r"\s*(?:(?:de|d'|a|par|pour|d'environ|environ|jusqu'a|d'au moins)\s*)?"
_DE_MONTANT = (
    r"\s*,?\s*(?:(?:de|d'|a|pour|qui coute|qui couterait|coutant|au prix de|d'environ|environ|valant|qui vaut|"
    r"qui represente|representant|qui rapporte|rapportant|totalisant|(?:un |d'un )?montant (?:de |d')?)\s*)?"
)
_ART = (
    r"(?:(?:d'|l'|de |du |des |un |une |le |la |les |notre |nos |nouveau |nouvel |nouvelle |nouveaux |autre |"
    r"deuxieme |second |seconde |gros |grosse |grand |grande |plus |meilleur |meilleure )\s*)*"
)
_HAUSSE = r"(?:augment|mont|hauss|grimp|explos|bondi)\w*"
_BAISSE = r"(?:baiss|diminu|chut|recul|tomb|fond)\w*"
_LEADS = r"(?:leads?|prospects?|demandes?(?: de soumission)?)"
_MARKETING = r"(?:de )?(?:marketing|publicitaire|pub|publicite|google ads|facebook ads)"
_MATERIAUX = r"(?:materiaux|materiel|intrants|fournitures|aluminium|acier|bardeaux?|vinyle|soffites?|fascias?)"
_PERSONNES = (
    r"(?:employes?|personnes?|ouvriers?|travailleurs?|installateurs?|couvreurs?|techniciens?|gars|"
    r"membres? de l'equipe)"
)
_ABSENTS = r"(?:absents?|absentes?|malades?|en conge|blesses?|en arret|manquants?)"
_METEO = (
    r"(?:mauvaise? (?:meteo|temps)|pluie|intemperies?|tempetes?|neige|verglas|orages?|froid extreme|canicule|"
    r"jours? de mauvais temps)"
)
_ACHAT = r"(?:achat|acheter|achete\w*|acquisition|acquerir|acquiert)"
_CLIENT = r"(?:client|contrat)s?(?: (?:important|majeur|principal|commercial|institutionnel))?"


class _Gabarit:
    """Construit un motif en attribuant des noms de groupes uniques ; retient ``groupe → (paramètre, genre)``."""

    def __init__(self) -> None:
        self.groupes: dict[str, tuple[str, str]] = {}

    def _groupe(self, parametre: str, genre: str) -> str:
        nom = f"g{len(self.groupes)}"
        self.groupes[nom] = (parametre, genre)
        return nom

    def pct(self, parametre: str) -> str:
        g = self._groupe(parametre, "pct")
        return rf"(?<![\d.,])(?P<{g}>{_DECIMAL})\s?{_POURCENT}"

    def montant(self, parametre: str) -> str:
        g = self._groupe(parametre, "montant")
        nombre = r"\d{1,3}(?: \d{3})+|\d{1,12}"
        return rf"(?<![\d.,])(?P<{g}>{nombre})(?:[.,](?P<{g}d>\d{{1,2}}))?\s?(?P<{g}k>k)?\s?(?:\$|dollars?)"

    def entier(self, parametre: str) -> str:
        g = self._groupe(parametre, "entier")
        return rf"(?<![\w-])(?P<{g}>{_ENTIER})(?![\w-])"

    def duree(self, parametre: str, unite: str, *, connecteurs: str = "pendant|durant|pour|sur|de") -> str:
        return rf"(?:,?\s+(?:(?:{connecteurs}) )?{self.entier(parametre)} {unite})"


def _motifs_du_choc(choc: str, b: _Gabarit) -> list[str]:
    """Motifs d'un choc (texte normalisé). Chaque appel de ``b`` déclare un groupe de paramètre."""
    if choc == "baisse_leads":
        return [
            rf"(?:baisse|diminution|chute|recul|reduction)s? (?:de |du (?:nombre|volume|flux) de |des )?{_LEADS}"
            rf"(?:{_DE}{b.pct('baisse_pct')})?",
            rf"{_LEADS} (?:\w+ )?{_BAISSE}(?:{_DE}{b.pct('baisse_pct')})?",
            rf"{b.pct('baisse_pct')} (?:de |des )?(?:moins de {_LEADS}|{_LEADS} en moins)",
        ]
    if choc == "hausse_budget_marketing":
        return [
            rf"(?:hausse|augmentation|accroissement) (?:de |du )?budget {_MARKETING}(?:{_DE}{b.pct('hausse_pct')})?",
            rf"{_HAUSSE} (?:le |notre |mon )?budget {_MARKETING}(?:{_DE}{b.pct('hausse_pct')})?",
            rf"budget {_MARKETING} (?:\w+ )?{_HAUSSE}(?:{_DE}{b.pct('hausse_pct')})?",
        ]
    if choc == "hausse_cout_materiaux":
        return [
            rf"(?:hausse|augmentation|flambee) (?:de |du |des )?(?:(?:cout|couts|prix) (?:de |des |du )?)?{_MATERIAUX}"
            rf"(?:{_DE}{b.pct('hausse_pct')})?",
            rf"(?:cout|couts|prix) (?:de |des |du )?{_MATERIAUX} (?:\w+ )?{_HAUSSE}(?:{_DE}{b.pct('hausse_pct')})?",
            rf"{_MATERIAUX} (?:\w+ )?{_HAUSSE}(?:{_DE}{b.pct('hausse_pct')})?",
        ]
    if choc == "absences":
        jours = "jours?|journees?"
        return [
            rf"{b.entier('personnes')} {_PERSONNES} (?:(?:sont|seraient|est|serait|tombent|tombaient) )?{_ABSENTS}"
            rf"{b.duree('jours_absents', jours)}?",
            rf"absences? (?:de )?{b.entier('personnes')} {_PERSONNES}{b.duree('jours_absents', jours)}?",
            rf"absences? (?:d'equipe|d'employes|de personnel|dans l'equipe){b.duree('jours_absents', jours)}?",
            rf"{_PERSONNES} {_ABSENTS}{b.duree('jours_absents', jours)}?",
        ]
    if choc == "meteo":
        return [
            rf"{b.entier('jours_bloques')} (?:jours?|journees?) (?:de |d')?{_METEO}",
            rf"{_METEO}{b.duree('jours_bloques', 'jours?|journees?')}?",
        ]
    if choc == "achat_camion":
        vehicule = r"(?:camion|pick-?up|fourgon|fourgonnette|vehicule)s?"
        return [rf"{_ACHAT} {_ART}{vehicule}(?:{_DE_MONTANT}{b.montant('prix')})?"]
    if choc == "nouvel_employe":
        suite = (
            rf"(?:{_DE_MONTANT}{b.montant('cout_mensuel')} ?(?:par|/|chaque) ?mois"
            rf"|,?\s*(?:et )?(?:pendant|durant|pour|sur) {b.entier('mois')} mois)*"
        )
        poste = r"(?:employe|ouvrier|travailleur|installateur|couvreur|technicien|vendeur|estimateur|personne)s?"
        return [
            rf"(?:embauch|engag|recrut)\w* {_ART}{poste}{suite}",
            rf"(?:nouvel|nouveau) {poste}{suite}",
        ]
    if choc == "perte_gros_client":
        return [
            rf"(?:perte|perdre|perd\w*) {_ART}{_CLIENT}(?:{_DE_MONTANT}{b.montant('revenu_perdu')})?",
            rf"{_ART}{_CLIENT} (?:nous )?(?:quitte|part|s'en va|annule)\w*"
            rf"(?:{_DE_MONTANT}{b.montant('revenu_perdu')})?",
        ]
    if choc == "nouvelle_ville":
        lieu = r"(?:ville|region|territoire|succursale|marche)"
        suite = (
            rf"(?:{_DE_MONTANT}(?:(?:un |avec un )?investissement (?:de |d'environ )?)?{b.montant('investissement')}"
            rf"|,?\s*(?:et |avec |pour )?(?P<{b._groupe('leads_supplementaires', 'entier')}>\d{{1,6}}) "
            rf"(?:leads|prospects)(?: (?:supplementaires|de plus|en plus))?)*"
        )
        return [
            rf"(?:ouv\w*|s'install\w*|s'eten\w*|expansion|lanc\w*) (?:a |dans |vers |en )?{_ART}{lieu}{suite}",
            rf"nouvelle (?:ville|region|succursale){suite}",
        ]
    if choc == "achat_equipement":
        objet = (
            r"(?:equipements?|machines?|plieuses?|echafaudages?|nacelles?|outillage|remorques?|compresseurs?|"
            r"outils?)"
        )
        return [rf"{_ACHAT} {_ART}{objet}(?: \w+)?(?:{_DE_MONTANT}{b.montant('prix')})?"]
    if choc == "achat_batisse":
        suite = (
            rf"(?:{_DE_MONTANT}{b.montant('prix')}"
            rf"|,?\s*(?:et |avec )?(?:une )?mise de fonds (?:de )?{b.pct('mise_de_fonds_pct')}"
            rf"|,?\s*(?:et |avec )?{b.pct('mise_de_fonds_pct')} (?:de mise de fonds|comptant))*"
        )
        return [rf"{_ACHAT} {_ART}(?:batisse|batiment|entrepot|local commercial|immeuble|garage){suite}"]
    if choc == "gain_gros_client":
        return [
            rf"(?:gain|gagn\w*|sign\w*|obten\w*|obtient|decroch\w*|arrivee) {_ART}{_CLIENT}"
            rf"(?:{_DE_MONTANT}{b.montant('revenu_ajoute')})?",
        ]
    if choc == "retard_paiement_client":
        suite = (
            rf"(?:{_DE_MONTANT}{b.montant('montant_retarde')}"
            rf"|,?\s*(?:et |de |avec |pendant |durant |sur )?{b.entier('jours_retard')} jours?(?: de retard)?)*"
        )
        return [
            rf"(?:retard\w*|report\w*) (?:de |du |des |d'un |dans (?:le |les ))?(?:paiements?|encaissements?|"
            rf"versements?|reglements?)(?: (?:d'un|du|des|de) (?:gros )?clients?)?{suite}",
            rf"clients? (?:\w+ )?(?:paie|paye|payait|payerait|reglerait|regle)\w* (?:en retard|avec (?:du )?retard|"
            rf"plus tard){suite}",
        ]
    if choc == "saison_morte_faible":
        suite = (
            rf"(?:,?\s*(?:avec |et )?(?:une )?(?:baisse|diminution|chute) (?:de |du |des )?(?:(?:revenus?|ventes?|"
            rf"chiffre d'affaires) (?:de )?)?{b.pct('baisse_revenu_pct')})?"
        )
        return [
            rf"saison morte (?:(?:est|serait|etait|sera) )?(?:plus )?(?:faible|difficile|longue|lente|tranquille|calme|"
            rf"mauvaise){suite}",
            rf"(?:mauvaise|faible|petite) saison morte{suite}",
            rf"hiver (?:plus )?(?:faible|lent|tranquille|calme|difficile){suite}",
        ]
    if choc == "nouveau_service":
        suite = (
            rf"(?:{_DE_MONTANT}(?:(?:un |avec un )?investissement (?:de |d'environ )?)?"
            rf"{b.montant('investissement')})?"
        )
        offre = r"(?:service|offre|gamme|ligne de service|produit)"
        return [
            rf"(?:lanc|ajout|offr|demarr|developp)\w* {_ART}{offre}(?: (?:de |d')[a-z]+)?{suite}",
            rf"nouve(?:au|lle) {offre}(?: (?:de |d')[a-z]+)?{suite}",
        ]
    if choc == "concurrent_agressif":
        suite = (
            rf"(?:,?\s*(?:et |qui )?(?:nous )?(?:fait perdre|ferait perdre|prend|prendrait|enleve|enleverait|vole|"
            rf"volerait|perte de)\s?(?:de |d')?{b.pct('perte_leads_pct')}(?: (?:de |des |de nos |du )?{_LEADS})?)?"
        )
        return [
            rf"concurrents? (?:tres )?(?:agressifs?|qui casse\w* (?:les|ses) prix|casse\w* les prix){suite}",
            rf"concurrence (?:plus |tres )?(?:agressive|feroce|forte){suite}",
        ]
    if choc == "cashflow_serre":
        suite = (
            rf"(?:,?\s*(?:et )?(?:sur|pendant|durant|pour) (?:les )?{b.entier('horizon_semaines')} "
            rf"(?:prochaines )?semaines?"
            rf"|,?\s*(?:et )?(?:sous|en dessous de|sous le seuil de|seuil de|minimum de|reserve de|plancher de)\s?"
            rf"{b.montant('seuil_minimal')})*"
        )
        return [
            rf"(?:cash-?flow|flux de tresorerie|tresorerie|liquidites|cash)s? (?:(?:est|devient|plus|tres|trop|"
            rf"serait) )*(?:serree?|tendue?|faible|juste|basse?){suite}",
            rf"manque de (?:cash|liquidites|tresorerie){suite}",
        ]
    if choc == "rupture_inventaire":
        return [
            rf"(?:rupture|penurie|manque) (?:de |d'|des |du )?(?:stock|inventaire|{_MATERIAUX})"
            rf"{b.duree('jours_rupture', 'jours?')}?",
            rf"{b.entier('jours_rupture')} jours? (?:de rupture|sans (?:stock|inventaire|{_MATERIAUX}))",
        ]
    if choc == "trop_de_demandes":
        return [
            rf"(?:trop|surplus|afflux|deferlement|avalanche) (?:de |d')\s?(?:{_LEADS}|soumissions?|appels?)"
            rf"(?:,?\s*(?:soit |avec )?(?:une )?(?:hausse|augmentation) (?:de )?{b.pct('hausse_pct')})?",
            rf"(?:hausse|augmentation|bond|explosion) (?:de |des |du (?:nombre|volume) de )?{_LEADS}"
            rf"(?:{_DE}{b.pct('hausse_pct')})?",
            rf"{_LEADS} (?:\w+ )?{_HAUSSE}(?:{_DE}{b.pct('hausse_pct')})?",
            rf"{b.pct('hausse_pct')} (?:de |des )?(?:plus de {_LEADS}|{_LEADS} en plus)",
        ]
    raise ValueError(f"{choc} : aucun motif déclaré")  # garde de construction : chaque choc doit être reconnu


def _compiler() -> list[tuple[int, str, re.Pattern[str], dict[str, tuple[str, str]]]]:
    motifs = []
    for rang, choc in enumerate(scenarios.CHOCS):
        noms = {p.nom for p in scenarios.CHOCS[choc].parametres}
        gabarit = _Gabarit()
        for texte in _motifs_du_choc(choc, gabarit):
            motif = re.compile(texte)
            groupes = {g: gabarit.groupes[g] for g in motif.groupindex if g in gabarit.groupes}
            if {parametre for parametre, _ in groupes.values()} - noms:
                raise ValueError(f"{choc} : un motif nomme un paramètre absent du catalogue")
            motifs.append((rang, choc, motif, groupes))
    return motifs


_MOTIFS = _compiler()


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def normaliser(question: str) -> str:
    """Minuscules, accents retirés, espaces insécables et apostrophes typographiques ramenés, espaces réduits."""
    texte = unicodedata.normalize("NFKD", question)
    texte = "".join(c for c in texte if not unicodedata.combining(c)).lower()
    texte = texte.replace("’", "'").replace("ʼ", "'").replace("`", "'")
    return re.sub(r"\s+", " ", texte).strip()


def _valeur(groupe: str, genre: str, correspondance: re.Match[str]) -> str:
    brut = correspondance.group(groupe)
    if genre == "entier":
        return str(_MOTS_NOMBRES[brut]) if brut in _MOTS_NOMBRES else str(int(brut))
    if genre == "pct":
        return brut.replace(",", ".")
    entier = brut.replace(" ", "")
    decimales = correspondance.group(f"{groupe}d")
    valeur = Decimal(f"{entier}.{decimales}" if decimales else entier)
    if correspondance.group(f"{groupe}k"):
        valeur *= 1000
    return format(valeur, "f")


def _proposition(choc: str, groupes: dict[str, tuple[str, str]], correspondance: re.Match[str]) -> dict:
    dits: dict[str, str] = {}
    for groupe, (parametre, genre) in groupes.items():
        if correspondance.group(groupe) is None:
            continue
        valeur = _valeur(groupe, genre, correspondance)
        if parametre in dits and dits[parametre] != valeur:
            raise _refus("REJ-QUESTION-AMBIGUE", f"{choc} : deux valeurs différentes pour {parametre}")
        scenarios.valider_parametre(choc, parametre, valeur)  # refus nommé du catalogue (nombre, borne)
        dits[parametre] = valeur
    attendus = [p.nom for p in scenarios.CHOCS[choc].parametres]
    a_fournir = [nom for nom in attendus if nom not in dits]
    return {
        "choc": choc,
        "libelle": scenarios.CHOCS[choc].libelle,
        "parametres": {nom: dits[nom] for nom in attendus if nom in dits},
        "parametres_a_fournir": a_fournir,
        "unites": {p.nom: p.unite for p in scenarios.CHOCS[choc].parametres},
        "bases_requises": scenarios.bases_requises(choc),
        "statut": "COMPLETE" if not a_fournir else "PARAMETRES_A_FOURNIR",
        "extrait": correspondance.group(0),
    }


def interpreter(question: str) -> dict:
    """Propositions de chocs pour une question « et si… » ; refus nommés, jamais de paramètre deviné."""
    if type(question) is not str:
        raise _refus("REJ-QUESTION-TYPE", "texte requis")
    if len(question) > MAX_QUESTION:
        raise _refus("REJ-QUESTION-LONGUEUR", f"au plus {MAX_QUESTION} caractères")
    texte = normaliser(question)
    if not texte:
        raise _refus("REJ-QUESTION-VIDE", "question vide")
    for occurrence in re.finditer(rf"{_POURCENT}", texte):
        if not re.search(r"\d\s?$", texte[: occurrence.start()]):
            raise _refus(
                "REJ-QUESTION-POURCENTAGE-EN-LETTRES",
                "écrire le pourcentage en chiffres (ex. « 25 % ») ; aucune conversion de mots n'est tentée",
            )
    if re.search(r"(?<![\w])[-−]\s?\d", texte):
        raise _refus("REJ-QUESTION-NOMBRE-SIGNE", "un nombre signé n'est pas admis : le sens du choc dit la direction")
    candidats = []
    for rang, choc, motif, groupes in _MOTIFS:
        for correspondance in motif.finditer(texte):
            if correspondance.end() > correspondance.start():
                candidats.append((correspondance.start(), -correspondance.end(), rang, choc, groupes, correspondance))
    candidats.sort(key=lambda c: c[:3])
    retenues, occupe, vues = [], [], set()
    for debut, fin_negative, _rang, choc, groupes, correspondance in candidats:
        fin = -fin_negative
        if any(debut < f and d < fin for d, f in occupe):
            continue
        occupe.append((debut, fin))
        proposition = _proposition(choc, groupes, correspondance)
        cle = (choc, tuple(sorted(proposition["parametres"].items())))
        if cle not in vues:
            vues.add(cle)
            retenues.append(proposition)
    entete = {
        "type": "INTERPRETATION_QUESTION_SCENARIO",
        "version": VERSION,
        "question_sha256": hashlib.sha256(texte.encode()).hexdigest(),
        "limites": list(_LIMITES),
    }
    if not retenues:
        return {
            **entete,
            "propositions": [],
            "statut": "QUESTION_NON_RECONNUE",
            "choc_disponibles": [{"choc": c.id, "libelle": c.libelle} for c in scenarios.CHOCS.values()],
        }
    return {**entete, "statut": "RECONNUE", "propositions": retenues}
