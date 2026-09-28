import json
import unicodedata
from datetime import date, timedelta
import yaml


def _normalize(s: str) -> str:
    """Normalise une chaîne : minuscules, sans accent."""
    nfkd = unicodedata.normalize('NFKD', s)
    return "".join(c for c in nfkd if unicodedata.category(c) != 'Mn').lower()


def charger_et_valider_fixtures(chemin_matomo: str, chemin_crm: str):
    """Charge les fixtures Matomo et CRM, valide le marqueur fictif:true.

    Lève ValueError si fictif est absent ou faux, ou si le YAML est invalide.
    Retourne (visites, leads).
    """
    try:
        with open(chemin_matomo, 'r', encoding='utf-8') as f:
            matomo_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        msg = f"parse_error: {e}"
        if hasattr(e, 'problem_mark') and e.problem_mark is not None:
            mark = e.problem_mark
            msg += f" at line {mark.line+1}, column {mark.column+1}"
        raise ValueError(msg) from e

    if not isinstance(matomo_data, dict) or matomo_data.get('fictif') is not True:
        raise ValueError("Le fichier Matomo doit avoir 'fictif: true'")
    visites = matomo_data.get('visites', [])

    try:
        with open(chemin_crm, 'r', encoding='utf-8') as f:
            crm_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        msg = f"parse_error: {e}"
        if hasattr(e, 'problem_mark') and e.problem_mark is not None:
            mark = e.problem_mark
            msg += f" at line {mark.line+1}, column {mark.column+1}"
        raise ValueError(msg) from e

    if not isinstance(crm_data, dict) or crm_data.get('fictif') is not True:
        raise ValueError("Le fichier CRM doit avoir 'fictif: true'")
    leads = crm_data.get('leads', [])

    return visites, leads


def attribuer(visites, leads, fenetre_jours=30):
    """Calcule le rapport d'attribution à partir des visites et des leads.

    Retourne un dict avec par_canal, par_campagne, non_attribuables et divergences.
    """
    # Indexation des visites par visitor_id
    visites_par_visitor = {}
    for v in visites:
        vid = v.get('visitor_id')
        if vid:
            visites_par_visitor.setdefault(vid, []).append(v)

    # Comptage du nombre total de visites par canal et par campagne
    visites_par_canal = {}
    visites_par_campagne = {}
    for v in visites:
        src = v['utm_source']
        camp = v['utm_campaign']
        visites_par_canal[src] = visites_par_canal.get(src, 0) + 1
        visites_par_campagne[camp] = visites_par_campagne.get(camp, 0) + 1

    # Structures d'agrégation
    par_canal = {}
    par_campagne = {}
    non_attribuables = 0
    divergences = []

    def _to_date(iso):
        # PyYAML parse déjà les dates ISO en objets date — accepter les deux formes.
        if isinstance(iso, date):
            return iso
        return date.fromisoformat(str(iso)[:10])

    for lead in leads:
        lid = lead.get('lead_id')
        lead_date_str = lead.get('date')
        source_declaree = lead.get('source_declaree', '')
        visitor = lead.get('visitor_id')

        if not lid or not lead_date_str:
            # Malformé, mais on ne l'ignore pas : on le compte non attribuable
            non_attribuables += 1
            continue

        lead_date = _to_date(lead_date_str)

        if not visitor or visitor not in visites_par_visitor:
            non_attribuables += 1
            continue

        seuil = lead_date - timedelta(days=fenetre_jours)
        visites_candidates = []
        for v in visites_par_visitor[visitor]:
            vdate = _to_date(v['date'])
            if seuil <= vdate <= lead_date:
                visites_candidates.append(
                    (vdate, v['utm_source'], v['utm_medium'], v['utm_campaign'], v['landing'], v)
                )

        if not visites_candidates:
            non_attribuables += 1
            continue

        # Tri déterministe : date croissante, puis champs lexicographiques
        visites_candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4]))
        premiere_visite = visites_candidates[0][5]
        derniere_visite = visites_candidates[-1][5]

        # Première touche
        src_prem = premiere_visite['utm_source']
        camp_prem = premiere_visite['utm_campaign']
        par_canal.setdefault(src_prem, {
            'visites': visites_par_canal.get(src_prem, 0),
            'leads_premiere_touche': 0,
            'leads_derniere_touche': 0
        })
        par_canal[src_prem]['leads_premiere_touche'] += 1
        par_campagne.setdefault(camp_prem, {
            'visites': visites_par_campagne.get(camp_prem, 0),
            'leads_premiere_touche': 0,
            'leads_derniere_touche': 0
        })
        par_campagne[camp_prem]['leads_premiere_touche'] += 1

        # Dernière touche
        src_dern = derniere_visite['utm_source']
        camp_dern = derniere_visite['utm_campaign']
        par_canal.setdefault(src_dern, {
            'visites': visites_par_canal.get(src_dern, 0),
            'leads_premiere_touche': 0,
            'leads_derniere_touche': 0
        })
        par_canal[src_dern]['leads_derniere_touche'] += 1
        par_campagne.setdefault(camp_dern, {
            'visites': visites_par_campagne.get(camp_dern, 0),
            'leads_premiere_touche': 0,
            'leads_derniere_touche': 0
        })
        par_campagne[camp_dern]['leads_derniere_touche'] += 1

        # Divergence : source_declaree normalisée ≠ utm_source de la dernière touche
        src_dern_norm = src_dern.lower()
        lead_norm = _normalize(source_declaree) if source_declaree else ''
        if lead_norm != src_dern_norm:
            divergences.append({
                'lead_id': lid,
                'source_declaree': source_declaree,
                'utm_source': src_dern,
                'utm_campaign': camp_dern
            })

    # Ajouter les canaux/campagnes sans lead (pour le comptage de visites)
    for src in visites_par_canal:
        if src not in par_canal:
            par_canal[src] = {
                'visites': visites_par_canal[src],
                'leads_premiere_touche': 0,
                'leads_derniere_touche': 0
            }
    for camp in visites_par_campagne:
        if camp not in par_campagne:
            par_campagne[camp] = {
                'visites': visites_par_campagne[camp],
                'leads_premiere_touche': 0,
                'leads_derniere_touche': 0
            }

    # Tris lexicographiques stables
    par_canal = dict(sorted(par_canal.items()))
    par_campagne = dict(sorted(par_campagne.items()))
    divergences.sort(key=lambda d: d['lead_id'])

    return {
        'par_canal': par_canal,
        'par_campagne': par_campagne,
        'non_attribuables': non_attribuables,
        'divergences': divergences
    }


def rapport_vers_json(rapport):
    """Sérialise le rapport d'attribution en JSON deterministe."""
    return json.dumps(rapport, sort_keys=True, ensure_ascii=False)
