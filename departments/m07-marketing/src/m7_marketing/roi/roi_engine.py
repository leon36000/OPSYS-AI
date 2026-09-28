import json
import hashlib
from pathlib import Path
import yaml

def _get_project_root():
    return Path(__file__).resolve().parents[3]

# Table de correspondance EXPLICITE canal (utm_source réel, tel que produit par
# attribution_engine.attribuer -> par_canal, ex. "google") -> plateforme_ads (taxonomie
# ads_loader.ALLOWED_PLATFORMS / fixtures/ads/*.yaml, ex. "google_ads"). Sans cette table,
# roi_engine cherchait "google" dans un dict indexé par "google_ads" : aucune correspondance
# n'était jamais possible et le coût réel n'était jamais retrouvé (R9 §1.1). Un canal absent
# de cette table n'a simplement AUCUNE plateforme publicitaire connue (organique/propriétaire,
# ex. gbp, infolettre, site) : jamais de plateforme fabriquée, la jointure échoue proprement
# en donnees_insuffisantes.
CANAL_VERS_PLATEFORME_ADS = {
    "google": "google_ads",
    "facebook": "meta",
    "gbp": "gbp_natif",
}

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
        # Jointure canal (utm_source réel) -> plateforme_ads via la table explicite,
        # jamais canal utilisé tel quel comme clé de plateforme (R9 §1.1).
        plateforme = CANAL_VERS_PLATEFORME_ADS.get(canal)
        campagnes_plateforme = campagnes_par_plateforme.get(plateforme, []) if plateforme else []

        cout_total = 0.0
        nb_campagnes_joignables = 0
        for camp in campagnes_plateforme:
            fenetre_id = camp.get('fenetre_id')
            mapping_fenetre = mapping_par_fenetre.get(fenetre_id)
            # Joignable si la fenêtre de la campagne est déclarée dans roi-mapping.v1.yaml
            # ET que ce mapping désigne bien LA MÊME plateforme que celle du canal courant
            # (une campagne dont la fenêtre est mappée à une autre plateforme n'est pas
            # attribuable à ce canal-ci, même si elle porte le même fenetre_id par coïncidence).
            if mapping_fenetre is not None and mapping_fenetre['plateforme'] == plateforme:
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
    # par_campagne du rapport d'attribution réel : {utm_campaign: {..., leads_derniere_touche}}.
    # C'est le SEUL lien campagne->lead disponible (attribution_engine agrège déjà par
    # utm_campaign) ; roi-mapping.v1.yaml relie fenetre_id à un ensemble d'utm_campaigns
    # (pas aux noms de campagnes ads, qui vivent dans un espace de noms différent).
    campagnes_attr = rapport_attribution.get('par_campagne', {}) or {}
    fenetres_result = []
    for f in fenetres_calendrier:
        fid = f.get('id') or f.get('fenetre_id')  # réel: 'id' ; festif: 'fenetre_id'
        mapping_fenetre = mapping_par_fenetre.get(fid)
        if mapping_fenetre is None:
            # Lien fenêtre -> campagnes totalement absent de roi-mapping.v1.yaml : on ne
            # sait ni combien de campagnes ni combien de leads sont liés à cette fenêtre.
            # Jamais de 0 fabriqué : refus explicite (R9 §1.2).
            fenetres_result.append({
                'fenetre_id': fid,
                'digest_fr': "aucune_campagne_liee",
                'nb_campagnes': 0,
                'donnees_insuffisantes': {'raison': 'lien_campagne_lead_absent'},
            })
            continue

        plateforme_f = mapping_fenetre['plateforme']
        campagnes_f = campagnes_par_plateforme.get(plateforme_f, [])
        # Ne compter que les campagnes réelles positionnées sur cette fenêtre (par fenetre_id ;
        # les utm_campaigns du mapping servent au pont S013/canaux, pas au nommage ads).
        nb_campagnes = sum(
            1 for c in campagnes_f
            if c.get('fenetre_id') == fid
        )
        # nb_leads_attribues calculé depuis l'attribution RÉELLE : somme des leads en
        # dernière touche des utm_campaigns que roi-mapping.v1.yaml lie à cette fenêtre.
        # Un 0 ici est un vrai zéro mesuré (campagnes liées mais pas encore de lead touché),
        # jamais une valeur par défaut faute de lien.
        nb_leads = sum(
            campagnes_attr.get(nom_utm, {}).get('leads_derniere_touche', 0)
            for nom_utm in mapping_fenetre['campagnes']
        )
        digest = generer_digest_fenetre(f, nb_campagnes, nb_leads)
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
    """Génère une phrase FR déterministe pour une fenêtre (compte OU liste acceptés)."""
    nb = campagnes_liees if isinstance(campagnes_liees, int) else len(campagnes_liees or [])
    if nb == 0:
        return "aucune_campagne_liee"
    fid = (fenetre.get('id') or fenetre.get('fenetre_id', 'inconnue')) if isinstance(fenetre, dict) else 'inconnue'
    return f"Fenêtre {fid} : {nb} campagne(s), {leads_attribues} leads attribués"
