# PDF isolé : diagnostic du runner Ubuntu

Sur le head `0c265cc13dec0dc23093b1d362d59c32aa26af6e`, le job socle
[`111356155855`](https://github.com/leon36000/OPSYS-AI/actions/runs/37175159762/job/111356155855)
installe réellement `bubblewrap 0.9.0-1ubuntu0.3`. Le prévol du confinement
échoue ensuite : `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`.
Les tests du socle ne démarrent pas; aucun résultat PostgreSQL ni résultat
de parsing PDF n'est déduit de ce job. Le lint et la cohérence des départements
avaient réussi. Le job départemental M7 réussit après ses reclassifications.

La source exacte de [bubblewrap 0.9.0](https://github.com/containers/bubblewrap/blob/v0.9.0/network.c#L137-L182)
configure `127.0.0.1/8` sur le loopback du nouveau namespace réseau par
`RTM_NEWADDR`. `EPERM` désigne un refus de cette opération. Il ne distingue
pas à lui seul une interdiction AppArmor, une capacité `CAP_NET_ADMIN`
manquante ou une autre restriction du runner.

[Ubuntu documente](https://documentation.ubuntu.com/security/security-features/privilege-restriction/apparmor/)
la permission de namespaces par programme; la
[manpage Noble](https://manpages.ubuntu.com/manpages/noble/en/man5/apparmor.d.5.html)
définit `userns create,` et les modes de profil correspondants. Un profil
ciblé `/usr/bin/bwrap` est donc une piste de configuration à évaluer.
Il n'est pas appliqué tant que le déni observé n'est pas identifié.
La sonde locale réussit sur Debian 13, où le paramètre de restriction AppArmor
Ubuntu n'existe pas : cette réussite ne qualifie pas Ubuntu.

Le workflow ajoute seulement une étape de diagnostic après un échec :

- lecture des deux paramètres kernel de namespaces et du profil du processus;
- état AppArmor via `aa-status`;
- journal kernel limité aux cinq dernières minutes, à 64 entrées et aux
  lignes AppArmor concernant bubblewrap ou `unprivileged_userns`;
- sorties bornées, codes de commande conservés; aucun dump d'environnement.

Le prévol reste bloquant. Le diagnostic ne désactive pas AppArmor, ne change
aucun sysctl, n'ajoute aucun bit setuid, ne partage pas le réseau hôte et ne
substitue pas le worker. Une absence de journal exploitable ne prouvera pas
l'absence de refus AppArmor. La prochaine décision doit partir du déni natif,
puis être éprouvée par le même prévol et les vrais tests de confinement.

`qa-r66` : dix tests entiers de configuration CI réussis, aucun ignoré,
Ruff/actionlint réussis, sources figées et aucun nouveau OOM.
`qa-r67` : Gitleaks du workflow modifié sans alerte brute. Ces contrôles
valident la modification de diagnostic, pas la résolution du refus natif.
Les preuves précédentes et la capsule [Socle/M7](SOCLE-CONTRATS-M7.md)
restent inchangées. OPSYS-AI reste PARTIEL; le gate mobile reste rouge.

[Archive](preuves/PDF-RUNNER-UBUNTU-r1.tar.xz) et
[inventaire SHA256](preuves/PDF-RUNNER-UBUNTU-r1.json).
