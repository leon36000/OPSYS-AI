# M7-S012 — Convention UTM gelée + générateur/validateur déterministe

T2 · allowed: src/utm/, tests/, contracts/ · deps S006+S008 · touches_ledger: false · zéro réseau.
Contrat utm-convention.v1.yaml GELÉ (sha256 137b99e0…, test consommateur D-015) : enums FR
sources/mediums justifiés par les canaux réels, campaign = <origine>-<slug>-<annee> (translittération
NFD déterministe, déduplication d'année). generer_lien_utm : ordre canonique stable, préservation
des params non-UTM, écrasement des utm_* préexistants, encodage % strict. valider_lien_utm : 12
règles U-01..U-12 fail-closed (U-08 ordre = warn). Intégrations utm_pour_content_item / utm_pour_
fenetre sur les données RÉELLES S006/S008 (url_base défaut = canonical S004), mapping surface→
(source,medium) déclaré hors contrat. 73 tests. Architecte Qwen3.7-Max (4e ADR prose conforme).
Défauts GREEN corrigés : +* regex invalide, année dupliquée, alphabet content sans +, url exigée à
tort, tests d'intégration sur API imaginaire réparés sur l'API réelle.
