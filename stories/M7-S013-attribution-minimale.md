# M7-S013 — Attribution minimale (Matomo fixtures + CRM lecture seule)

T2 · allowed: src/attribution/, tests/, fixtures/{matomo,crm}/ · deps S012 · SANS MMM · zéro
réseau/horloge. Fixtures FICTIVES gelées sha256 (fictif fail-closed, ids anonymes v-xxx/l-xxx,
visitor_id CRM optionnel = réalité terrain). Jointure STRICTE par visitor_id — jamais d'heuristique
(anti-invention) ; fenêtre paramètre (30 j défaut justifié rénovation) ; première/dernière touche,
départage lexicographique déterministe ; non_attribuables comptés, divergences source_declaree↔UTM
SIGNALÉES jamais tranchées ; aucun ratio à dénominateur nul (omission) ; UTM des visites validées
par S012 (URL reconstruite). Lecture seule PROUVÉE (sha avant/après). 11 tests. Architecte
Qwen3.7-Max (5e ADR prose). Défauts GREEN : dates YAML natives, campaigns fixtures hors format
(balayage exhaustif + re-gel), import namespace/assertion manquante réparés au contrat prescrit.
