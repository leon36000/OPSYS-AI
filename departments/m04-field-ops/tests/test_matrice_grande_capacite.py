"""fictif: true — capacité globale distincte du transport OSRM, sans réseau réel."""
import json
import time

from m4_field_ops import distances, distances_osrm

FICTIF = True
PARAMETRES = dict(facteur_detour_milliemes=1300, vitesse_moyenne_kmh=50, marge_par_trajet_secondes=600)


def _points(nombre):
    return [dict(id=f'point-fictif-{i:03d}', latitude_microdeg=45000000+i*10,
                 longitude_microdeg=-73000000-i*10) for i in range(nombre)]


def test_202_points_globaux_acceptes_pour_200_chantiers_et_depots():
    points, verdict = distances.valider_points(_points(202))
    assert verdict is None, verdict
    assert len(points) == 202


def test_transport_osrm_202_points_refuse_avant_toute_requete(monkeypatch):
    fournisseur = distances_osrm.FournisseurOsrm('http://127.0.0.1:5000', 'quebec-fictif-20300603')

    def interdit(*args, **kwargs):
        raise AssertionError('aucune requête HTTP autorisée pour cette taille')

    monkeypatch.setattr(fournisseur, '_requete', interdit)
    resultat, verdict = fournisseur.trajets(_points(202))
    assert resultat is None and verdict['code'] == distances.CODE_FOURNISSEUR_INDISPONIBLE
    assert '100' in verdict['detail'] and 'blocs' in verdict['detail']



def test_frontiere_256_complete_et_257_refusee_sans_fournisseur(record_testsuite_property):
    debut = time.perf_counter()
    matrice, verdict = distances.matrice_palier0(_points(256), PARAMETRES)
    assert verdict is None and distances.MAX_POINTS == 256
    assert distances.verifier_matrice(matrice) == (True, '')
    assert len(matrice['ids']) == 256 and matrice['mode_bride'] is True
    assert all(len(ligne) == 256 for ligne in matrice['metres'])
    assert matrice['metres'][0][-1] > 0 and matrice['secondes'][0][-1] > 600
    assert all(matrice['metres'][i][i] == matrice['secondes'][i][i] == 0 for i in range(256))

    class Jamais:
        def descripteur(self):
            raise AssertionError('fournisseur ne doit pas être consulté après entrée trop grande')

    refusee, verdict = distances.obtenir_matrice(_points(257), PARAMETRES, Jamais())
    assert refusee is None and verdict['code'] == 'REJ-CONTRAT-INVALIDE'
    record_testsuite_property('matrice256', json.dumps(dict(points=256, cellules_entieres=2*256*256,
        secondes=time.perf_counter()-debut, mode='haversine_detour', transport_reel=False)))


def test_repli_global_202_marque_sans_melange_et_sans_reseau(monkeypatch):
    fournisseur = distances_osrm.FournisseurOsrm('http://127.0.0.1:5000', 'quebec-fictif-20300603')

    def interdit(*args, **kwargs):
        raise AssertionError('transport par blocs absent, aucune requête permise')

    monkeypatch.setattr(fournisseur, '_requete', interdit)
    points = _points(202)
    matrice, verdict = distances.obtenir_matrice(points, PARAMETRES, fournisseur)
    directe, _ = distances.matrice_palier0(points, PARAMETRES)
    assert verdict is None and matrice['mode_bride'] is True
    assert matrice['repli']['code'] == distances.CODE_FOURNISSEUR_INDISPONIBLE
    assert matrice['metres'] == directe['metres'] and matrice['secondes'] == directe['secondes']
    assert matrice['empreinte'] != directe['empreinte']
    assert distances.verifier_matrice(matrice) == (True, '')


def test_transport_100_garde_chemin_unique_et_asymetrie_via_seam(monkeypatch):
    fournisseur = distances_osrm.FournisseurOsrm('http://127.0.0.1:5000', 'quebec-fictif-20300603')
    points = _points(100)
    metres = [[0 if i == j else 100*i+j+1 for j in range(100)] for i in range(100)]
    secondes = [[0 if i == j else 10*i+j+1 for j in range(100)] for i in range(100)]
    urls = []

    def reponse(url):
        urls.append(url)
        return json.dumps(dict(code='Ok', distances=metres, durations=secondes)).encode(), None

    monkeypatch.setattr(fournisseur, '_requete', reponse)
    resultat, verdict = fournisseur.trajets(points)
    assert verdict is None and resultat == {'metres': metres, 'secondes': secondes}
    assert resultat['metres'][0][1] != resultat['metres'][1][0]
    assert len(urls) == 1 and urls[0].count(';') == 99
    assert urls[0].endswith('?annotations=duration,distance') and 'fallback_speed' not in urls[0]
