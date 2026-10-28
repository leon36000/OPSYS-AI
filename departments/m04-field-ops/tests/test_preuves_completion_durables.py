"""fictif: true — preuves futures dans le seul maillon de complétion, jamais dans le WCT diffusé."""
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops import encodage, etats, outbox, outils, registre
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True


def _charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, Path(__file__).with_name(fichier))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


f = _charger('preuves_durables_fichiers_fixture', 'test_outils_fichiers.py')
b = _charger('preuves_durables_outbox_fixture', 'test_outbox.py')


def _maillons():
    with stockage.transaction():
        return list(stockage.maillons('m04-field-ops', 'principal'))


def _commande(i_id, photo):
    return dict(intervention_id=i_id, horodatage=b.H_COMPLETION,
        preuves_completion=dict(checklist_complete=True, photos_apres=[photo],
            notes='Note FICTIVE privée', signature=photo),
        signature_requise=True)


def test_vrai_outil_conserve_dossier_et_reconnexion_sans_diffusion(base_durable, deposer_photo_test):
    par_nom = {o.nom: o for o in outils.outils()}
    ident = f._mener_a_sur_site(par_nom, 'L-PREUVES-DURABLES-FICTIF')
    photo = deposer_photo_test(par_nom)
    args = _commande(ident, photo)
    avant = len(_maillons())
    r = executer_atomique(par_nom['m4_completer_intervention'], args)
    assert r['ok'] and r['resultat']['accepte'], r
    stockage.liberer()
    lignes = _maillons()
    assert len(lignes) == avant + 1
    archive = lignes[-1].get('preuves_completion')
    assert archive == dict(version_schema=1, signature_requise=True, preuves=args['preuves_completion'])
    chaine = registre.Registre(lignes)
    chaine.assert_chaine()
    assert outbox.verifier_invariants_outbox(chaine) == (True, '')
    assert 'preuves_completion' not in lignes[-1]['wct']
    assert 'Note FICTIVE privée' not in codec.encoder(outbox.lire_outbox(chaine))
    with stockage.transaction() as cnx:
        rows = cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == 'm4.travaux_termines')).all()
    assert len(rows) == 1
    evenement = codec.decoder(rows[0].charge)
    assert 'preuves_completion' not in evenement and 'photos_apres' not in evenement
    assert 'Note FICTIVE privée' not in rows[0].charge


def test_echec_publication_annule_archive_et_completion(base_durable, deposer_photo_test, monkeypatch):
    par_nom = {o.nom: o for o in outils.outils()}
    ident = f._mener_a_sur_site(par_nom, 'L-PREUVES-ROLLBACK-FICTIF')
    photo = deposer_photo_test(par_nom)
    avant = _maillons()
    original = evenements.publier
    def echec(typ, *a, **k):
        if typ == 'm4.travaux_termines':
            raise OSError('publication fictive interrompue')
        return original(typ, *a, **k)
    monkeypatch.setattr(evenements, 'publier', echec)
    with pytest.raises(OSError, match='publication fictive'):
        executer_atomique(par_nom['m4_completer_intervention'], _commande(ident, photo))
    assert _maillons() == avant


def _preuves():
    return dict(checklist_complete=True, photos_apres=['photo-declaree-fictive'], notes='Note FICTIVE', signature=None)


def test_snapshot_avant_hash_et_ecriture_reste_isole(monkeypatch):
    reg, ident = b._intervention_sur_site_avec_pointages()
    dossier = _preuves()
    original = reg.ajouter
    def ajouter(m):
        dossier['photos_apres'].append('ajout-tardif-fictif')
        dossier['notes'] = 'note-modifiee-fictive'
        return original(m)
    monkeypatch.setattr(reg, 'ajouter', ajouter)
    recu, verdict = outbox.completer_intervention(ident, b.H_COMPLETION, reg, ecart_detecte=False,
        preuves_completion=dossier, signature_requise=False)
    assert recu and verdict is None
    archive = reg.lire()[-1]['preuves_completion']
    assert archive['preuves'] == _preuves()
    assert outbox.verifier_invariants_outbox(reg) == (True, '')


@pytest.mark.parametrize('cas', ['sans_signature_requise', 'signature_entier', 'notes_excessives', 'photos_excessives',
                                 'notes_canoniques_excessives', 'unicode_invalide'])
def test_archive_inadmissible_refuse_avant_ajout(cas):
    reg, ident = b._intervention_sur_site_avec_pointages()
    dossier = _preuves()
    kw = dict(preuves_completion=dossier, signature_requise=False)
    if cas == 'sans_signature_requise':
        kw.pop('signature_requise')
    elif cas == 'signature_entier':
        kw['signature_requise'] = 0
    elif cas == 'notes_excessives':
        dossier['notes'] = 'X' * 65537
    elif cas == 'photos_excessives':
        dossier['photos_apres'] = ['photo-fictive'] * 513
    elif cas == 'unicode_invalide':
        dossier['notes'] = '\ud800'
    else:
        dossier['notes'] = '€' * 12000
    avant = reg.lire()
    recu, verdict = outbox.completer_intervention(ident, b.H_COMPLETION, reg, ecart_detecte=False, **kw)
    assert recu is None and verdict['code'] == 'REJ-CONTRAT-INVALIDE'
    assert reg.lire() == avant


def test_anciens_appels_et_hashes_sans_archive_restent_valides():
    reg, ident = b._intervention_sur_site_avec_pointages()
    recu, verdict = outbox.completer_intervention(ident, b.H_COMPLETION, reg, ecart_detecte=False)
    assert recu and verdict is None
    maillon = reg.lire()[-1]
    assert 'preuves_completion' not in maillon
    assert maillon['wct']['hash_maillon'] == encodage.empreinte({k: v for k, v in maillon.items()
        if k not in ('ligne_id', 'precedent_ligne_id', 'wct')})
    assert outbox.verifier_invariants_outbox(reg) == (True, '')


@pytest.mark.parametrize('archive', [None, {'version_schema': True, 'signature_requise': False, 'preuves': _preuves()}])
def test_invariants_refusent_bloc_invalide_meme_apres_rehash(archive):
    reg, ident = b._intervention_sur_site_avec_pointages()
    recu, verdict = outbox.completer_intervention(ident, b.H_COMPLETION, reg, ecart_detecte=False)
    assert recu and verdict is None
    entrees = reg.lire()
    nouveau = registre.Registre()
    for entree in entrees:
        m = {k: v for k, v in entree.items() if k not in ('ligne_id', 'precedent_ligne_id')}
        if 'wct' in m:
            m['preuves_completion'] = archive
            m['wct']['hash_maillon'] = encodage.empreinte({k: v for k, v in m.items() if k != 'wct'})
        nouveau.ajouter(m)
    nouveau.assert_chaine()
    assert outbox.verifier_invariants_outbox(nouveau)[0] is False


def test_confirmation_ne_devient_pas_second_chemin_archive():
    reg, ident = b._intervention_sur_site_avec_pointages()
    recu, verdict = outbox.completer_intervention(ident, b.H_COMPLETION, reg,
        ecart_detecte=False, verification_en_attente=True)
    assert recu and verdict is None
    # Maillon volontairement invalide, pour éprouver le lecteur d'invariants.
    reg.ajouter(dict(type_entree=etats.TYPE_TRANSITION, intervention_id=ident,
        statut='completed_verified', statut_precedent='completed_pending_review',
        horodatage='2025-06-02T11:40:00+00:00', preuves_completion=dict(
            version_schema=1, signature_requise=False, preuves=_preuves())))
    assert outbox.verifier_invariants_outbox(reg)[0] is False


def test_mutation_appelant_apres_verification_cas_ne_change_pas_archive(
    base_durable, deposer_photo_test, monkeypatch,
):
    par_nom = {o.nom: o for o in outils.outils()}
    ident = f._mener_a_sur_site(par_nom, 'L-PREUVES-SNAPSHOT-CAS-FICTIF')
    photo = deposer_photo_test(par_nom)
    args = _commande(ident, photo)
    verifier = outils._verifier_preuves_fichiers
    def verification(preuves, signature_requise):
        verdict = verifier(preuves, signature_requise)
        args['preuves_completion']['photos_apres'][0] = 'fichier:sha256:' + '0' * 64
        return verdict
    monkeypatch.setattr(outils, '_verifier_preuves_fichiers', verification)
    r = executer_atomique(par_nom['m4_completer_intervention'], args)
    assert r['ok'] and r['resultat']['accepte'], r
    assert _maillons()[-1]['preuves_completion']['preuves']['photos_apres'] == [photo]


def test_borne_archive_outil_avant_toute_verification_sql_cas(base_durable, deposer_photo_test, monkeypatch):
    par_nom = {o.nom: o for o in outils.outils()}
    ident = f._mener_a_sur_site(par_nom, 'L-PREUVES-BORNE-CAS-FICTIF')
    photo = deposer_photo_test(par_nom)
    args = _commande(ident, photo)
    args['preuves_completion']['photos_apres'] = [photo] * 513
    appels = []
    verifier = outils._verifier_preuves_fichiers
    def verification(*a, **k):
        appels.append(1)
        return verifier(*a, **k)
    monkeypatch.setattr(outils, '_verifier_preuves_fichiers', verification)
    avant = _maillons()
    r = executer_atomique(par_nom['m4_completer_intervention'], args)
    assert r['ok'] and r['resultat']['accepte'] is False
    assert appels == []
    assert _maillons() == avant
