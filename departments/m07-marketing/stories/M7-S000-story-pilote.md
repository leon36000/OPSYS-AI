# M7-S000 — Story pilote (MODE OMBRE)

But: prouver le pipeline A->G de bout en bout, pas le produit. <= 1 h humain-equivalent (D-044).

## Portee
- Charger un profil de marque depuis `departments/m07-marketing/src/brand/profile.yaml`
- Exposer `GET /brand` (lecture seule) qui retourne le profil valide par schema
- Tests: schema valide, profil charge, endpoint repond, champ manquant -> erreur RFC 9457

## Criteres d'acceptation (testables)
1. `pytest` vert avec assertions reelles (aucun test sans assertion)
2. e2e minimal: requete HTTP reelle -> 200 + payload conforme
3. Impact doc declare: README M7 mis a jour (sinon doc:none journalise)
4. MODE OMBRE: aucun effet de bord externe

## Interdits rappeles
Stubs, TODO en diff, assert True, DONE partiel. Sortie finale: PREUVE: ou BLOCKED:.
