# Schéma des registres (append-only, JSONL, jamais édités à la main)
Entrée: {"ts":"ISO8601","acteur":"humain|modele:nom","action":"","cible":"",
"preuve":{"commande":"","sortie_hash":"","artefact":""},"hash_precedent":""}
Fichiers: decisions.jsonl · preuves.jsonl · executions.jsonl · installations.jsonl
Règle: entrée DONE sans preuve = invalide (gate CI la rejette).
