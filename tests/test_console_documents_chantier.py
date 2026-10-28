"""fictif: true — galerie privée M3/M4/CAS; aucun parcours appareil complet prétendu."""
import hashlib
import importlib
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import update

from opsys import evenements, fichiers, identite, stockage
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS, FICHIERS_BLOCS, REGISTRES

spec = importlib.util.spec_from_file_location('documents_crm_fixture',
    Path(__file__).with_name('test_console_preparation_chantier.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, catalogue, affaire = f.client_crm, f.catalogue, f.affaire
FICTIF = True
PNG = b'\x89PNG\r\n\x1a\nIMAGE-CHANTIER-FICTIF'
SHA = hashlib.sha256(PNG).hexdigest()
REF = 'fichier:sha256:' + SHA


def _port():
    return importlib.import_module('opsys.console.documents_chantier')


def _url(a):
    return a['route'].removesuffix('/preparation-chantier') + '/fichiers'


def _depot(cnx, contenu=PNG):
    import base64
    sha = hashlib.sha256(contenu).hexdigest()
    r = fichiers.deposer_bloc(cnx, empreinte_sha256=sha, taille_octets=len(contenu), type_mime='image/png',
        index_bloc=0, nombre_blocs=1, bloc_base64=base64.b64encode(contenu).decode())
    assert r.accepte, r
    return 'fichier:sha256:' + sha


def _completion(a, session, photos, *, dossier=None, signature_requise=False):
    """État terrain de fixture, puis vrai écrivain outbox et vraie publication. Pas un E2E DEVICE."""
    from m4_field_ops import etats, outbox, pointage, registre
    with session() as cnx:
        reg = registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        intervention = etats.intervention_du_devis(reg, a['devis'])
        reg.ajouter(dict(type_entree=etats.TYPE_TRANSITION, intervention_id=intervention,
            statut='sur_site', statut_precedent='planifiee', horodatage='2030-06-01T09:00:00+00:00'))
        for action, heure in [('arrivee', '09'), ('depart', '11')]:
            reg.ajouter(dict(type_entree=pointage.TYPE_POINTAGE, intervention_id=intervention,
                technicien_id='TECH-FICTIF', action=action, horodatage=f'2030-06-01T{heure}:00:00+00:00',
                latitude=45.5, longitude=-73.5, fictif=True))
        _depot(cnx)
        kwargs = {} if photos is None else {'photos': photos}
        if dossier is not None:
            kwargs.update(preuves_completion=dossier, signature_requise=signature_requise)
        recu, verdict = outbox.completer_intervention(intervention, '2030-06-01T11:05:00+00:00', reg,
            ecart_detecte=False, verification_en_attente=True, **kwargs)
        assert verdict is None, verdict
        wct = next(m[outbox.CLE_WCT] for m in reg.lire() if m['ligne_id'] == recu['ligne_id'])
        evenements.publier('m4.travaux_termines', 'm04-field-ops', wct, evenement_id=wct['wct_id'])
    return wct


@pytest.fixture
def photos(affaire, session):
    wct = _completion(affaire, session, [REF])
    return {**affaire, 'wct': wct}


def test_sans_completion_affiche_pdf_m3_et_absence_sans_ecriture(affaire, catalogue, session):
    _port()
    avant = f.m.base._instantane_base(session)
    r = catalogue.get(_url(affaire))
    assert r.status_code == 200, r.text
    assert 'Aucune fin de travaux publiée' in r.text
    assert 'document/pdf' in r.text and 'document/html' in r.text
    assert 'original signé' in r.text
    assert 'Photos et fichiers du chantier' in catalogue.get(_url(affaire).removesuffix('/fichiers')).text
    assert f.m.base._instantane_base(session) == avant


def test_photo_wct_reelle_lecture_exacte_sans_fuite_ni_dml(photos, catalogue, session):
    _port()
    avant = f.m.base._instantane_base(session)
    r = catalogue.get(_url(photos))
    assert r.status_code == 200, r.text
    assert r.headers['cache-control'] == 'no-store'
    assert 'completed_pending_review' in r.text and 'Photo 1' in r.text
    assert 'preuves de complétion historiques' in r.text
    assert 'non conservées' in r.text
    assert '/photos/' + SHA in r.text
    for secret in ('TECH-FICTIF', 'latitude', '-73.5', 'prix_total', '600.00'):
        assert secret not in r.text
    photo = catalogue.get(_url(photos) + '/photos/' + SHA)
    assert photo.status_code == 200 and photo.content == PNG
    assert photo.headers['content-type'] == 'image/png'
    assert photo.headers['cache-control'] == 'no-store'
    assert photo.headers['x-content-type-options'] == 'nosniff'
    assert "default-src 'none'" in photo.headers['content-security-policy']
    assert 'inline;' in photo.headers['content-disposition']
    assert f.m.base._instantane_base(session) == avant


def test_completion_sans_photos_ne_reconstitue_pas_preuves(affaire, catalogue, session):
    _port()
    _completion(affaire, session, None)
    r = catalogue.get(_url(affaire))
    assert r.status_code == 200 and 'Aucune photo déclarée à la fin des travaux' in r.text
    assert '/photos/' not in r.text


@pytest.mark.parametrize('suffixe', ['', '/photos/' + SHA])
def test_autre_projet_et_devis_refuses(photos, catalogue, suffixe):
    _port()
    assert catalogue.get(_url(photos).replace(photos['lead'], f.LEAD) + suffixe).status_code == 404
    assert catalogue.get(_url(photos).replace(photos['devis'], 'DEVIS-AUTRE-FICTIF') + suffixe).status_code == 404


def test_hash_orphelin_meme_depose_ne_donne_aucun_acces(photos, catalogue, session):
    _port()
    with session() as cnx:
        autre = _depot(cnx, b'\x89PNG\r\n\x1a\nAUTRE-PROJET-FICTIF')
    r = catalogue.get(_url(photos) + '/photos/' + autre.rsplit(':', 1)[1])
    assert r.status_code == 404 and 'AUTRE-PROJET' not in r.text


@pytest.mark.parametrize('suffixe', ['?inconnu=secret-fictif', '/photos/' + SHA + '?inconnu=secret-fictif'])
def test_parametres_fermes(photos, catalogue, suffixe):
    _port()
    r = catalogue.get(_url(photos) + suffixe)
    assert r.status_code == 400 and 'secret-fictif' not in r.text


def test_admin_revoque_avant_source_ferme(photos, catalogue, session, monkeypatch):
    p = _port()
    with session() as cnx:
        identite.retirer_role(cnx, f.AUTH.utilisateur, 'admin')
    def interdit(*a, **k):
        raise AssertionError('sources lues avant autorité')
    monkeypatch.setattr(p, '_capture', interdit)
    for suffixe in ('', '/photos/' + SHA):
        assert catalogue.get(_url(photos) + suffixe).status_code == 403


def test_admin_revoque_pendant_rendu_ferme(photos, catalogue, session, monkeypatch):
    p = _port()
    original = p.contenu
    def rendu(*a, **k):
        with session() as cnx:
            identite.retirer_role(cnx, f.AUTH.utilisateur, 'admin')
        return original(*a, **k)
    monkeypatch.setattr(p, 'contenu', rendu)
    assert catalogue.get(_url(photos)).status_code == 403


def test_binaire_corrompu_refuse_sans_octets_partiels(photos, catalogue, session):
    _port()
    with session() as cnx:
        cnx.execute(update(FICHIERS_BLOCS).where(FICHIERS_BLOCS.c.empreinte_sha256 == SHA)
            .values(contenu_base64='INVALIDE-CONTENU-FICTIF'))
    r = catalogue.get(_url(photos) + '/photos/' + SHA)
    assert r.status_code == 503 and 'INVALIDE-CONTENU-FICTIF' not in r.text


def test_publication_wct_modifiee_refuse(photos, catalogue, session):
    _port()
    with session() as cnx:
        wct = {**photos['wct'], 'lead_id': 'LEAD-ETRANGER-FICTIF'}
        cnx.execute(update(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == wct['wct_id'])
            .values(charge=codec.encoder(wct)))
    r = catalogue.get(_url(photos))
    assert r.status_code == 503 and SHA not in r.text


def test_source_modifiee_pendant_rendu_refuse(photos, catalogue, session, monkeypatch):
    p = _port()
    original = p.contenu
    def rendu(*a, **k):
        with session() as cnx:
            cnx.execute(update(REGISTRES).where(REGISTRES.c.departement == 'm04-field-ops')
                .values(cree_le=__import__('datetime').datetime(2031, 1, 1)))
        return original(*a, **k)
    monkeypatch.setattr(p, 'contenu', rendu)
    assert catalogue.get(_url(photos)).status_code == 503


def test_rendu_trop_volumineux_refuse(photos, catalogue, monkeypatch):
    p = _port()
    monkeypatch.setattr(p, 'contenu', lambda *a: 'X' * 131073)
    assert catalogue.get(_url(photos)).status_code == 503


def test_sources_trop_volumineuses_avant_decodage(photos, catalogue, monkeypatch):
    p = _port()
    monkeypatch.setattr(f.port, 'MAX_SOURCES', 0)
    def interdit(*a, **k):
        raise AssertionError('décodage avant borne')
    monkeypatch.setattr(p, 'copier_maillons_avec_metadonnees', interdit)
    assert catalogue.get(_url(photos)).status_code == 503


def test_references_externes_jamais_suivies_ni_affichees(affaire, catalogue, session):
    _port()
    _completion(affaire, session, ['https://exemple.invalid/<script>FICTIF</script>'])
    r = catalogue.get(_url(affaire))
    assert r.status_code == 200 and 'Référence non consultable' in r.text
    assert 'exemple.invalid' not in r.text and '<script>' not in r.text


def test_liste_excessive_refuse_sans_troncature(affaire, catalogue, session):
    _port()
    _completion(affaire, session, [REF] * 21)
    r = catalogue.get(_url(affaire))
    assert r.status_code == 503 and SHA not in r.text


def test_role_revoque_apres_lecture_blob_refuse(photos, catalogue, session, monkeypatch):
    p = _port()
    original = p.fichiers.lire_blob_verifie
    def lecture(*a, **k):
        blob = original(*a, **k)
        with session() as cnx:
            identite.retirer_role(cnx, f.AUTH.utilisateur, 'admin')
        return blob
    monkeypatch.setattr(p.fichiers, 'lire_blob_verifie', lecture)
    r = catalogue.get(_url(photos) + '/photos/' + SHA)
    assert r.status_code == 403 and PNG not in r.content


def test_wct_duplique_ne_devient_pas_une_seconde_galerie(photos, catalogue, session):
    _port()
    from m4_field_ops import registre
    with session():
        reg = registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        maillon = next(m for m in reg.lire() if m.get('wct', {}).get('wct_id') == photos['wct']['wct_id'])
        reg.ajouter({k: v for k, v in maillon.items() if k not in ('ligne_id', 'precedent_ligne_id')})
    r = catalogue.get(_url(photos))
    assert r.status_code == 503 and SHA not in r.text


def test_chaine_m4_corrompue_ferme_sans_diagnostic_brut(photos, catalogue, session):
    _port()
    with session() as cnx:
        cnx.execute(update(REGISTRES).where(REGISTRES.c.departement == 'm04-field-ops')
            .values(maillon='SOURCE-CORROMPUE-FICTIVE'))
    r = catalogue.get(_url(photos))
    assert r.status_code == 503 and 'SOURCE-CORROMPUE-FICTIVE' not in r.text


@pytest.mark.parametrize('fin', ['/fichiers', '/fichiers/', '/fichiers/photos/' + SHA])
def test_recherche_documentaire_interdite_reste_masquee_dans_journal(fin):
    import logging

    from opsys.console.journaux_http import MasquerRecherche
    cible = '/crm/lead/FICTIF/soumissions/DEVIS-FICTIF' + fin + '?nom=secret-document-fictif'
    record = logging.LogRecord('uvicorn.access', 20, '', 1, '%s %s %s %s %s',
        ('127.0.0.1', 'GET', cible, '1.1', 400), None)
    assert MasquerRecherche().filter(record)
    assert 'secret-document-fictif' not in record.getMessage()


@pytest.mark.parametrize('cas', ['decimal_vs_texte', 'nan_concordant'])
def test_publication_typee_et_non_finis_ne_qualifient_pas_une_photo(photos, catalogue, session, cas):
    import json
    from decimal import Decimal

    from m4_field_ops import registre
    from sqlalchemy import select

    _port()
    valeur = Decimal('45.5') if cas == 'decimal_vs_texte' else float('nan')
    wct = {**photos['wct'], 'fix_gps_completion': {'latitude': valeur, 'longitude': -73.5}}

    def brut(m, est_wct=False):
        if cas == 'decimal_vs_texte' or not est_wct:
            return codec.encoder(m)
        # Corruption SQL explicite : les écrivains normaux refusent déjà NaN à l'encodage.
        wc = m.get('wct', m)
        safe = {**wc, 'fix_gps_completion': {**wc['fix_gps_completion'], 'latitude': 0}}
        raw = json.loads(codec.encoder({**m, 'wct': safe} if 'wct' in m else safe))
        raw.get('wct', raw)['fix_gps_completion']['latitude'] = float('nan')
        return json.dumps(raw)

    with session() as cnx:
        rows = cnx.execute(select(REGISTRES).where(REGISTRES.c.departement == 'm04-field-ops',
            REGISTRES.c.registre == 'principal').order_by(REGISTRES.c.rang)).mappings().all()
        chaine = registre.Registre()
        for row in rows:
            m = codec.decoder(row['maillon'])
            if m.get('wct', {}).get('wct_id') == wct['wct_id']:
                m = {**m, 'wct': wct}
            chaine.ajouter({k: v for k, v in m.items() if k not in ('ligne_id', 'precedent_ligne_id')})
            nouveau = chaine.lire()[-1]
            cnx.execute(update(REGISTRES).where(REGISTRES.c.departement == 'm04-field-ops',
                REGISTRES.c.registre == 'principal', REGISTRES.c.rang == row['rang'])
                .values(maillon=brut(nouveau, 'wct' in nouveau)))
        publie = {**wct, 'fix_gps_completion': {**wct['fix_gps_completion'], 'latitude': '45.5'}} \
            if cas == 'decimal_vs_texte' else wct
        cnx.execute(update(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == wct['wct_id'])
            .values(charge=brut(publie, True)))
    r = catalogue.get(_url(photos))
    assert r.status_code == 503 and SHA not in r.text


def _photo_png(cnx, couleur):
    """Vrai PNG RGB 1×1 fictif, avec chunks et CRC pour les nouvelles preuves visuelles."""
    import struct
    import zlib
    def chunk(tag, corps):
        return struct.pack('>I', len(corps)) + tag + corps + struct.pack('>I', zlib.crc32(tag + corps))
    donnees = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(b'\x00' + bytes([couleur, 0, 0]))) + chunk(b'IEND', b''))
    return _depot(cnx, donnees), donnees


@pytest.fixture
def preuves_apres(affaire, session):
    with session() as cnx:
        ref, donnees = _photo_png(cnx, 12)
        signature, _ = _photo_png(cnx, 99)
    dossier = dict(checklist_complete=True, photos_apres=[ref],
        notes='NOTE-PRIVEE-FICTIVE-NE-PAS-AFFICHER', signature=signature)
    wct = _completion(affaire, session, None, dossier=dossier, signature_requise=True)
    assert 'photos' not in wct
    return {**affaire, 'wct': wct, 'ref_apres': ref, 'sha_apres': ref.rsplit(':', 1)[1],
            'signature': signature, 'png_apres': donnees}


def test_preuve_apres_sans_photos_wct_est_consultable_et_sans_dml(preuves_apres, catalogue, session):
    avant = f.m.base._instantane_base(session)
    page = catalogue.get(_url(preuves_apres))
    assert page.status_code == 200, page.text
    assert 'Photo après 1' in page.text and 'preuve conservée' in page.text
    assert 'non conservées' not in page.text
    assert 'completed_pending_review' in page.text
    photo = catalogue.get(_url(preuves_apres) + '/photos/' + preuves_apres['sha_apres'])
    assert photo.status_code == 200 and photo.content == preuves_apres['png_apres']
    assert photo.headers['cache-control'] == 'no-store'
    assert f.m.base._instantane_base(session) == avant


def test_notes_signature_absentes_du_dto_et_signature_interdite(preuves_apres, catalogue, session):
    p = _port()
    page = catalogue.get(_url(preuves_apres))
    with session() as cnx:
        dto = p.lire(cnx, preuves_apres['deps'], f.AUTH, preuves_apres['lead'], preuves_apres['devis'])
    for contenu in (page.text, repr(dto)):
        assert 'NOTE-PRIVEE-FICTIVE-NE-PAS-AFFICHER' not in contenu
        assert preuves_apres['signature'] not in contenu
        assert preuves_apres['signature'].rsplit(':', 1)[1] not in contenu
    r = catalogue.get(_url(preuves_apres) + '/photos/' + preuves_apres['signature'].rsplit(':', 1)[1])
    assert r.status_code == 404


def test_preuve_apres_ne_donne_pas_acces_depuis_un_autre_projet(preuves_apres, catalogue):
    chemin = _url(preuves_apres).replace(preuves_apres['lead'], f.LEAD)
    assert catalogue.get(chemin).status_code == 404
    assert catalogue.get(chemin + '/photos/' + preuves_apres['sha_apres']).status_code == 404


def test_sources_wct_et_preuve_apres_restant_distinctes(affaire, catalogue, session):
    dossier = dict(checklist_complete=True, photos_apres=[REF], notes='', signature=None)
    _completion(affaire, session, [REF], dossier=dossier)
    page = catalogue.get(_url(affaire))
    assert page.status_code == 200, page.text
    assert 'Photo 1 (déclarée)' in page.text and 'Photo après 1' in page.text
    assert page.text.count('/photos/' + SHA) == 2
    assert 'une même image' in page.text


def test_pagination_et_photo_hors_page_autorisees_depuis_meme_source(affaire, catalogue, session):
    with session() as cnx:
        images = [_photo_png(cnx, i) for i in range(25)]
    dossier = dict(checklist_complete=True, photos_apres=[ref for ref, _ in images], notes='', signature=None)
    _completion(affaire, session, None, dossier=dossier)
    avant = f.m.base._instantane_base(session)
    premiere = catalogue.get(_url(affaire))
    assert premiere.status_code == 200, premiere.text
    assert 'Photo après 20' in premiere.text and 'Photo après 21' not in premiere.text
    assert '?decalage=20' in premiere.text
    suivante = catalogue.get(_url(affaire) + '?decalage=20')
    assert suivante.status_code == 200, suivante.text
    assert 'Photo après 21' in suivante.text and 'Photo après 25' in suivante.text
    assert 'Photo après 20' not in suivante.text and 'Page précédente' in suivante.text
    retour = catalogue.get(_url(affaire) + '?decalage=0')
    assert retour.status_code == 200 and 'Photo après 1' in retour.text and 'Photo après 21' not in retour.text
    derniere_ref, derniere_image = images[-1]
    assert derniere_ref.rsplit(':', 1)[1] not in premiere.text
    r = catalogue.get(_url(affaire) + '/photos/' + derniere_ref.rsplit(':', 1)[1])
    assert r.status_code == 200 and r.content == derniere_image
    with session() as cnx:
        p = _port()
        debut = p.lire(cnx, affaire['deps'], f.AUTH, affaire['lead'], affaire['devis'])
        fin = p.lire(cnx, affaire['deps'], f.AUTH, affaire['lead'], affaire['devis'], decalage=20)
    assert debut['source_calculee'] == fin['source_calculee']
    assert debut['nombre_references'] == fin['nombre_references'] == 25
    assert f.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('valeur', ['', '-20', '1', '020', 'true', '20.0', '1000000'])
def test_pagination_non_canonique_refusee(preuves_apres, catalogue, valeur):
    assert catalogue.get(_url(preuves_apres) + '?decalage=' + valeur).status_code == 400


def test_pagination_doublon_et_query_photo_refusees(preuves_apres, catalogue):
    assert catalogue.get(_url(preuves_apres) + '?decalage=0&decalage=0').status_code == 400
    chemin = _url(preuves_apres) + '/photos/' + preuves_apres['sha_apres']
    assert catalogue.get(chemin + '?decalage=0').status_code == 400


def test_page_inexistante_fermee_sans_photo(preuves_apres, catalogue):
    r = catalogue.get(_url(preuves_apres) + '?decalage=20')
    assert r.status_code == 404 and preuves_apres['sha_apres'] not in r.text


def test_borne_native_512_references_est_paginee_sans_export_brut(affaire, catalogue, session):
    dossier = dict(checklist_complete=True, photos_apres=[REF] * 512, notes='', signature=None)
    _completion(affaire, session, None, dossier=dossier)
    premiere = catalogue.get(_url(affaire))
    assert premiere.status_code == 200, premiere.text
    assert premiere.text.count('/photos/' + SHA) == 20
    derniere = catalogue.get(_url(affaire) + '?decalage=500')
    assert derniere.status_code == 200, derniere.text
    assert 'Photo après 512' in derniere.text and 'Photo après 513' not in derniere.text
    assert derniere.text.count('/photos/' + SHA) == 12
    assert '?decalage=520' not in derniere.text
