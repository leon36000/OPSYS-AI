# M7-S015 — Rapport ROI minimal consolidé (snapshot-ready M8)

T2 · allowed: src/roi/, tests/, metrics/, contracts/ · deps S012+S013+S014 · SANS MMM · zéro
réseau/horloge. Pont canal↔fenêtre par MAPPING DÉCLARÉ (contracts/roi-mapping.v1.yaml — jamais de
substring), campagne hors mapping = sans_pont/mapping_absent ; cout_par_lead émis SEULEMENT si
leads>0 ET coût fini (raisons énumérées zero_leads/cout_indisponible/mapping_absent — division
structurellement impossible) ; devise CAD ; digests FR par fenêtre réelle (aucune_campagne_liee) ;
snapshot_id sha256 du JSON canonique (date_reference incluse) ; refs sha256 des 3 sources ; +4
métriques ADDITIVES au catalogue (enregistrées au test de cohérence, pattern S009). Normaliseurs
double-dialecte documentés (S013 dict/liste, S014 plat/imbriqué, calendrier réel/festif). 12 tests.
Architecte Qwen3.7-Max (6e ADR prose). Défauts GREEN corrigés : clés calendrier/plateformes
fantômes, schema_version orphelin dans le catalogue, date_reference hors snapshot.
