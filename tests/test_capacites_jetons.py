from __future__ import annotations

import dataclasses
import datetime as dt

import demo_outils
import pytest
from sqlalchemy import select

from opsys import approbations, contexte, jetons
from opsys.capacites import Capacites
from opsys.stockage.schema import ARTEFACTS


@pytest.fixture
def capacites(departements_demo, session):
    demo_outils.JOURNAL.clear()
    return Capacites(departements_demo, session, limite_sortie=800)


def test_liste_contient_outils_du_departement_et_communs(capacites):
    noms = {o.nom for o in capacites.lister()}
    assert {"m9_additionner", "m9_payer", "opsys_lire_artefact", "opsys_etat_budget"} <= noms


def test_t0_execute_directement(capacites):
    assert capacites.appeler("m9_additionner", {"a": 0.1, "b": 0.2}) == {
        "ok": True, "resultat": {"somme": "0.3"}}


def test_refus_metier_et_outil_inconnu(capacites):
    assert capacites.appeler("m9_refuser_si_negatif", {"valeur": -1})["erreur"] == "refus_metier"
    assert capacites.appeler("m9_inexistant", {})["erreur"] == "outil_inconnu"


def test_t2_en_mode_supervise_passe_par_approbation(capacites, session, departements_demo, nathan):
    reponse = capacites.appeler("m9_envoyer_message", {"destinataire": "client", "texte": "Bonjour"})
    assert reponse["statut"] == "en_attente_approbation"
    assert demo_outils.JOURNAL == []  # rien n'a été envoyé

    index = {o.nom: o for o in capacites.lister()}
    with session() as cnx:
        decision = approbations.decider(cnx, reponse["demande_id"], True, nathan, index, departements_demo)
        assert decision["statut"] == "executee"
        with pytest.raises(ValueError, match="déjà traitée"):
            approbations.decider(cnx, reponse["demande_id"], True, nathan, index, departements_demo)
    assert demo_outils.JOURNAL == [{"a": "client", "texte": "Bonjour"}]


def test_t3_toujours_approuve_meme_en_autonome(capacites, session, departements_demo, nathan):
    with session() as cnx:
        approbations.fixer_mode(cnx, "m09-demo", "autonome", "nathan")
    reponse = capacites.appeler("m9_payer", {"montant": 100})
    assert reponse["statut"] == "en_attente_approbation"
    with session() as cnx:
        refus = approbations.decider(cnx, reponse["demande_id"], False, nathan, {}, departements_demo,
                                     "pas maintenant")
    assert refus == {"id": reponse["demande_id"], "statut": "refusee"}
    assert demo_outils.JOURNAL == []


def test_t2_en_mode_autonome_execute(capacites, session):
    with session() as cnx:
        approbations.fixer_mode(cnx, "m09-demo", "autonome", "nathan")
    reponse = capacites.appeler("m9_envoyer_message", {"destinataire": "c", "texte": "t"})
    assert reponse["ok"] is True and reponse["resultat"]["envoye"] is True


def test_demande_invalide_non_enregistree(capacites, session):
    reponse = capacites.appeler("m9_envoyer_message", {"destinataire": "c"})
    assert reponse["erreur"] == "arguments_invalides"
    with session() as cnx:
        assert approbations.lister(cnx) == []


def test_budget_epuise_bloque_les_actions(capacites, session):
    with session() as cnx:
        jetons.enregistrer_usage(cnx, "m09-demo", "modele-x", {"input_tokens": 900, "output_tokens": 200})
    bloque = capacites.appeler("m9_envoyer_message", {"destinataire": "c", "texte": "t"})
    assert bloque["erreur"] == "budget_epuise"


def test_troncature_et_lecture_artefact(capacites, session):
    reponse = capacites.appeler("m9_gros_rapport", {"lignes": 100})
    assert reponse["tronque"] is True
    assert "opsys_lire_artefact" in reponse["apercu"]
    ident = reponse["apercu"].split("artefact ")[1].split(" ")[0]
    lecteur = Capacites(capacites.departements, session, limite_sortie=800, appelant="m09-demo")
    lecture = lecteur.appeler("opsys_lire_artefact", {"id": ident, "debut": 0, "longueur": 100})
    assert lecture["ok"] is True and len(lecture["resultat"]["contenu"]) == 100


def test_artefact_ne_se_lit_que_depuis_son_origine_authentifiee(departements_demo, session):
    base = departements_demo["m09-demo"]
    departements = {
        **departements_demo,
        "m01-front-office": dataclasses.replace(base, id="m01-front-office"),
        "m02-revenue-crm": dataclasses.replace(base, id="m02-revenue-crm"),
    }
    appelant_reel = Capacites(
        departements, session, filtre={"m09-demo"}, limite_sortie=800, appelant="m01-front-office"
    )
    rapport = appelant_reel.appeler("m9_gros_rapport", {"lignes": 100})
    assert rapport["tronque"] is True
    ident = rapport["apercu"].split("artefact ")[1].split(" ")[0]
    with session() as cnx:
        artefact = cnx.execute(
            select(ARTEFACTS.c.departement, ARTEFACTS.c.origine).where(ARTEFACTS.c.id == ident)
        ).one()
    assert artefact == ("m09-demo", "m01-front-office")

    acces_origine = appelant_reel.appeler(
        "opsys_lire_artefact", {"id": ident, "debut": 0, "longueur": 100}
    )
    acces_autre_departement = Capacites(
        departements, session, filtre={"m09-demo"}, limite_sortie=800, appelant="m02-revenue-crm"
    ).appeler("opsys_lire_artefact", {"id": ident, "debut": 0, "longueur": 100})

    assert acces_origine["ok"] is True
    assert acces_autre_departement["ok"] is False
    assert acces_autre_departement["erreur"] == "refus_metier"
    assert ident not in acces_autre_departement.get("details", "")


def test_artefact_legacy_sans_provenance_refuse_via_capacites(departements_demo, session):
    ident = "legacy0000000001"
    with session() as cnx:
        cnx.execute(ARTEFACTS.insert().values(
            id=ident, cree_le="2026-09-01T00:00:00+00:00", source="ancien", taille=12,
            contenu="contenu secret", departement=None, origine=None,
        ))
    lecteur = Capacites(departements_demo, session, appelant="m09-demo")
    reponse = lecteur.appeler("opsys_lire_artefact", {"id": ident, "debut": 0, "longueur": 100})
    assert reponse["erreur"] == "refus_metier"
    assert "contenu secret" not in str(reponse)
    assert ident not in str(reponse)


def test_normalisation_usage_fournisseurs():
    assert jetons.normaliser_usage({"prompt_tokens": 10, "completion_tokens": 5}) == {
        "tokens_entree": 10, "tokens_sortie": 5, "tokens_cache_lus": 0}
    assert jetons.normaliser_usage({"input_tokens": 7, "output_tokens": 3, "cache_read_tokens": 4}) == {
        "tokens_entree": 7, "tokens_sortie": 3, "tokens_cache_lus": 4}
    assert jetons.normaliser_usage(None)["tokens_entree"] == 0


def test_niveaux_de_budget(departements_demo, session):
    budget = departements_demo["m09-demo"].budget
    jour = dt.date(2026, 9, 28)
    with session() as cnx:
        assert jetons.etat_budget(cnx, "m09-demo", budget, jour)["niveau"] == "ok"
        jetons.enregistrer_usage(cnx, "m09-demo", "m", {"input_tokens": 850}, jour)
        assert jetons.etat_budget(cnx, "m09-demo", budget, jour)["niveau"] == "alerte"
        jetons.enregistrer_usage(cnx, "m09-demo", "m", {"input_tokens": 150}, jour)
        etat = jetons.etat_budget(cnx, "m09-demo", budget, jour)
    assert etat["niveau"] == "epuise"
    assert etat["jour"] == {"utilise": 1000, "limite": 1000, "pct": 100.0}


def test_lecture_artefact_bornes(session):
    with session() as cnx:
        texte = "a" * 10000
        apercu = jetons.tronquer(
            cnx, texte, "test", limite=1000, departement="m09-demo", origine="m09-demo"
        )
        assert len(apercu) < 1200
        ident = apercu.split("artefact ")[1].split(" ")[0]
        with contexte.appeler_en_tant_que("m09-demo"):
            fin = jetons.lire_artefact(cnx, ident, debut=9990, longueur=100)
        assert fin["contenu"] == "a" * 10 and fin["reste"] == 0
        with pytest.raises(ValueError):
            jetons.lire_artefact(cnx, ident, debut=-1)
        with pytest.raises(KeyError):
            jetons.lire_artefact(cnx, "inconnu")


def test_la_sortie_publique_serializee_respecte_la_borne_et_garde_la_reprise(capacites, session):
    import json

    reponse = capacites.appeler('m9_gros_rapport', {'lignes': 100})
    assert len(json.dumps(reponse, ensure_ascii=False)) <= 800
    ident = reponse['apercu'].split('artefact ')[1].split(' ')[0]
    with session() as cnx, contexte.appeler_en_tant_que('m09-demo'):
        recupere = jetons.lire_artefact(cnx, ident, longueur=20000)
    objet = json.loads(recupere['contenu'])
    assert len(objet['resultat']['lignes']) == 100


@pytest.mark.parametrize('limite', [None, True, -1, 1.5])
def test_tronquer_refuse_les_limites_invalides_meme_pour_texte_vide(session, limite):
    with session() as cnx, pytest.raises(ValueError, match='limite invalide'):
        jetons.tronquer(cnx, '', 'fictif', limite=limite)


def test_tronquer_accepte_les_sorties_exactement_a_la_limite(session):
    with session() as cnx:
        assert jetons.tronquer(cnx, '', 'fictif', limite=0) == ''
        assert jetons.tronquer(cnx, 'abc', 'fictif', limite=3) == 'abc'


@pytest.mark.parametrize(('departement', 'origine'), [
    ('m09-demo', None), (None, 'm09-demo'), ('m09-demo', 7), (7, 'm09-demo'),
])
def test_tronquer_ne_conserve_pas_sans_provenance_valide(session, departement, origine):
    with session() as cnx:
        apercu = jetons.tronquer(cnx, 'x' * 1000, 'fictif', limite=200,
                                 departement=departement, origine=origine)
        assert 'reprise non conservée' in apercu
        assert cnx.execute(select(ARTEFACTS.c.id)).first() is None


def test_tronquer_annonce_les_omissions_et_preserve_la_reprise(session):
    import re

    texte = 'A' * 5000 + 'B' * 5000
    with session() as cnx:
        apercu = jetons.tronquer(cnx, texte, 'fictif', limite=800,
                                 departement='m09-demo', origine='m09-demo')
        debut, suite = apercu.split('\n\n[… ', 1)
        indication, fin = suite.split(']\n\n', 1)
        correspondance = re.match(r'(\d+) caractères omis.*debut=(\d+)\)', indication)
        assert correspondance is not None
        omis, offset = map(int, correspondance.groups())
        assert debut and fin and texte.startswith(debut) and texte.endswith(fin)
        assert offset == len(debut) and omis + len(debut) + len(fin) == len(texte)
        assert 'artefact 413355cec3dd5e4f ' in indication
        assert len(apercu) == 800


def test_tronquer_utilise_le_cadre_complet_des_qu_il_tient(session):
    texte = 'x' * 1001
    notice = '\n\n[… 1001 caractères omis — reprise non conservée : origine authentifiée absente]\n\n'
    with session() as cnx:
        apercu = jetons.tronquer(cnx, texte, 'fictif', limite=len(notice))
        assert apercu == notice
        assert jetons.tronquer(cnx, texte, 'fictif', limite=len('reprise non conservée')) == 'reprise non conservée'


@pytest.mark.parametrize('limite', [90, 150, 256, 6000])
def test_enveloppe_json_bornee_meme_pour_caracteres_echappes(departements_demo, session, limite):
    import json
    import re

    cap = Capacites(departements_demo, session, limite_sortie=limite)
    original = {'ok': True, 'resultat': {'texte': ('\\"\n\r\t💼' * 2500)}}
    reponse = cap._tronquer(original, 'm9-test', departement='m09-demo', origine='m09-demo')
    assert len(json.dumps(reponse, ensure_ascii=False)) <= limite
    assert reponse['tronque'] is True
    ident = reponse['apercu'].split('artefact ')[1].split(' ')[0]
    with session() as cnx, contexte.appeler_en_tant_que('m09-demo'):
        premier = jetons.lire_artefact(cnx, ident, longueur=20000)
        dernier = jetons.lire_artefact(cnx, ident, debut=premier['fin'], longueur=20000)
    assert premier['contenu'] + dernier['contenu'] == json.dumps(original, ensure_ascii=False)
    assert dernier['reste'] == 0
    offset = re.search(r'debut=(\d+)', reponse['apercu'])
    if offset:
        assert reponse['apercu'].startswith(premier['contenu'][:int(offset.group(1))])


def test_petit_quota_ne_fait_pas_croire_que_l_operation_a_echoue(departements_demo, session):
    import json

    cap = Capacites(departements_demo, session, limite_sortie=40)
    reponse = cap._tronquer({'ok': True, 'resultat': 'x' * 1000}, 'm9-test',
                            departement='m09-demo', origine='m09-demo')
    assert reponse == {'ok': False, 'issue': 'inconnue'}
    assert len(json.dumps(reponse, ensure_ascii=False)) <= 40
    with session() as cnx:
        assert cnx.execute(select(ARTEFACTS.c.id)).first() is None


def test_quota_trop_petit_leve_issue_inconnue_sans_artefact_orphelin(departements_demo, session):
    cap = Capacites(departements_demo, session, limite_sortie=1)
    with pytest.raises(ValueError, match='ISSUE-INCONNUE'):
        cap._tronquer({'ok': True, 'resultat': 'x' * 1000}, 'm9-test',
                      departement='m09-demo', origine='m09-demo')
    with session() as cnx:
        assert cnx.execute(select(ARTEFACTS.c.id)).first() is None


def test_absence_origine_ne_cree_jamais_d_artefact(departements_demo, session):
    import json

    cap = Capacites(departements_demo, session, limite_sortie=200)
    reponse = cap._tronquer({'ok': True, 'resultat': 'x' * 1000}, 'm9-test')
    assert len(json.dumps(reponse, ensure_ascii=False)) <= 200
    assert 'reprise non conservée' in reponse['apercu']
    with session() as cnx:
        assert cnx.execute(select(ARTEFACTS.c.id)).first() is None


def test_vrai_copilote_m8_cinq_mesures_via_capacites_reste_borne(departements_demo, session):
    import json

    from m8_analytics import jeux_fictifs
    from m8_analytics import outils as outils_m8
    from m8_analytics.registre import RegistreSnapshots

    from opsys.outils import executer_atomique

    registres = jeux_fictifs.registres_fictifs(avec_operations=True)
    outils = outils_m8.outils(
        registre_cible=RegistreSnapshots(), definitions_cible=[], faits_cible=registres['chantier'],
        faits_entonnoir_cible=registres['entonnoir'], faits_contenus_cible=registres['contenus'],
        faits_cash_libre_cible=registres['cash_libre'], faits_operations_cible=registres['operations'],
        historique_sante_cible=[], publications_cible=[],
    )
    constructeur = next(o for o in outils if o.nom == 'm8_construire_entrepot')
    for leads, heure in ((20, '09'), (21, '10')):
        nouveaux = jeux_fictifs.registres_fictifs(leads=leads, avec_operations=True)
        for nom in registres:
            registres[nom][:] = nouveaux[nom]
        assert executer_atomique(constructeur, {'maintenant': f'2026-10-30T{heure}:00:00Z'})['ok']
    outil = next(o for o in outils if o.nom == 'm8_repondre_question')
    cap = Capacites(departements_demo, session, limite_sortie=6000, appelant='m09-demo')
    cap.index[outil.nom] = (departements_demo['m09-demo'], outil)
    reponse = cap.appeler('m8_repondre_question', {
        'question': ('Évolution des leads reçus, des leads qualifiés, des devis envoyés, '
                     'des devis acceptés et des devis sans réponse'),
        'maintenant': '2026-10-30T20:00:00-04:00',
    })
    assert reponse['ok'] is True
    assert len(json.dumps(reponse, ensure_ascii=False)) <= 6000
    assert reponse['tronque'] is True
    ident = reponse['apercu'].split('artefact ')[1].split(' ')[0]
    morceaux, debut = [], 0
    while True:
        reprise = cap.appeler('opsys_lire_artefact', {'id': ident, 'debut': debut, 'longueur': 1000})
        assert reprise['ok'] is True
        fragment = reprise['resultat']
        morceaux.append(fragment['contenu'])
        debut = fragment['fin']
        if not fragment['reste']:
            break
    complet = json.loads(''.join(morceaux))
    assert len(complet['resultat']['mesures']) == 5


def test_quota_minuscule_profil_runtime_rollback_parent_et_permissions(departements_demo, session, nathan):
    from opsys import agents

    profil = {
        'id': 'profil-bornes-fictif', 'departement': 'm09-demo', 'responsabilite': 'Rapport fictif',
        'palier_modele': 'standard', 'outils': ['m9_gros_rapport'], 'budget_jour': 1000, 'budget_mois': 10000,
        'limite_tours': 4, 'limite_reessais': 1, 'limite_concurrence': 1, 'declencheurs': [{'type': 'manuel'}],
    }
    with session() as cnx:
        agents.creer(cnx, departements_demo, profil, par=nathan, mutation_id='profil-bornes-create-fictif')
        actif = agents.definir_actif(cnx, profil['id'], departements_demo, True, par=nathan,
                                    mutation_id='profil-bornes-active-fictif', revision_attendue=1)
    cap = Capacites(departements_demo, session, limite_sortie=1, appelant='m09-demo')
    args = dict(profile_id=profil['id'], profile_revision=actif['revision'], server='opsys_m9')
    interdit = cap.appeler_profil_runtime('m9_additionner', {'a': 1, 'b': 2}, None, None, **args)
    assert interdit['erreur'] == 'admission_profil_refusee'
    with pytest.raises(ValueError, match='ISSUE-INCONNUE'), session():
        cap.appeler_profil_runtime('m9_gros_rapport', {'lignes': 100}, None, None, **args)
    with session() as cnx:
        assert cnx.execute(select(ARTEFACTS.c.id)).first() is None
    cap_40 = Capacites(departements_demo, session, limite_sortie=40, appelant='m09-demo')
    issue = cap_40.appeler_profil_runtime('m9_gros_rapport', {'lignes': 100}, None, None, **args)
    assert issue == {'ok': False, 'issue': 'inconnue'}
    with session() as cnx:
        assert cnx.execute(select(ARTEFACTS.c.id)).first() is None
    cap = Capacites(departements_demo, session, limite_sortie=90, appelant='m09-demo')
    reponse = cap.appeler_profil_runtime('m9_gros_rapport', {'lignes': 100}, None, None, **args)
    assert reponse['tronque']
    ident = reponse['apercu'].split('artefact ')[1].split(' ')[0]
    lecteur = Capacites(departements_demo, session, limite_sortie=800, appelant='m09-demo')
    lecture = lecteur.appeler('opsys_lire_artefact', {'id': ident, 'debut': 0, 'longueur': 100})
    assert lecture['ok'] and lecture['resultat']['contenu']
    with session() as cnx, contexte.appeler_en_tant_que('m01-front-office'), pytest.raises(KeyError):
        jetons.lire_artefact(cnx, ident)


def test_hermes_sans_origine_ne_cree_pas_de_reprise(departements_demo, session):
    from opsys.hermes_plugin import PluginOpsys

    plugin = PluginOpsys('m09-demo', departements_demo, cnx_factory=session, limite_sortie=40)
    apercu = plugin.transform_tool_result('m9_gros_rapport', 'x' * 1000)
    assert len(apercu) <= 40 and 'reprise non conservée' in apercu
    with session() as cnx:
        assert cnx.execute(select(ARTEFACTS.c.id)).first() is None


def test_hermes_quota_minuscule_rollback_parent_sans_reprise_exterieure(departements_demo, session):
    from opsys.hermes_plugin import PluginOpsys

    plugin = PluginOpsys('m09-demo', departements_demo, cnx_factory=session, limite_sortie=1)
    with pytest.raises(ValueError, match='ISSUE-INCONNUE'), session(), contexte.appeler_en_tant_que('m09-demo'):
        plugin.transform_tool_result('m9_gros_rapport', 'x' * 1000)
    with session() as cnx:
        assert cnx.execute(select(ARTEFACTS.c.id)).first() is None
    plugin = PluginOpsys('m09-demo', departements_demo, cnx_factory=session, limite_sortie=100)
    with contexte.appeler_en_tant_que('m09-demo'):
        apercu = plugin.transform_tool_result('m9_gros_rapport', 'x' * 1000)
    assert len(apercu) <= 100
    ident = apercu.split('artefact ')[1].split(' ')[0]
    with session() as cnx, contexte.appeler_en_tant_que('m09-demo'):
        assert jetons.lire_artefact(cnx, ident)['contenu'] == 'x' * 1000
    with session() as cnx, contexte.appeler_en_tant_que('m01-front-office'), pytest.raises(KeyError):
        jetons.lire_artefact(cnx, ident)


def test_quota_impossible_ne_promet_pas_annulation_ni_rejeu(departements_demo, session):
    demo_outils.JOURNAL.clear()
    cap = Capacites(departements_demo, session, limite_sortie=1, appelant='m09-demo')
    with pytest.raises(ValueError, match='ISSUE-INCONNUE'):
        cap.appeler('m9_pointer', {'appareil': 'appareil-fictif'})
    # L'effet externe fictif est déjà intervenu : ni échec ni annulation ne sont déduits de l'erreur de sortie.
    assert demo_outils.JOURNAL == [{'pointage': 'appareil-fictif'}]
