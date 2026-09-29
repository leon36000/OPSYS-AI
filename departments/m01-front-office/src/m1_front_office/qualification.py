import hashlib
import re
import unicodedata

from opsys import taxonomie

from . import verdicts

# Le service demandé n'est plus reconnu par des motifs codés ici : la liste des services, et les
# termes qui les évoquent, viennent de la taxonomie du socle (`opsys.taxonomie`, PLAN T0.13),
# paramétrée par le profil d'entreprise de l'instance. Ce module ne connaît aucun service.

# Correctif d'audit : aucune ville n'est codée en dur dans ce module. La zone
# desservie (quelles villes l'entreprise dessert) est une donnée de
# configuration métier, propre à chaque installation OPSYS ; elle est fournie
# par l'appelant à chaque appel (paramètre zone_desservie de qualifier()),
# jamais inventée ni figée ici.

# Marqueurs d'urgence explicites (jamais inférés)
_URGENCE_PATTERNS = [
    re.compile(r"urgent", re.IGNORECASE),
    re.compile(r"urgence", re.IGNORECASE),
    re.compile(r"au\s+plus\s+vite", re.IGNORECASE),
    re.compile(r"d[ée]g[âa]t\s+d['’]?eau", re.IGNORECASE),
    re.compile(r"\bfuite\b", re.IGNORECASE),
]

# Marqueur de neutralisation posé par S005, à ignorer
_MARQUEUR = re.compile(r"\[CONTENU_NON_FIABLE\]", re.IGNORECASE)

# Expression régulière pour détecter une ville (utilisée avec \b et escape)
_VILLE_REGEX_CACHE = {}

# --------------------------------------------------
# Motifs de contact
# --------------------------------------------------
_PHONE_REGEX = re.compile(
    r'''
    (?:\(\d{3}\)\s?\d{3}[-.\s]?\d{4}  # (514) 555-0142
    |\d{3}[-.\s]?\d{3}[-.\s]?\d{4}   # 514-555-0142, 514 555 0142, 5145550142
    )\b
    ''',
    re.VERBOSE
)

_EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')


def _rejet(detail: str | None = None):
    """Verdict de rejet normalisé."""
    return {"verdict": verdicts.construire_verdict("REJ-QUALIF-INSUFFISANTE", detail=detail)}


def _clean(contenu_filtre: str) -> str:
    """Supprime le marqueur de contenu non fiable et nettoie les blancs."""
    return _MARQUEUR.sub("", contenu_filtre).strip()


def _sans_accent(texte: str) -> str:
    """Minuscules sans accents, apostrophe typographique ramenée à l'apostrophe droite."""
    decompose = unicodedata.normalize("NFKD", texte.replace("\u2019", "'").lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


_MOTIFS_SERVICE_CACHE = {}


def _motif_service(service: taxonomie.Service):
    """Regex du service : un de ses mots-clés, mot entier, pluriel admis, accents et casse ignorés."""
    cle = (service.code, service.mots_cles)
    if cle not in _MOTIFS_SERVICE_CACHE:
        alternatives = []
        for terme in service.mots_cles:
            mots = [re.escape(m) + "s?" for m in _sans_accent(terme).split()]
            alternatives.append(r"\s+".join(mots))
        _MOTIFS_SERVICE_CACHE[cle] = (
            re.compile(r"\b(?:" + "|".join(alternatives) + r")\b") if alternatives else None
        )
    return _MOTIFS_SERVICE_CACHE[cle]


def _extraire_service(contenu: str, services):
    """Retourne `(code, None)` si UN SEUL service déclaré est évoqué, sinon `(None, raison)`.

    Le lead porte un seul `service` : un signal qui en évoque plusieurs, ou aucun, n'est pas
    qualifié (fail-closed, jamais un choix arbitraire). L'agent demande alors lequel. La règle de
    précédence (p. ex. « réparation de gouttières ») reste une décision du propriétaire (T2.1).
    """
    texte = _sans_accent(contenu)
    evoques = []
    for service in services:
        motif = _motif_service(service)
        if motif is not None and motif.search(texte):
            evoques.append(service.code)
    if len(evoques) == 1:
        return evoques[0], None
    if not evoques:
        return None, "aucun service déclaré n'est reconnu dans la demande : demander quel service est visé"
    return None, (
        f"plusieurs services évoqués ({', '.join(evoques)}) : demander lequel traiter en premier"
    )


def _extraire_ville(contenu: str, zone_desservie):
    """Retourne la première ville de la zone desservie reconnue, ou None.

    zone_desservie est fournie par l'appelant (aucune ville codée en dur ici).
    Le cache de regex reste global : il est indexé par nom de ville, pas par
    zone, donc partageable en toute sécurité entre appels à zones différentes.
    """
    for ville in sorted(zone_desservie, key=lambda v: -len(v)):
        if ville not in _VILLE_REGEX_CACHE:
            _VILLE_REGEX_CACHE[ville] = re.compile(
                r"\b" + re.escape(ville) + r"\b", re.IGNORECASE
            )
        if _VILLE_REGEX_CACHE[ville].search(contenu):
            return ville
    return None


def _extraire_urgence(contenu: str) -> bool:
    """Détecte la présence d'un marqueur d'urgence explicite."""
    return any(p.search(contenu) for p in _URGENCE_PATTERNS)


def _extraire_contact(contenu: str) -> dict | None:
    """Extrait un contact (téléphone et/ou courriel) du contenu.
    Retourne None si aucun contact trouvé.
    """
    contact = {}
    phone_match = _PHONE_REGEX.search(contenu)
    if phone_match:
        contact["telephone"] = phone_match.group().strip()
    email_match = _EMAIL_REGEX.search(contenu)
    if email_match:
        contact["courriel"] = email_match.group().strip()
    return contact if contact else None


def _materiau_lead_id(conversation_id: str, contenu: str) -> str:
    """Encodage canonique INJECTIF (préfixage par longueur) : deux couples différents
    ne peuvent pas produire le même matériau, contrairement à une concaténation directe."""
    return f"{len(conversation_id)}:{conversation_id}|{len(contenu)}:{contenu}"


def qualifier(
    contenu_filtre: str,
    canal: str,
    conversation_id: str,
    zone_desservie,
    services=None,
    source: str | None = None,
    utm: dict | None = None,
    campagne: str | None = None,
) -> dict:
    """
    Extrait les informations obligatoires d'un message filtré.
    Retourne un LeadQualifie v2 selon le contrat M1-M2 (`m1-lead-qualifie.v2.yaml`),
    ou un verdict de rejet REJ-QUALIF-INSUFFISANTE.

    zone_desservie : villes desservies par l'entreprise, fournies par l'appelant
        (configuration métier propre à l'installation). Requise et non vide :
        aucune ville n'est codée en dur dans ce module (correctif d'audit) ;
        sans zone, le module refuse plutôt que d'inventer une couverture.
    services : services que l'entreprise offre (`opsys.taxonomie.Service`, avec leurs mots-clés).
        Absent, le profil d'entreprise de l'instance est lu. Sans service déclaré, le module
        refuse (ValueError qui dit quoi configurer) plutôt que d'inventer un service.
    source, utm, campagne : provenance marketing, transmise telle que fournie par l'appelant ;
        jamais devinée, absente du lead si elle n'est pas fournie.
    """
    if not zone_desservie:
        raise ValueError(
            "zone_desservie requise et non vide : aucune ville n'est codée en dur "
            "dans qualification.py, l'appelant doit fournir la zone desservie"
        )
    if services is None:
        services, verdict_profil = taxonomie.charger_services()
        if verdict_profil is not None:
            raise ValueError(f"{verdict_profil['code']}: {verdict_profil['detail']}")
    contenu = _clean(contenu_filtre)
    if not contenu:
        return _rejet()

    service, raison = _extraire_service(contenu, services)
    if service is None:
        return _rejet(raison)

    ville = _extraire_ville(contenu, zone_desservie)
    if ville is None:
        return _rejet()

    urgence = _extraire_urgence(contenu)

    contact = _extraire_contact(contenu)
    if contact is None:
        return _rejet()

    materiau = _materiau_lead_id(conversation_id, contenu)
    lead_id = hashlib.sha256(materiau.encode("utf-8")).hexdigest()

    lead = {
        "schema_version": 2,
        "lead_id": lead_id,
        "service": service,
        "ville": ville,
        "urgence_declaree": urgence,
        "canal": canal,
        "conversation_id": conversation_id,
        "contact": contact,
    }
    for cle, valeur in (("source", source), ("utm", utm), ("campagne", campagne)):
        if valeur is not None:
            lead[cle] = valeur
    return lead
