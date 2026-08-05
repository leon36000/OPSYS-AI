# audit/contrats.py
import re
import unicodedata

SEVERITE = ("critique", "majeure", "mineure", "indetermine")
CLASSE = (
    "defaut-code",
    "ecart-plan",
    "faille-securite",
    "goulot-performance",
    "incoherence-documentaire",
    "indetermine",
)
STATUT_CONSTAT = (
    "ouvert",
    "confirme",
    "refute",
    "arbitrage-humain",
    "indetermine",
)

_CHAMPS_CONSTAT = (
    "id",
    "lot",
    "classe",
    "titre",
    "emplacement",
    "temoin",
    "temoin_rc",
    "temoin_sortie_sha256",
    "entrees_rubrique",
    "severite",
    "statut",
    "refutation",
    "assume_ref",
)

_CHAMPS_ENTREES_RUBRIQUE = (
    "frontiere_t3",
    "gate_couvrant",
    "rayon",
    "contrat_gele",
)

_CHAMPS_REFUTATION = ("cmd", "sortie", "conclusion")

_MOTIF_ID = re.compile(r"^AUD-A[1-7]-\d{3}$")
_MOTIF_EMPLACEMENT = re.compile(r"^.+:[1-9]\d*$")
_MOTIF_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ADJECTIFS_GRAVITE = {
    "critique",
    "grave",
    "majeur",
    "mineur",
    "dangereux",
    "severe",
    "catastrophique",
    "benin",
}


def _code_valeur(champ: str, valeur: object) -> str:
    return f"{champ}_VALEUR_INVALIDE:{valeur!r}"


def _code_type(champ: str, valeur: object) -> str:
    return f"{champ}_TYPE_INVALIDE:{type(valeur).__name__}"


def _normaliser_sans_accents(texte: str) -> str:
    decomposition = unicodedata.normalize("NFD", texte.casefold())
    return "".join(
        caractere
        for caractere in decomposition
        if unicodedata.category(caractere) != "Mn"
    )


def _valider_cles(
    valeur: dict,
    champs_attendus: tuple[str, ...],
    prefixe: str,
) -> str:
    for champ in champs_attendus:
        if champ not in valeur:
            return f"{prefixe}_CLE_MANQUANTE:{champ}"
    for champ in valeur:
        if champ not in champs_attendus:
            return f"{prefixe}_CLE_EN_TROP:{champ!r}"
    return ""


def _valider_titre(titre: str) -> str:
    texte = titre.strip()
    if not texte:
        return _code_valeur("TITRE", titre)
    if "\n" in texte or "\r" in texte:
        return _code_valeur("TITRE_PHRASE", titre)
    if re.search(r"[.!?]", texte[:-1]):
        return _code_valeur("TITRE_PHRASE", titre)

    mots = re.findall(r"\b\w+\b", _normaliser_sans_accents(texte))
    for mot in mots:
        if mot in _ADJECTIFS_GRAVITE:
            return f"TITRE_ADJECTIF_GRAVITE_INTERDIT:{mot!r}"
    return ""


def valider_constat(constat: dict) -> tuple[bool, str]:
    if not isinstance(constat, dict):
        return False, _code_type("CONSTAT", constat)

    rejet = _valider_cles(constat, _CHAMPS_CONSTAT, "CONSTAT")
    if rejet:
        return False, rejet

    identifiant = constat["id"]
    if not isinstance(identifiant, str):
        return False, _code_type("ID", identifiant)
    if not _MOTIF_ID.fullmatch(identifiant):
        return False, _code_valeur("ID", identifiant)

    lot = constat["lot"]
    if not isinstance(lot, str):
        return False, _code_type("LOT", lot)
    if lot not in ("A1", "A2", "A3", "A4", "A5", "A6", "A7"):
        return False, _code_valeur("LOT", lot)

    classe = constat["classe"]
    if not isinstance(classe, str):
        return False, _code_type("CLASSE", classe)
    if classe not in CLASSE:
        return False, _code_valeur("CLASSE", classe)

    titre = constat["titre"]
    if not isinstance(titre, str):
        return False, _code_type("TITRE", titre)
    rejet = _valider_titre(titre)
    if rejet:
        return False, rejet

    emplacement = constat["emplacement"]
    if not isinstance(emplacement, list):
        return False, _code_type("EMPLACEMENT", emplacement)
    if not emplacement:
        return False, _code_valeur("EMPLACEMENT", emplacement)
    for indice, element in enumerate(emplacement):
        if not isinstance(element, str):
            return False, _code_type(f"EMPLACEMENT_ELEMENT_{indice}", element)
        if not _MOTIF_EMPLACEMENT.fullmatch(element):
            return False, _code_valeur(f"EMPLACEMENT_ELEMENT_{indice}", element)

    temoin = constat["temoin"]
    if not isinstance(temoin, str):
        return False, _code_type("TEMOIN", temoin)
    if not temoin:
        return False, _code_valeur("TEMOIN", temoin)

    temoin_rc = constat["temoin_rc"]
    if type(temoin_rc) is not int:
        return False, _code_type("TEMOIN_RC", temoin_rc)
    if temoin_rc == 0:
        return False, _code_valeur("TEMOIN_RC", temoin_rc)

    temoin_sortie_sha256 = constat["temoin_sortie_sha256"]
    if not isinstance(temoin_sortie_sha256, str):
        return False, _code_type("TEMOIN_SORTIE_SHA256", temoin_sortie_sha256)
    if not _MOTIF_SHA256.fullmatch(temoin_sortie_sha256):
        return False, _code_valeur("TEMOIN_SORTIE_SHA256", temoin_sortie_sha256)

    entrees_rubrique = constat["entrees_rubrique"]
    if not isinstance(entrees_rubrique, dict):
        return False, _code_type("ENTREES_RUBRIQUE", entrees_rubrique)
    rejet = _valider_cles(
        entrees_rubrique,
        _CHAMPS_ENTREES_RUBRIQUE,
        "ENTREES_RUBRIQUE",
    )
    if rejet:
        return False, rejet

    frontiere_t3 = entrees_rubrique["frontiere_t3"]
    if type(frontiere_t3) is not bool:
        return False, _code_type("ENTREES_RUBRIQUE_FRONTIERE_T3", frontiere_t3)

    gate_couvrant = entrees_rubrique["gate_couvrant"]
    if type(gate_couvrant) is not bool:
        return False, _code_type("ENTREES_RUBRIQUE_GATE_COUVRANT", gate_couvrant)

    rayon = entrees_rubrique["rayon"]
    if type(rayon) is not int:
        return False, _code_type("ENTREES_RUBRIQUE_RAYON", rayon)
    if rayon < 0:
        return False, _code_valeur("ENTREES_RUBRIQUE_RAYON", rayon)

    contrat_gele = entrees_rubrique["contrat_gele"]
    if not isinstance(contrat_gele, str):
        return False, _code_type("ENTREES_RUBRIQUE_CONTRAT_GELE", contrat_gele)

    severite = constat["severite"]
    if not isinstance(severite, str):
        return False, _code_type("SEVERITE", severite)
    if severite not in SEVERITE:
        return False, _code_valeur("SEVERITE", severite)

    statut = constat["statut"]
    if not isinstance(statut, str):
        return False, _code_type("STATUT", statut)
    if statut not in STATUT_CONSTAT:
        return False, _code_valeur("STATUT", statut)

    refutation = constat["refutation"]
    if not isinstance(refutation, dict):
        return False, _code_type("REFUTATION", refutation)
    rejet = _valider_cles(refutation, _CHAMPS_REFUTATION, "REFUTATION")
    if rejet:
        return False, rejet
    for champ in _CHAMPS_REFUTATION:
        valeur = refutation[champ]
        if not isinstance(valeur, str):
            return False, _code_type(f"REFUTATION_{champ.upper()}", valeur)
        if not valeur:
            return False, _code_valeur(f"REFUTATION_{champ.upper()}", valeur)

    assume_ref = constat["assume_ref"]
    if assume_ref is not None and not isinstance(assume_ref, str):
        return False, _code_type("ASSUME_REF", assume_ref)

    return True, ""
