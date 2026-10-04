# OCR M5 — identité d’un artefact PDFium candidat

4 octobre 2026 UTC. Recherche d’artefact, sans installation ni exécution.
Ce wheel **5.13.0** est distinct du **5.3.0 installé** utilisé par le
[pilote CPU](M5-OCR-PILOTE-CPU-2026-10-04.md). La provenance encore ouverte
du binaire installé ne devient pas celle du nouveau candidat.

## Identité vérifiée

PyPI fournit `pypdfium2-5.13.0-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl`,
3 730 077 octets, SHA-256
`81df25c1ab4c13ff773102d3cbea1967511d079123b067fc077bd0c4d57d91d8`.
L’agent puis ROOT revérifient taille et empreinte. Les métadonnées du wheel
correspondent à l’empreinte `core-metadata` de PyPI. Ses tags déclarent Python 3 /
Linux x86_64 / manylinux ; aucun chargement de bibliothèque ne prouve ici sa
compatibilité avec le worker ou un VPS. L’artefact PyPI n’a pas de signature
déclarée : identité par empreinte et construction reproductible restent des
preuves différentes.

| Élément | Référence conservée |
|---|---|
| Wrapper 5.13.0 | Tag annoté `86fb6af04dc6912ec3f5ddc4edb76ee4a7c8bbb5` → commit `a4659102e4c258ee18c661232c0f9763f6c85ad0` |
| Version native embarquée | PDFium 153.0, build 7999, origine `pdfium-binaries` |
| Release du constructeur | `chromium/7999`, commit du dépôt builder `b9132659ca171211a8b7a996e0e4df2d317961ad` |
| Source PDFium indiquée | `e9fc01804a0c5224ea780ad782abb8cfede628ef`, également résolue par Gitiles |
| Archive Linux x64 amont | 3 675 613 octets, SHA-256 `c3af580f9df0fef9545b44115bc5ea440f286956b5f231df69fb373b8efc4f69` |

ROOT télécharge ensuite cette archive publique bornée et vérifie son empreinte.
Le membre `lib/libpdfium.so` et celui du wheel sont **identiques octet par octet** :
7 669 256 octets, SHA-256
`224f8ece41f7e35891f11c10073b7b7062d7a18e9ef870586162a85c46130f7d`.
Aucune bibliothèque n’est installée ni exécutée. Cette comparaison relie les
deux artefacts publiés ; elle ne reproduit pas la compilation depuis les sources.

## Notices propres à l’artefact

ROOT compare les **19 fichiers de licence déclarés** aux octets du wheel.
Ils comprennent Apache/BSD du wrapper, notices PDFium et constructeur, puis
Abseil, agg23, fast_float, FreeType, ICU, LCMS, JPEG-Turbo, OpenJPEG, PNG, TIFF,
llvm-libc, simdutf et zlib. Les notices PDFium/constructeur du wheel diffèrent de
celles du dépôt wrapper : conserver les copies embarquées du candidat exact.

La notice ICU inclut des textes GPLv2/v3 de scripts de construction Autotools
avec exceptions. Elle est conservée avec son contexte ; sa présence ne prouve
pas à elle seule l’inclusion de code GPL dans le moteur exécuté. Les conditions
des notices et exceptions restent à appliquer au paquet effectivement distribué.

Une erreur de citation du rapport agent r1 donnait le commit du wrapper installé
5.3.0 à la place de celui du 5.13.0. ROOT l’a identifiée dans la capture de tag ;
le rapport r2 et les index sont corrigés. Les originales et leurs manifestes
demeurent intacts. La comparaison binaire ROOT est postérieure à ces rapports,
ce qui explique leurs mentions « archive amont non téléchargée ».

## Décision et portée

Conserver ce candidat pour la prochaine qualification du rasterizer isolé,
avec pin exact et notices. Aucune dépendance OPSYS ni configuration du lecteur
natif n’est modifiée. Isolation, plafonds, erreurs, redressement et coordonnées,
corpus représentatif et intégration AP doivent fournir leurs propres preuves.
Ni OCR de production, ni précision fr-CA, ni ingestion massive ne sont qualifiés.

[Capsule des métadonnées et notices](preuves/M5-OCR-ARTEFACT-PDFIUM-r1.tar.xz),
[manifeste](preuves/M5-OCR-ARTEFACT-PDFIUM-r1.json). Le wheel, l’archive binaire
et les bibliothèques sont exclus de la capsule ; URL et empreintes permettent
de retrouver les artefacts exacts.
