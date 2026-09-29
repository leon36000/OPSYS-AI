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


def _rejet(detail: str | None = None, champs_manquants: list[str] | None = None):
    """Verdict de rejet normalisé. `champs_manquants` nomme CHAQUE champ du lead que le contenu n'établit pas."""
    rejet: dict = {"verdict": verdicts.construire_verdict("REJ-QUALIF-INSUFFISANTE", detail=detail)}
    if champs_manquants is not None:
        rejet["champs_manquants"] = champs_manquants
    return rejet


def _clean(contenu_filtre: str) -> str:
    """Supprime le marqueur de contenu non fiable et nettoie les blancs."""
    return _MARQUEUR.sub("", contenu_filtre).strip()


def contenu_utile(contenu_filtre: str) -> str:
    """Le contenu sans le marqueur de neutralisation de la provenance : ce que les règles de lecture regardent."""
    return _clean(contenu_filtre)


def _sans_accent(texte: str) -> str:
    """Minuscules sans accents, apostrophe typographique ramenée à l'apostrophe droite."""
    decompose = unicodedata.normalize("NFKD", texte.replace("\u2019", "'").lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


_MOTIFS_CACHE = {}


def motif_de_termes(termes):
    """Regex qui reconnaît un des termes, mot entier, pluriel admis, accents et casse ignorés (à chercher dans un texte
    passé par `sans_accent`). Sert aux mots-clés d'un service et à ceux de la réponse à une question du profil : une
    seule règle de lecture. `None` sans terme : rien n'est alors reconnu."""
    termes = tuple(termes)
    if termes not in _MOTIFS_CACHE:
        alternatives = []
        for terme in termes:
            mots = [re.escape(m) + "s?" for m in _sans_accent(terme).split()]
            alternatives.append(r"\s+".join(mots))
        _MOTIFS_CACHE[termes] = re.compile(r"\b(?:" + "|".join(alternatives) + r")\b") if alternatives else None
    return _MOTIFS_CACHE[termes]


def sans_accent(texte: str) -> str:
    """Le texte tel que `motif_de_termes` le veut : minuscules, sans accent, apostrophe droite."""
    return _sans_accent(texte)


def _services_evoques(contenu: str, services) -> list[str]:
    """Codes des services déclarés que le contenu évoque, dans l'ordre de la déclaration."""
    texte = _sans_accent(contenu)
    evoques = []
    for service in services:
        motif = motif_de_termes(service.mots_cles)
        if motif is not None and motif.search(texte):
            evoques.append(service.code)
    return evoques


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


def _source_du_contact(contenu: str, contact_canal: dict | None) -> str | None:
    """`canal` si la plateforme a vérifié l'identité du correspondant, `texte` si le client l'écrit, sinon `None`."""
    if contact_canal:
        return "canal"
    return "texte" if _extraire_contact(contenu) is not None else None


def _diagnostic(contenu: str, zone_desservie, services, contact_canal: dict | None) -> dict:
    """Le diagnostic d'un contenu déjà nettoyé, zone et services déjà validés.

    Le lead porte un seul `service` : un contenu qui en évoque plusieurs, ou aucun, ne l'établit pas (fail-closed,
    jamais un choix arbitraire ; l'agent demande alors lequel). La règle de précédence (p. ex. « réparation de
    gouttières ») reste une décision du propriétaire (T2.1).
    """
    evoques = _services_evoques(contenu, services)
    return {
        "services_evoques": evoques,
        "service": evoques[0] if len(evoques) == 1 else None,
        "ville": _extraire_ville(contenu, zone_desservie),
        "contact": _source_du_contact(contenu, contact_canal),
        "urgence_declaree": _extraire_urgence(contenu),
    }


def diagnostiquer(contenu_filtre: str, zone_desservie, services=None, contact_canal: dict | None = None) -> dict:
    """Ce que le contenu établit déjà, pour dire ce qu'il reste à demander (jamais pour qualifier).

    Retourne `{"services_evoques": [codes], "service": code | None, "ville": ville | None, "contact": "canal" |
    "texte" | None, "urgence_declaree": bool}` : `service` n'est posé que si UN SEUL service déclaré est évoqué (même
    règle que `qualifier`), `ville` que si une ville de `zone_desservie` est reconnue, `contact` que si la plateforme
    a fourni l'identité du correspondant (`contact_canal` : « canal ») ou que le texte donne un téléphone ou un
    courriel (« texte »). Mêmes règles, mêmes sources : ce qui est « connu » ici est exactement ce que `qualifier`
    accepte, jamais davantage. Le contenu est celui de TOUS les messages rassemblés d'une conversation : le service
    dans l'un, la ville dans l'autre, le contact et l'urgence où ils sont écrits.
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
    return _diagnostic(_clean(contenu_filtre), zone_desservie, services, contact_canal)


CHAMPS_DU_LEAD = ("service", "ville", "contact")


def champs_manquants(diagnostic: dict) -> list[str]:
    """Chaque champ du lead que le diagnostic n'établit pas, dans l'ordre `service`, `ville`, `contact`."""
    return [champ for champ in CHAMPS_DU_LEAD if diagnostic[champ] is None]


def _raison_du_champ(champ: str, diagnostic: dict) -> str:
    """Ce qu'il faut demander pour un champ manquant (le détail du verdict de rejet)."""
    if champ == "service":
        evoques = diagnostic["services_evoques"]
        if evoques:
            return f"plusieurs services évoqués ({', '.join(evoques)}) : demander lequel traiter en premier"
        return "aucun service déclaré n'est reconnu dans la demande : demander quel service est visé"
    if champ == "ville":
        return "aucune ville de la zone desservie n'est reconnue : demander la ville de la propriété"
    return "aucun téléphone ni courriel : demander comment joindre le client"


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


def _materiau_lead_id(conversation_id: str, contenu: str, identite: str | None = None) -> str:
    """Encodage canonique INJECTIF (préfixage par longueur) : deux couples différents
    ne peuvent pas produire le même matériau, contrairement à une concaténation directe.

    `identite` (optionnelle) s'ajoute comme troisième segment ; absente, le matériau est celui d'avant, octet pour
    octet : les `lead_id` déjà émis ne changent pas."""
    materiau = f"{len(conversation_id)}:{conversation_id}|{len(contenu)}:{contenu}"
    if identite is not None:
        materiau += f"|{len(identite)}:{identite}"
    return materiau


def qualifier(
    contenu_filtre: str,
    canal: str,
    conversation_id: str,
    zone_desservie,
    services=None,
    source: str | None = None,
    utm: dict | None = None,
    campagne: str | None = None,
    contact_canal: dict | None = None,
    identite_lead: str | None = None,
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
    contact_canal : l'identité que la plateforme a vérifiée pour un message de canal (numéro E.164 d'un SMS,
        adresse d'un courriel, `m1_front_office.reception`). Elle devient le contact du lead, seule : le texte
        du client n'y ajoute rien et ne la remplace pas (M2 tire le `client_id` du contact entier). Absent, le
        contact est cherché dans le texte, comme avant.
    identite_lead : de quoi distinguer deux demandes de même texte d'un même client (le premier message d'une
        conversation rassemblée, `conversation`) ; entre dans l'empreinte du `lead_id`. Absente : `lead_id` d'avant.
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
    diagnostic = _diagnostic(contenu, zone_desservie, services, contact_canal)
    manque = champs_manquants(diagnostic)
    if manque:
        # Le rejet nomme CHAQUE champ manquant (pas seulement le premier) et dit quoi demander pour chacun.
        raisons = " ; ".join(f"{champ} : {_raison_du_champ(champ, diagnostic)}" for champ in manque)
        return _rejet(f"champs manquants ({', '.join(manque)}) — {raisons}", manque)

    service, ville, urgence = diagnostic["service"], diagnostic["ville"], diagnostic["urgence_declaree"]
    contact = dict(contact_canal) if contact_canal else _extraire_contact(contenu)

    materiau = _materiau_lead_id(conversation_id, contenu, identite_lead)
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
