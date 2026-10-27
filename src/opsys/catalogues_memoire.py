"""Publication transactionnelle d'une référence de version, jamais de son contenu privé."""
import hashlib

from . import evenements, stockage

SOURCES = {
    ('m03-estimation', 'modeles_soumission'): ('m3_modeles', 'm3.catalogue_reference'),
    ('m03-estimation', 'modeles_lignes_soumission'): ('m3_lignes', 'm3.catalogue_reference'),
    ('m06-material-control', 'catalogue_materiaux'): ('m6_materiaux', 'm6.catalogue_reference'),
}


def _reference(producteur, registre, source_hash):
    genre, type_evenement = SOURCES[(producteur, registre)]
    journal = stockage.maillons(producteur, registre)
    if len(journal) > 10000:
        raise ValueError('Source de catalogue hors borne')
    candidats = [(rang, m) for rang, m in enumerate(journal) if m.get('source_id') == source_hash]
    if len(candidats) != 1:
        raise ValueError('Version de catalogue introuvable ou ambiguë')
    rang, m = candidats[0]
    revision = m['revision']
    fait_id = hashlib.sha256(f'catalogue-reference-v1:{genre}:{rang}:{revision}:{source_hash}'.encode()).hexdigest()
    charge = dict(fait_id=fait_id, source_genre=genre, source_rang=rang, source_revision=revision,
                  source_sha256=source_hash, horodatage=m['horodatage'])
    verifier_source(genre, rang, revision, source_hash, m['horodatage'])
    return type_evenement, charge


def publier(producteur, registre, source_hash):
    type_evenement, charge = _reference(producteur, registre, source_hash)
    return evenements.publier(type_evenement, producteur, charge,
                              evenement_id='catalogue-reference-' + charge['fait_id'])


def verifier_source(genre, rang, revision, source_hash, horodatage):
    """Courtier socle : relecture par le domaine propriétaire, aucune copie privée vers M10."""
    cle = next((cle for cle, valeur in SOURCES.items() if valeur[0] == genre), None)
    if cle is None:
        raise ValueError('Genre de catalogue inconnu')
    journal = stockage.maillons(*cle)
    if len(journal) > 10000:
        raise ValueError('Source de catalogue hors borne')
    original = next((m for i, m in enumerate(journal) if i == rang), None)
    if not isinstance(original, dict):
        raise ValueError('Source de référence configuration absente ou incohérente')
    # Le socle est le courtier entre propriétaires; aucun département n'importe un autre département.
    if genre == 'm6_materiaux':
        from m6_material_control import catalogue_materiaux as domaine

        try:
            source = domaine.lire(journal, original['materiau_id'], revision=revision)
        except (domaine.CatalogueRefuse, KeyError):
            raise ValueError('Source de référence configuration invalide') from None
    else:
        from m3_estimation import modeles_lignes_soumission, modeles_soumission

        try:
            if genre == 'm3_modeles':
                source = modeles_soumission.lire(journal, original['modele_id'], revision)['resultat']
            else:
                source = modeles_lignes_soumission.lire(
                    journal, original['modele_id'], original['modele_source'], revision)['resultat']
        except (modeles_soumission.Refus, KeyError):
            raise ValueError('Source de référence configuration invalide') from None
    if (source['source_id'] != source_hash or source['revision'] != revision or source['horodatage'] != horodatage
            or original.get('source_id') != source_hash or original.get('revision') != revision):
        raise ValueError('Source de référence configuration absente ou incohérente')


def consulter(producteur, registre, source_hash):
    """Projection de preuve pour une façade autorisée : publié ne veut pas dire mémorisé."""
    from m10_memoire import references_configuration
    from sqlalchemy import select

    from .stockage import codec
    from .stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

    type_evenement, attendu = _reference(producteur, registre, source_hash)
    eid = 'catalogue-reference-' + attendu['fait_id']
    cnx = stockage.connexion_courante()
    publication = cnx.execute(select(EVENEMENTS_SORTANTS).where(
        EVENEMENTS_SORTANTS.c.evenement_id == eid)).mappings().one_or_none()
    recu = cnx.execute(select(EVENEMENTS_RECUS).where(
        (EVENEMENTS_RECUS.c.evenement_id == eid) &
        (EVENEMENTS_RECUS.c.consommateur == 'm10-memoire'))).mappings().one_or_none()
    memoire = references_configuration.lire(
        stockage.maillons('m10-memoire', references_configuration.REGISTRE), attendu['fait_id'])
    conflit = memoire is not None and any(memoire[k] != v for k, v in attendu.items())
    if publication is not None:
        conflit |= (publication['producteur'] != producteur or publication['type_evenement'] != type_evenement
                    or codec.decoder(publication['charge']) != attendu)
    resultat = codec.decoder(recu['resultat']) if recu is not None and recu['resultat'] else None
    livre = (recu is not None and recu['statut'] == 'traite' and memoire is not None
             and isinstance(resultat, dict) and resultat.get('memorise') is True
             and resultat.get('fait_id') == attendu['fait_id'] and resultat.get('ligne_id') == memoire['ligne_id'])
    if recu is not None and recu['statut'] == 'traite' and not livre:
        conflit = True
    if publication is None and (recu is not None or memoire is not None):
        conflit = True
    if conflit:
        etat = 'CONFLIT'
    elif publication is None:
        etat = 'NON_PUBLIE'
    elif livre:
        etat = 'MEMORISE'
    else:
        etat = {'echec': 'ECHEC_LIVRAISON', 'quarantaine': 'QUARANTAINE'}.get(
            recu['statut'] if recu is not None else None, 'EN_ATTENTE')
    return {'etat': etat, 'revision': attendu['source_revision']}
