# R43 — mesure réelle STT français canadien sur CPU

Le candidat `whisper.cpp v1.8.0` avec `large-v3-turbo q5_0` a traité les **20 extraits Common Voice sélectionnés, provenant de 20 locuteurs distincts**. Les fichiers PCM16 mono à 8 kHz passent par le serveur HTTP local, avec deux threads CPU. Aucun appel client, aucune donnée privée et aucun entraînement n’ont été réalisés.

| Mesure | Résultat |
|---|---:|
| Erreurs de mots / mots de référence | 56 / 193 |
| WER, normalisation NFKC et ponctuation, accents et chiffres conservés | 29,02 % |
| Latence HTTP p50 / p95, rang le plus proche | 41,55 s / 42,16 s |
| Requêtes dépassant le budget Core de 4 secondes | 20 / 20 |
| Erreurs HTTP ou délais de 300 secondes dépassés | 0 / 20 |
| Pic RSS du groupe de processus, échantillonné à 250 ms | 938 639 360 octets |
| Marge cgroup minimale observée | 3 102 494 720 octets |

**Décision : candidat non qualifié pour une réception ou une dictée en temps réel sur ce CPU.** Le succès HTTP prouve le fonctionnement du banc, pas l’aptitude au produit. Un traitement différé de messages vocaux demanderait encore une qualification métier, une file de travaux, un délai explicite et une validation du texte incertain. Il n’est pas raccordé au produit à ce stade.

ROOT a recalculé indépendamment les distances d’édition et les quantiles, vérifié les références et empreintes audio contre le manifeste, puis vérifié l’arrêt du serveur et la fermeture du port. Les compteurs OOM n’ont pas augmenté. Le résultat complet et les journaux publics sont conservés dans le [reçu ROOT](/workspace/poursuite-opsys-2026-10-02-r1/R43-qualification-root-r1/VERIFICATION-ROOT-r1.json).

Les 20 phrases lues, 123,792 secondes de son, ne représentent ni les appels de rénovation, ni le bruit de chantier, ni les interruptions et noms/adresses clients. L’écriture des chiffres et des accents peut compter comme erreur selon cette normalisation. Aucun résultat publié sur GPU n’est présenté comme une mesure de cet environnement. Le matériel, les threads et le quantile sont toujours associés aux mesures.

Poids : 574 041 195 octets, SHA-256 `394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2`. Binaire : SHA-256 `5c745067e4929d52331b2c0ce8f82aeefe632e077e76114ef7747efd0d5d8a21`, commit `41fc9dea6a4fe056424be86f61164413903fcff4`. Le [protocole R6](/workspace/poursuite-opsys-2026-10-02-r1/R43-whisper-r6/R43-whisper-r6.md) et ses vérifications préparatoires restent historiques et inchangés.

Suite : vérifier la chaîne audio et les coûts d’encodage à partir du code épinglé ; comparer des options adaptées au français québécois et au budget temps réel. Un modèle plus petit ne sera pas adopté sur sa seule vitesse. La voix mobile, le TTS, le SIP et les avatars parlants restent à intégrer et à qualifier.
