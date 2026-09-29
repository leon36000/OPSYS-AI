"""Digest quotidien déterministe du pipeline commercial.

Le digest est une fonction PURE du registre : aucune écriture, aucune
horloge interne. L'instant de production est fourni par l'appelant, ce
qui garantit une sortie byte-identique à entrées égales, indépendante
de l'ordre d'ingestion et du fuseau horaire de la machine.
"""

from datetime import UTC, datetime, timedelta

# Seuil ratifié : un lead « nouveau » sans owner n'est déclaré orphelin
# qu'au-delà de 48 heures STRICTES, afin que la frontière soit univoque
# (un écart d'exactement 48 h ne déclenche aucun signalement).
SEUIL_ORPHELIN_HEURES = 48

# Statuts considérés « en attente » d'action commerciale dans le digest.
_STATUTS_EN_ATTENTE = ("nouveau", "qualifie")

# Valeur d'arbitrage marquant un signalement encore non tranché ; toute
# autre valeur (par exemple « distincts_confirmes ») est une décision
# humaine qui sort le signalement du digest.
_ARBITRAGE_EN_ATTENTE = "en_attente"


def _normaliser_utc(valeur):
    """Convertit un horodatage ISO-8601 fourni en instant UTC.

    La normalisation UTC rend la comparaison inter-fuseaux déterministe :
    deux libellés distincts désignant le même instant donnent le même
    résultat, quelle que soit la machine qui exécute le calcul.

    Le fuseau est OBLIGATOIRE et son absence est un refus, jamais une
    supposition. POURQUOI : sur une chaîne naïve, ``astimezone`` retomberait
    sur le fuseau local de la machine, qui est une entrée AMBIANTE non
    fournie par l'appelant. Mesuré sur un même registre avec un même
    horodatage naïf : orphelin vrai sous TZ=UTC, faux sous
    TZ=Pacific/Kiritimati. Cela briserait CA-M2-09 (sortie byte-identique à
    entrées égales) et l'invariant « zéro horloge interne » du §8. Le module
    reste donc fail-closed : il lève plutôt que de deviner.
    """
    instant = datetime.fromisoformat(valeur)
    if instant.tzinfo is None or instant.tzinfo.utcoffset(instant) is None:
        raise ValueError(
            "horodatage sans fuseau refusé : le fuseau est obligatoire, sinon "
            "la sortie dépendrait du fuseau local de la machine "
            f"(reçu {valeur!r})"
        )
    return instant.astimezone(UTC)


def _est_en_attente(arbitrage):
    """Vrai si le signalement n'a pas encore reçu d'arbitrage humain.

    L'absence d'arbitrage est équivalente à la valeur par défaut
    'en_attente'.
    """
    return arbitrage == _ARBITRAGE_EN_ATTENTE


def _date_cible(date_jour):
    """Convertit date_jour ("AAAA-MM-JJ") en date calendaire, pour le filtre.

    Une date_jour invalide est un refus (fail-closed), jamais une valeur par
    défaut : produire un digest sans savoir de quel jour il parle serait pire
    qu'un rejet explicite.
    """
    try:
        return datetime.fromisoformat(date_jour).date()
    except (ValueError, TypeError) as exc:
        raise ValueError(f"date_jour invalide, attendu AAAA-MM-JJ : {date_jour!r}") from exc


def produire_digest(registre_cible, date_jour, horodatage):
    """Produit un digest déterministe du pipeline commercial.

    Args:
        registre_cible: instance de Registre supportant .lire().
        date_jour: chaîne de date (ex: "2026-03-03"), date cible du digest.
            Filtre réellement l'état reconstruit : seuls les maillons
            horodatés à date_jour ou avant comptent (état du pipeline « tel
            qu'il était » à la fin de cette journée-là). Un maillon postérieur
            à date_jour (ingestion, transition ou signalement futur du point
            de vue du digest demandé) est ignoré, comme s'il n'existait pas
            encore — c'était le filtre que date_jour était censé appliquer et
            qu'il ignorait avant ce correctif d'audit.
        horodatage: chaîne ISO-8601 avec timezone, instant de production
            du digest (sert au calcul des orphelins à 48h, indépendant du
            filtre date_jour ci-dessus).

    Returns:
        Chaîne structurée contenant les sections [EN_ATTENTE],
        [ORPHELINS], [DOUBLONS_EN_ATTENTE], triées de façon déterministe.
        La sortie est byte-identique pour des entrées égales.
    """
    prod_dt = _normaliser_utc(horodatage)
    date_cible = _date_cible(date_jour)

    # Structures de reconstruction depuis les maillons du registre.
    lead_statut = {}          # lead_id -> statut courant (à date_jour)
    lead_owner = {}           # lead_id -> owner (str ou None)
    lead_ingestion = {}       # lead_id -> (horodatage_str, datetime_utc)
    signalement_arbitrage = {}  # signalement_id -> dernier arbitrage (à date_jour)

    # Parcours unique du registre pour extraire l'état "à la date_jour" :
    # un maillon horodaté après date_jour est ignoré, comme s'il n'était pas
    # encore survenu au moment visé par ce digest.
    for maillon in registre_cible.lire():
        type_entree = maillon.get('type_entree')
        if type_entree in ('lead_ingere', 'transition_statut', 'doublon_signale', 'reassignation'):
            horo_maillon = maillon.get('horodatage')
            if horo_maillon and _normaliser_utc(horo_maillon).date() > date_cible:
                continue
        if type_entree == 'lead_ingere':
            lead_id = maillon['lead_id']
            horo_str = maillon['horodatage']
            horo_dt = _normaliser_utc(horo_str)
            lead_ingestion[lead_id] = (horo_str, horo_dt)
            lead_statut[lead_id] = "nouveau"
        elif type_entree == 'transition_statut':
            lead_id = maillon['lead_id']
            statut = maillon['statut']
            lead_statut[lead_id] = statut
            if statut == 'qualifie' and 'owner' in maillon:
                lead_owner[lead_id] = maillon['owner']
        elif type_entree == 'reassignation':
            # PLAN T1.4-m : le propriétaire affiché est le courant, celui de la dernière réassignation
            # (horodatée au plus tard à date_jour, comme le reste de ce parcours).
            lead_owner[maillon['lead_id']] = maillon['nouveau_proprietaire']
        elif type_entree == 'doublon_signale':
            sid = maillon['signalement_id']
            arbitrage = maillon.get('arbitrage', _ARBITRAGE_EN_ATTENTE)
            signalement_arbitrage[sid] = arbitrage

    # Préparation de la liste des leads en attente.
    leads_en_attente = []
    for lead_id, statut in lead_statut.items():
        if statut in _STATUTS_EN_ATTENTE:
            ingestion_str, ingestion_dt = lead_ingestion.get(lead_id, ('', None))
            if ingestion_dt is None:
                continue  # ne devrait pas arriver (lead sans ingestion enregistrée)
            owner = lead_owner.get(lead_id)
            owner_str = owner if owner else "-"
            leads_en_attente.append((lead_id, statut, ingestion_str, ingestion_dt, owner_str))

    # Tri déterministe : par date d'ingestion UTC, puis par lead_id
    # (aucune itération sur dict non triée ci-dessus).
    leads_en_attente.sort(key=lambda x: (x[3], x[0]))

    lignes = []
    # En-tête du digest
    lignes.append(f"DIGEST date_jour={date_jour} horodatage={horodatage}")

    # Section [EN_ATTENTE]
    lignes.append("[EN_ATTENTE]")
    for lead_id, statut, ingestion_str, _, owner_str in leads_en_attente:
        lignes.append(f"  {lead_id} statut={statut} ingere={ingestion_str} owner={owner_str}")

    # Section [ORPHELINS] : leads nouveaux sans owner, ingérés depuis > 48h
    seuil = timedelta(hours=SEUIL_ORPHELIN_HEURES)
    orphelins = []
    for lead_id, statut, _, ingestion_dt, owner_str in leads_en_attente:
        if statut == "nouveau" and owner_str == "-" and (prod_dt - ingestion_dt) > seuil:
            orphelins.append(lead_id)
    orphelins.sort()
    lignes.append("[ORPHELINS]")
    for lead_id in orphelins:
        lignes.append(f"  {lead_id}")

    # Section [DOUBLONS_EN_ATTENTE]
    doublons_en_attente = sorted(
        sid for sid, arb in signalement_arbitrage.items() if _est_en_attente(arb)
    )
    lignes.append("[DOUBLONS_EN_ATTENTE]")
    for sid in doublons_en_attente:
        lignes.append(f"  {sid}")

    return "\n".join(lignes)
