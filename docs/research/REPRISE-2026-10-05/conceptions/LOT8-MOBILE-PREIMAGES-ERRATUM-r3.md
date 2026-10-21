# Erratum r3 — bases des patchs lot8 mobile vendeur

Les stages r1 et r2 restent inchangés.

`PATCH.diff` de r1 (SHA-256 `d3f7ca2d361f719f6c76cceaf55437ed2b445d5f181dd75e37ab2cfb0be66bcf`) transforme les préimages du dépôt en copies r1. Par exemple, `quotes.tsx` part de la préimage live SHA `44120ea805437f67a559fbe1b299fb03a1e77f03ffb8f974c6e87a19d50094d9` et aboutit au fichier r1 SHA `39ea4c9499cc1858023f47fd45edd0eb01c9df83fba851b854400ccbc58c5cfa`.

`PATCH-R2.diff` (SHA-256 `a3803a6fdc6260b55ff45dcce0b14cdc51067ab228e03c71ddc29f0b6c8ef826`) est le delta des copies r1 vers les copies r2. Pour `quotes.tsx`, la préimage r2 est bien la copie r1 SHA `39ea4c9499cc1858023f47fd45edd0eb01c9df83fba851b854400ccbc58c5cfa`; la copie r2 finale est SHA `cc30f0c7859d7b487a837d2a79b8e513fc446af9a34b155f46149484fe0cc31c`.

Les fichiers `chargeurReadiness.ts` et `chargeurReadiness.test.ts` n’existaient pas dans les copies r1. Leurs préimages r2 sont les sources originales non modifiées par r1; le delta r2 les ajoute avec le helper de contrôle de session et le test différé. La composition de promotion est donc: appliquer le patch r1 à sa base live, puis le patch r2 au résultat; les deux chemins readiness restent à leur version live avant l’ajout r2.

Le test de visibilité couvre une page détenue par A masquée pour B et une réponse différée rejetée par personne/séquence; ce modèle pur ne valide pas le rendu réel React Native ni les cartes visuelles complètes. Cette qualification reste à faire par ROOT. Aucun test, build, lint ou QA n’a été exécuté ici.
