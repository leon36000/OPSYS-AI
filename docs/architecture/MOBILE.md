# Application mobile OPSYS

Base : les applications officielles d'OpenClaw (`apps/ios`, `apps/android`, compagnons Wear OS et
Apple Watch ; MIT). Elles se connectent à la passerelle comme un **nœud** (`role: node`).

## Ce qu'elles font déjà (README amont, v2026.9.6)

- Appairage à la passerelle par QR code ou code de configuration. Identifiants chiffrés sur
  l'appareil.
- Chat en flux, choix du modèle et de l'agent, sessions épinglées.
- Voix : mot d'éveil, mode Talk.
- **Approbations.**
- Pièces jointes photo et vidéo depuis la caméra.
- Localisation, notifications.
- SMS (Android, builds tiers).
- Gestion des skills et des automatisations.

## Phase 1 — sans développement

Le patron et les équipes installent l'app OpenClaw officielle et l'appairent à la passerelle OPSYS
de leur VPS. Tout de suite :

| Besoin OPSYS | Comment |
|---|---|
| M3 : photos de chantier pour l'estimation | Caméra → message à l'agent M3 → `m3_estimer_projet` |
| M4 : pointage et suivi terrain | Localisation du nœud + outils M4 (pointage, écarts, fin de travaux) |
| M1 : réception vocale | Talk / mot d'éveil vers l'agent M1 |
| Direction : approbations | Approbations natives de l'app pour les actions OpenClaw ; demandes T2/T3 d'OPSYS visibles dans la console `/opsys` (navigateur mobile) |

## Phase 2 — application OPSYS (fork rebrandé)

Fork de `apps/ios` et `apps/android`, épinglé sur la même release que la passerelle :
1. Identité OPSYS : nom, icônes, thème. La licence MIT est conservée avec l'attribution.
2. Écrans par profil :
   - Patron : approbations OPSYS, budgets, digest ;
   - Estimateur : prise de photos guidée avec référence d'échelle, retour immédiat « prix bloqué :
     il manque… » ;
   - Chef d'équipe : cédule du jour, pointage, déclaration de fin de travaux ;
   - Réception : file des demandes.
3. Les écrans consomment les mêmes capacités MCP que les agents. Aucune logique métier dans l'app.
4. **Publication App Store / Google Play : frontière humaine (T3).** Comptes développeur, signature
   et fiche store relèvent du propriétaire.

## Points à valider sur un VPS réel

- Appairage à travers Caddy (TLS) et authentification de la passerelle.
- Transmission des photos du nœud vers l'outil M3 : format, taille, métadonnées d'échelle.
- Localisation du nœud utilisable par les outils M4, avec consentement Loi 25 (politique
  géolocalisation dans `docs/compliance/politiques/`).
