"""Publication transactionnelle d'une référence de version, jamais de son contenu privé."""
import hashlib

from . import evenements, stockage

SOURCES = {
    ('m03-estimation', 'modeles_soumission'): ('m3_modeles', 'm3.catalogue_reference'),
    ('m03-estimation', 'modeles_lignes_soumission'): ('m3_lignes', 'm3.catalogue_reference'),
    ('m06-material-control', 'catalogue_materiaux'): ('m6_materiaux', 'm6.catalogue_reference'),
}


def publier(producteur, registre, source_hash):
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
    return evenements.publier(type_evenement, producteur, charge, evenement_id='catalogue-reference-' + fait_id)


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
