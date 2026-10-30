from opsys import equipes
base={'competences':['gouttieres'],'depot':{'id':'depot-fictif','latitude_microdegres':45580000,'longitude_microdegres':-73750000},'quarts':[{'jour':0,'debut_min':480,'fin_min':1020}]}
profil={'liste':[dict(base,id='eq-a',membres=['admin.fictif']),dict(base,id='eq-b',membres=['reprise.fictive'])], 'services':{'gouttieres':{'duree_min':90,'competences':['gouttieres']}},'cedule':{'facteur_detour_milliemes':1300,'vitesse_moyenne_kmh':50,'marge_par_trajet_secondes':60,'iterations':10,'cout_non_cedule_m':500000},'fenetre_par_defaut':{'jours':[0],'debut_min':480,'fin_min':1020}}
equipes.enregistrer_equipes(profil);print('PROFIL_FICTIF_CREE')
