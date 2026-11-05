"""La couverture calculée par M8 survit à la construction réelle de l'entrepôt."""

from m8_analytics import catalogue_mesures, entrepot_stockage, jeux_fictifs, moteur_mesures

from opsys import stockage


def test_couverture_partielle_calculee_reste_identique_en_courant_et_historique(tmp_path):
    # Le jeu fictif porte des visites pour six des sept jours de la période.
    registres = jeux_fictifs.registres_fictifs(avec_operations=True)
    catalogue = catalogue_mesures.charger()
    mesure = next(m for m in moteur_mesures.lire(registres, catalogue) if m['metric_id'] == 'm8_visites_site')
    assert mesure['statut'] == 'calculee' and mesure['valeur'] == '410'
    assert {k: mesure['couverture'][k] for k in ('etat', 'couverts', 'attendus', 'manquants')} == {
        'etat': 'partielle', 'couverts': 6, 'attendus': 7, 'manquants': 1,
    }
    url = f"sqlite:///{tmp_path / 'm8.db'}"
    stockage.migrer(url)
    try:
        with stockage.moteur(url).begin() as cnx:
            resultat = entrepot_stockage.reconstruire(cnx, registres, catalogue, '2026-10-30T20:00:00-04:00')
            assert resultat['statut'] == 'construit'
            courante = next(m for m in entrepot_stockage.lire_mesures_courantes(cnx)
                            if m['metric_id'] == mesure['metric_id'])
            historique = entrepot_stockage.lire_historique(cnx, mesure['metric_id'])
            assert len(historique) == 1
            for ligne in (courante, historique[0]):
                assert ligne['valeur'] == mesure['valeur']
                assert ligne['couverture'] == mesure['couverture']
                assert ligne['construction_id'] == resultat['construction']['construction_id']

            # La couverture financière a une autre raison et provient d'un autre producteur.
            financier = next(m for m in entrepot_stockage.lire_mesures_courantes(cnx)
                             if m['metric_id'] == 'm8_ecart_depense_pub_comptabilisee_cad')
            assert financier['valeur'] == '113.75'
            assert (financier['couverture']['etat'], financier['couverture']['couverts'],
                    financier['couverture']['attendus']) == ('partielle', 3, 5)
            historique_financier = entrepot_stockage.lire_historique(cnx, financier['metric_id'])
            assert historique_financier[0]['couverture'] == financier['couverture']
    finally:
        stockage.liberer()
