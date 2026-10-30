from m9_strategic_intelligence import contrats_attendus as ca, raccord_core_conseil as rc, semantique_metriques as sm
def essai(nom, f):
    try: print(nom, "->", f())
    except Exception as e: print(nom, "-> EXC", type(e).__name__, e)
dep = lambda **k: {"debut":"2026-10-01","fin":"2026-10-31","couverture":"PARTIELLE","manque":[],"lignes":[{"canal":"r","montant_cad":"450.00","constate_le":"2026-10-15","source_ref":"r:7"}]} | k
essai("C1 couverture liste", lambda: ca.valider_charge("depenses_marketing", dep(couverture=[])))
pl = {"debut":"2026-10-01","fin":"2026-10-31","ouvertes_total":3,"manque":[],"categories":[{"categorie":{"x":1},"ouvertes":1}]}
essai("C2 categorie dict", lambda: ca.valider_charge("plaintes_structurees", pl))
essai("C3 date impossible + fin<debut + montant negatif", lambda: ca.valider_charge("depenses_marketing", dep(debut="2026-99-99", fin="2026-01-01", lignes=[{"canal":"r","montant_cad":"-450","constate_le":"0000-00-00","source_ref":"r"}]))["conforme"])
pl2 = {"debut":"2026-10-01","fin":"2026-10-31","ouvertes_total":99,"manque":[],"categories":[{"categorie":"degat","ouvertes":1},{"categorie":"degat","ouvertes":5}]}
essai("C4 doublon categorie + total incoherent", lambda: ca.valider_charge("plaintes_structurees", pl2)["conforme"])
li = {"liaisons_versions":[{"metric_id":"m","revision":1,"empreinte":"a"*64},{"metric_id":"m","revision":2,"empreinte":"a"*64}]}
essai("C5 liaisons contradictoires valider_charge", lambda: ca.valider_charge("liaisons_versions", li)["conforme"])
essai("C5b meme lot cataloguer_liaisons", lambda: sm.cataloguer_liaisons(li["liaisons_versions"], {"m":{}}))
essai("C6 manque bytes vide", lambda: ca.valider_charge("depenses_marketing", dep(manque=b""))["conforme"])
essai("C7 liste None", lambda: ca.valider_charge("depenses_marketing", dep(lignes=None)))
cap = {"semaine_debut":"2026-11-02","calculable":False,"manque":[],"equipes":[{"equipe_id":"a","heures_disponibles":"-5","heures_planifiees":"9"}]}
essai("C8 calculable False sans manque, heures negatives", lambda: ca.valider_charge("capacite_equipe", cap)["conforme"])
dp = {"acteur":"admin","outil":rc.OUTIL_DEPOT,"resultat":"ok","session_id":"s2","role":"strategie_ventes","reservation":{"id":"r","profil":rc.agent_id("strategie_ventes"),"statut":"conciliee","tokens_reels":-10,"tokens_plafond":5}}
en = {"acteur":"admin","outil":rc.OUTIL_ENTREE,"resultat":"ok","session_id":"s1","role":"liaison_finance"}
essai("R1 depot avant entree, autre session/role, tokens negatifs", lambda: rc.verifier_trace([dp, en])["verdict"])
essai("R2 agent reussit m9_ouvrir_conseil", lambda: rc.verifier_trace([en, dp|{"reservation":dp["reservation"]|{"tokens_reels":1}}, {"acteur":"agent","outil":"m9_ouvrir_conseil","resultat":"ok"}, {"acteur":"agent","outil":"m9_cloturer_conseil","resultat":"ok"}])["verdict"])
essai("R3 role liste", lambda: rc.verifier_trace([en, dp|{"role":[]}]))
essai("R4 reservation sans id", lambda: rc.verifier_trace([en, dp|{"reservation":{k:v for k,v in dp["reservation"].items() if k!="id"}|{"tokens_reels":1}}])["verdict"])
essai("R5 evenement runtime (etape 5 SEQUENCE)", lambda: rc.verifier_trace([en, {"acteur":"runtime","outil":"reconcilier","resultat":"ok"}, dp]))
essai("R6 depot sans session_id ni reservation_id unique", lambda: rc.verifier_trace([en, {k:v for k,v in dp.items() if k!="session_id"}|{"reservation":dp["reservation"]|{"tokens_reels":1}}])["verdict"])
cat = {"m":{"metric_id":"m","unite":"CAD","version":3}}
L = sm.cataloguer_liaisons([{"metric_id":"m","revision":2,"empreinte":"a"*64}], cat)
essai("S1 revision 2 absente du registre (registre saute 1->3)", lambda: sm.classer({"metric_id":"m","valeur":"1","unite":"CAD","version_definition":"a"*64}, cat, L)["statut"])
essai("S2 obs version True vs courante 1 (hors diff)", lambda: sm.classer({"metric_id":"m","valeur":"1","version_definition":True}, {"m":{"metric_id":"m","unite":"CAD","version":1}})["statut"])
essai("S3 obs version 1.0", lambda: sm.classer({"metric_id":"m","valeur":"1","version_definition":1.0}, {"m":{"metric_id":"m","unite":"CAD","version":1}})["statut"])
cat2 = {"m":{"metric_id":"m","unite":"CAD","version":2}}
L2 = sm.cataloguer_liaisons([{"metric_id":"m","revision":2,"empreinte":"a"*64}], cat2)
r = sm.rapprocher([{"metric_id":"m","valeur":"1","unite":"CAD","version_definition":"a"*64},{"metric_id":"m","valeur":"2","unite":"CAD","version_definition":2}], cat2, L2)
essai("S4 groupes COMPATIBLE pour meme revision", lambda: [(g["version_definition"], g["statut"]) for g in r["comparables_ensemble"]])
essai("S5 obs unite None + liaison", lambda: sm.classer({"metric_id":"m","valeur":"1","version_definition":"a"*64}, cat2, L2))
essai("S6 cataloguer_liaisons None", lambda: sm.cataloguer_liaisons(None, cat2))
essai("S7 cataloguer_liaisons dict", lambda: sm.cataloguer_liaisons({"metric_id":"m"}, cat2))
