"""Scénario fictif : les visites distinctes ne deviennent pas une durée continue."""
from m4_field_ops import outbox, registre


def _registre_fictif():
    reg = registre.Registre()
    for action, instant in [
        ('arrivee', '2026-11-02T09:00:00-05:00'),
        ('pause_debut', '2026-11-02T10:00:00-05:00'),
        ('pause_fin', '2026-11-02T10:30:00-05:00'),
        ('depart', '2026-11-02T12:00:00-05:00'),
        ('arrivee', '2026-11-06T14:00:00+00:00'),
        ('depart', '2026-11-06T18:00:00+00:00'),
    ]:
        reg.ajouter({'type_entree': 'pointage', 'intervention_id': 'fictif-1',
                     'action': action, 'horodatage': instant, 'fictif': True})
    return reg


def test_refuse_duree_continue_sur_deux_arrivees_sans_ancrage():
    # Oracle métier : lundi 180 - 30 = 150 min, vendredi 240 min, total 390.
    # Sans identité de visite fiable, l'ancien lecteur doit refuser au lieu d'inventer.
    assert outbox.calculer_duree_reelle(_registre_fictif(), 'fictif-1') == (
        None, 'REJ-CONTRAT-INVALIDE')


def test_refuse_deplacement_ambigu_sur_deux_arrivees():
    reg = _registre_fictif()
    reg.ajouter({'type_entree': 'transition_statut', 'intervention_id': 'fictif-1',
                 'statut': 'en_route', 'horodatage': '2026-11-06T13:30:00+00:00',
                 'fictif': True})
    assert outbox.calculer_minutes_deplacement(reg, 'fictif-1') == (
        None, 'REJ-CONTRAT-INVALIDE')


def test_double_depart_historique_reste_calculable():
    reg = registre.Registre()
    for action, instant in [('arrivee', '2026-11-02T09:00:00-05:00'),
                            ('depart', '2026-11-02T11:00:00-05:00'),
                            ('depart', '2026-11-02T11:05:00-05:00')]:
        reg.ajouter({'type_entree': 'pointage', 'intervention_id': 'fictif-1',
                     'action': action, 'horodatage': instant, 'fictif': True})
    assert outbox.calculer_duree_reelle(reg, 'fictif-1') == (125, None)
