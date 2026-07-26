import json
import hashlib
from pathlib import Path
import yaml

def _get_project_root():
    return Path(__file__).resolve().parents[2]

def _hash_json_dict(data):
    """Retourne le sha256 hex d'un dict sérialisé de manière déterministe."""
    serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()

def valider_mapping(mapping):
    """Lève ValueError si le mapping est invalide."""
    if not isinstance(mapping, dict) or 'mappings' not in mapping:
        raise ValueError("mapping invalide : clé 'mappings' manquante")
    for m in mapping['mappings']:
        required = {'fenetre_id', 'plateforme_ads', 'utm_campaigns'}
        if not required.issubset(m.keys()):
            raise ValueError("entrée mapping invalide")

def consolider_roi(rapport_attribution, rapport_ads, mapping, calendrier, date_reference):
    """Consolidation déterministe des rapports d'attribution et ads."""
    valider_mapping(mapping)

    # ------------------------------------------------------------------
    # 1. Par canal
    # ------------------------------------------------------------------
    canaux_attr = rapport_attribution.get('par_canal', [])
    # Deux dialectes acceptés : S014 réel PLAT (campagnes=[{plateforme,...}]) et
    # forme imbriquée (plateformes=[{plateforme, campagnes=[...]}]) des rapports composés.
    campagnes_ads = list(rapport_ads.get('campagnes', []))
    for pf in rapport_ads.get('plateformes', []):
        for c in pf.get('campagnes', []):
            cc = dict(c)
            cc.setdefault('plateforme', pf.get('plateforme'))
            campagnes_ads.append(cc)
    campagnes_par_plateforme = {}
    for c in campagnes_ads:
        campagnes_par_plateforme.setdefault(c.get('plateforme'), []).append(c)

    # Index mapping : fenetre_id -> {plateforme, set(campagnes)}
    mapping_par_fenetre = {}
    for m in mapping.get('mappings', []):
        fid = m['fenetre_id']
        camps = set(m['utm_campaigns'])
        if fid not in mapping_par_fenetre:
            mapping_par_fenetre[fid] = {'plateforme': m['plateforme_ads'], 'campagnes': camps}
        else:
            mapping_par_fenetre[fid]['campagnes'].update(camps)

    canaux_result = []
    # par_canal du rapport S013 est un dict {canal: comptes} — normaliser en items
    if isinstance(canaux_attr, dict):
        canaux_iter = [{'canal': k, **(v or {})} for k, v in sorted(canaux_attr.items())]
    else:
        canaux_iter = canaux_attr
    for canal_attr in canaux_iter:
        canal = canal_attr.get('canal')
        leads = canal_attr.get('leads_derniere_touche', 0)
        campagnes_plateforme = campagnes_par_plateforme.get(canal, [])

        cout_total = 0.0
        nb_campagnes_joignables = 0
        for camp in campagnes_plateforme:
            nom_camp = camp.get('campagne')
            fenetre_id = camp.get('fenetre_id')
            # Vérifier que la campagne est bien listée dans le mapping pour cette fenêtre
            if (fenetre_id in mapping_par_fenetre and
                nom_camp in mapping_par_fenetre[fenetre_id]['campagnes']):
                cout_total += camp.get('cout', 0.0)
                nb_campagnes_joignables += 1

        if leads == 0:
            canaux_result.append({
                'canal': canal,
                'leads_derniere_touche': leads,
                'cout_ads': cout_total,
                'donnees_insuffisantes': {'raison': 'zero_leads'}
            })
        elif nb_campagnes_joignables == 0:
            # Aucune campagne joignable
            if campagnes_plateforme:
                raison = 'mapping_absent'
            else:
                raison = 'cout_indisponible'
            canaux_result.append({
                'canal': canal,
                'leads_derniere_touche': leads,
                'cout_ads': 0.0,
                'donnees_insuffisantes': {'raison': raison}
            })
        else:
            cpl = cout_total / leads
            canaux_result.append({
                'canal': canal,
                'leads_derniere_touche': leads,
                'cout_ads': cout_total,
                'cout_par_lead': cpl
            })

    # ------------------------------------------------------------------
    # 2. Par fenêtre
    # ------------------------------------------------------------------
    fenetres_calendrier = calendrier.get('fenetres_marketing') or calendrier.get('fenetres', [])
    fenetres_result = []
    for f in fenetres_calendrier:
        fid = f.get('id') or f.get('fenetre_id')  # réel: 'id' ; festif: 'fenetre_id'
        nb_campagnes = 0
        if fid in mapping_par_fenetre:
            plateforme_f = mapping_par_fenetre[fid]['plateforme']
            camps_mappees = mapping_par_fenetre[fid]['campagnes']
            campagnes_f = campagnes_par_plateforme.get(plateforme_f, [])
            # Ne compter que les campagnes réelles dont l'id est dans camps_mappees
            # et qui sont bien positionnées sur cette fenêtre
            # Côté ads, le lien fenêtre est PORTÉ par fenetre_id (les utm_campaigns du
            # mapping servent au pont S013/canaux, pas au nommage des campagnes ads).
            nb_campagnes = sum(
                1 for c in campagnes_f
                if c.get('fenetre_id') == fid
            )
        # nb_leads_attribues n'est pas déductible sans lien campagne→lead individuel,
        # nous le laissons à 0 conformément au périmètre de S015.
        nb_leads = 0
        if nb_campagnes == 0:
            digest = "aucune_campagne_liee"
        else:
            digest = f"Fenêtre {fid} : {nb_campagnes} campagne(s) liée(s), {nb_leads} leads attribués"
        fenetres_result.append({
            'fenetre_id': fid,
            'digest_fr': digest,
            'nb_campagnes': nb_campagnes,
            'nb_leads_attribues': nb_leads
        })

    # ------------------------------------------------------------------
    # 3. Références (sha256 des fichiers/dicts sources)
    # ------------------------------------------------------------------
    refs = {}
    refs['attribution'] = _hash_json_dict(rapport_attribution)
    refs['ads'] = _hash_json_dict(rapport_ads)

    contrat_utm_path = _get_project_root() / "contracts" / "utm-convention.v1.yaml"
    if contrat_utm_path.exists():
        refs['utm_convention'] = hashlib.sha256(contrat_utm_path.read_bytes()).hexdigest()
    else:
        # fallback: hash vide (ne se produira pas dans le dépôt réel)
        refs['utm_convention'] = hashlib.sha256(b'').hexdigest()

    # Construction du rapport sans snapshot_id pour génération du snapshot
    rapport_sans_id = {
        'date_reference': date_reference,
        'par_canal': canaux_result,
        'par_fenetre': fenetres_result,
        'refs': refs
    }
    snapshot_id = hashlib.sha256(
        json.dumps(rapport_sans_id, sort_keys=True, ensure_ascii=False).encode('utf-8')
    ).hexdigest()

    rapport = dict(rapport_sans_id)
    rapport['snapshot_id'] = snapshot_id
    return rapport

def calculer_snapshot_id(rapport):
    """Calcule un snapshot_id déterministe à partir du rapport hors snapshot_id."""
    copie = {k: v for k, v in rapport.items() if k != 'snapshot_id'}
    data = json.dumps(copie, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()

def generer_digest_fenetre(fenetre, campagnes_liees, leads_attribues):
    """Génère une phrase FR déterministe pour une fenêtre."""
    if not campagnes_liees:
        return "aucune_campagne_liee"
    nb = len(campagnes_liees)
    fid = fenetre.get('id', 'inconnue') if isinstance(fenetre, dict) else 'inconnue'
    return f"Fenêtre {fid} : {nb} campagne(s), {leads_attribues} leads attribués"
