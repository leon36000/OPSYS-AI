"""Catalogue initial des fournisseurs : candidats ADOPTÉS, de REPLI, CONDITIONNELS et ÉCARTÉS.

Source : FEUILLE-DE-ROUTE-TECHNO r2 (tableau A) et recherches R1 (voix/avatars), R3 (OCR/RAG), R4 (web),
R5 (image/vidéo), R6 (agents/LLM) du 2026-10-31. Les licences sont reprises TELLES QUE DOCUMENTÉES dans ces
recherches (champ `source` = fichier et ligne/section) ; rien n'est complété de mémoire.

Conventions :
- `qualification="a_mesurer"` partout : aucune mesure locale (FR-QC, factures québécoises, GB10) n'existe encore
  (FEUILLE r2 B.4). Un fournisseur adopté n'est PAS « qualifié ».
- `verification="a_lire"` quand la recherche signale une licence lue en résumé seulement ou une question ouverte :
  le moteur de politique refuse alors l'activation tant qu'un administrateur n'a pas consigné sa lecture.
- `service_tiers="incertain"` pour toute licence maison de modèle dont le droit d'offrir un service à des tiers
  n'est pas établi par la recherche (permissives OSI et CC-BY : `autorise`).
- Coûts : seulement ceux que la recherche publie (sinon `None` = non déclaré) ; points d'accès d'exemple en boucle
  locale pour le local, à configurer pour les API. Aucune clé, aucune donnée réelle.
"""

from __future__ import annotations

from .modele import Cout, Fournisseur, Licence

R1 = "recherche/R1-AVATARS-VOIX.md"
R3 = "recherche/R3-INGESTION-OCR-RAG-CONNECTEURS.md"
R4 = "recherche/R4-MARKETING-SEO-GEO-WEB.md"
R5 = "recherche/R5-CREATION-IMAGE-VIDEO-DESIGN.md"
R6 = "recherche/R6-AGENTS-AUTONOMIE-OUTILLAGE.md"
VLLM = "http://127.0.0.1:8000/v1"


def _permissive(code: str | None, poids: str | None, source: str, **extra) -> Licence:
    return Licence(code=code, poids=poids, usage_commercial="autorise", service_tiers="autorise", source=source,
                   **extra)


def _f(identifiant: str, capacite: str, mode: str, modele: str, licence: Licence, statut: str, **extra) -> Fournisseur:
    return Fournisseur(identifiant=identifiant, capacite=capacite, mode=mode, modele=modele, licence=licence,
                       statut_catalogue=statut, qualification="a_mesurer", **extra)


def _api_contrat(source: str, note: str | None = None) -> Licence:
    return Licence(code="Propriétaire (API)", poids=None, usage_commercial="sur_contrat", service_tiers="incertain",
                   integration="api", source=source, note=note)


CATALOGUE: tuple[Fournisseur, ...] = (
    # ---------------------------------------------------------------- LLM (R6 §LLM locaux, l. 299-301, 431)
    _f("llm.mistral-small-4.local", "llm", "local", "Mistral Small 4 119B-2603 (NVFP4) via vLLM",
       _permissive("Apache-2.0 (vLLM)", "Apache-2.0", f"{R6} l.299 [V]"), "adopte", point_acces=VLLM),
    _f("llm.gpt-oss-120b.local", "llm", "local", "gpt-oss-120b (MXFP4) via vLLM",
       _permissive("Apache-2.0 (vLLM)", "Apache-2.0", f"{R6} l.300 [V]"), "adopte", point_acces=VLLM),
    _f("llm.nemotron-3.5-lightning.local", "llm", "local", "NVIDIA Nemotron 3.5 Lightning 30B-A3B via vLLM",
       Licence(code="Apache-2.0 (vLLM)", poids="OpenMDW-1.1", usage_commercial="autorise", service_tiers="incertain",
               verification="a_lire", source=f"{R6} l.301 [V carte], l.431 « OpenMDW-1.1, à lire »",
               note="liste blanche R6 : OpenMDW seulement une fois lue"),
       "adopte", point_acces=VLLM),
    # ---------------------------------------------------------------- Embeddings / reranker (R3 §3, l.104-122)
    _f("embeddings.bge-m3.local", "embeddings", "local", "BAAI/bge-m3 (1024 dimensions, ONNX Runtime)",
       _permissive("MIT", "MIT", f"{R3} l.104 [C+V3]"), "adopte", point_acces="http://127.0.0.1:8766"),
    _f("embeddings.qwen3-embedding.local", "embeddings", "local", "Qwen3-Embedding 0.6B/4B (profil GPU, MRL ≤ 2048)",
       _permissive("Apache-2.0", "Apache-2.0", f"{R3} l.105"), "adopte", point_acces=VLLM),
    _f("reranker.bge-reranker-v2-m3.local", "reranker", "local", "BAAI/bge-reranker-v2-m3 (CPU)",
       _permissive("Apache-2.0", "Apache-2.0", f"{R3} l.119"), "adopte"),
    _f("reranker.qwen3-reranker.local", "reranker", "local", "Qwen3-Reranker 0.6B/4B (GPU)",
       _permissive("Apache-2.0", "Apache-2.0", f"{R3} l.121 (C)"), "adopte"),
    _f("reranker.mxbai-rerank-v2.local", "reranker", "local", "mixedbread mxbai-rerank-base/large-v2 (GPU)",
       _permissive("Apache-2.0", "Apache-2.0", f"{R3} l.120 [V]"), "repli"),
    _f("embeddings.jina-v5", "embeddings", "local", "Jina embeddings v3/v4/v5",
       Licence(code=None, poids="v3 CC-BY-NC ; v4 Qwen Research License ; v5 CC-BY-NC-4.0",
               usage_commercial="interdit", service_tiers="interdit", source=f"{R3} l.112 [V]"),
       "ecarte", raison_ecart="poids non commerciaux en auto-hébergement (FEUILLE r2 tableau A)"),
    _f("reranker.jina-reranker-v3", "reranker", "local", "jina-reranker-v2/v3/v3.5",
       Licence(code=None, poids="CC-BY-NC-4.0", usage_commercial="interdit", service_tiers="interdit",
               source=f"{R3} l.122 [V]"),
       "ecarte", raison_ecart="poids non commerciaux (FEUILLE r2 tableau A)"),
    # ---------------------------------------------------------------- OCR / parsing (R3 §2, l.48-70, 386-388)
    _f("ocr.docling.local", "ocr", "local", "Docling (+ Granite-Docling-258M)",
       Licence(code="MIT", poids="Granite-Docling-258M Apache-2.0 ; modèles internes à vérifier un par un",
               usage_commercial="autorise", service_tiers="autorise", verification="a_lire",
               source=f"{R3} l.48-49, question ouverte n° 11"),
       "adopte", point_acces="module:docling"),
    _f("ocr.tesseract-5.5.local", "ocr", "local", "Tesseract 5.5.0 / Leptonica 1.84.1 (worker isolé existant)",
       _permissive("Apache-2.0", None, f"{R3} l.18, l.55"), "adopte", point_acces="binaire:tesseract"),
    _f("ocr.paddleocr.local", "ocr", "local", "PaddleOCR 3.7 : PP-OCRv6, PaddleOCR-VL-1.6",
       _permissive("Apache-2.0", "Apache-2.0 (PaddleOCR-VL)", f"{R3} l.54 (V3)"), "adopte",
       point_acces="module:paddleocr"),
    _f("ocr.mistral-ocr-3.api", "ocr", "api", "Mistral OCR 3",
       _api_contrat(f"{R3} l.66", "entreprise française, données hors Québec (UE)"), "repli",
       residence_donnees="UE", cout_unitaire=Cout("page", "0.002", "USD", f"{R3} l.66 (2 $ US/1000 pages)")),
    _f("ocr.marker", "ocr", "local", "Marker (Datalab)",
       Licence(code="Apache-2.0", poids="OpenRAIL-M modifiée (gratuit < 5 M$ de financement ou revenu)",
               usage_commercial="sous_seuil", seuil_revenu_usd=5_000_000, service_tiers="incertain",
               source=f"{R3} l.51, l.388"),
       "ecarte", raison_ecart="seuil de revenu applicable à l'éditeur (FEUILLE r2 tableau A)"),
    _f("ocr.surya", "ocr", "local", "Surya 2.5 (Datalab)",
       Licence(code="Apache-2.0", poids="OpenRAIL-M modifiée (< 5 M$)", usage_commercial="sous_seuil",
               seuil_revenu_usd=5_000_000, service_tiers="incertain", source=f"{R3} l.52, l.388"),
       "ecarte", raison_ecart="seuil de revenu applicable à l'éditeur (FEUILLE r2 tableau A)"),
    _f("ocr.chandra-2", "ocr", "local", "Chandra 2 (Datalab)",
       Licence(code="Apache-2.0", poids="OpenRAIL-M modifiée : gratuit < 2 M$, concurrence de l'API Datalab interdite",
               usage_commercial="sous_seuil", seuil_revenu_usd=2_000_000, service_tiers="interdit",
               source=f"{R3} l.53, l.388"),
       "ecarte", raison_ecart="seuil de revenu et clause de non-concurrence (FEUILLE r2 tableau A)"),
    _f("ocr.pymupdf", "ocr", "local", "PyMuPDF",
       Licence(code="AGPL-3.0 ou commerciale", poids=None, usage_commercial="autorise", service_tiers="autorise",
               integration="bibliotheque", source=f"{R3} l.70, l.386"),
       "ecarte", raison_ecart="AGPL interdite dans le code distribué (DECISIONS r1 §7)"),
    _f("ocr.ghostscript", "ocr", "local", "Ghostscript (rastérisation OCRmyPDF < 17)",
       Licence(code="AGPL-3.0", poids=None, usage_commercial="autorise", service_tiers="autorise",
               integration="bibliotheque", source=f"{R3} l.56, l.386"),
       "ecarte", raison_ecart="AGPL ; OCRmyPDF ≥ 17 rastérise par pypdfium2 (FEUILLE r2 tableau A)"),
    _f("ocr.nougat", "ocr", "local", "Nougat (Meta)",
       Licence(code="MIT", poids="CC-BY-NC-4.0", usage_commercial="interdit", service_tiers="interdit",
               source=f"{R3} l.64"),
       "ecarte", raison_ecart="poids non commerciaux (FEUILLE r2 tableau A)"),
    _f("ocr.got-ocr2", "ocr", "local", "GOT-OCR 2.0",
       Licence(code="Avis officiel : recherche seulement (+ licence de Vary)", poids="recherche seulement",
               usage_commercial="interdit", service_tiers="interdit", source=f"{R3} l.63 [V]"),
       "ecarte", raison_ecart="réservé à la recherche (FEUILLE r2 tableau A)"),
    # ---------------------------------------------------------------- STT (R1 §3, l.148-156, 381)
    _f("stt.voxtral-mini-realtime.local", "stt", "local", "Voxtral Mini 4B Realtime 2602 via vLLM",
       _permissive("Apache-2.0 (vLLM)", "Apache-2.0", f"{R1} l.148 [V]"), "adopte", point_acces=VLLM),
    _f("stt.kyutai-stt.local", "stt", "local", "Kyutai STT 1B en_fr",
       _permissive("MIT (Python) / Apache (Rust)", "CC-BY-4.0", f"{R1} l.149, l.381 [V]",
                   mention_obligatoire="Kyutai STT — CC-BY-4.0 (page Crédits de la console)"),
       "repli"),
    _f("stt.parakeet-tdt-v3.local", "stt", "local", "NVIDIA Parakeet TDT 0.6B v3 (NeMo, lot)",
       _permissive("Apache-2.0 (NeMo)", "CC-BY-4.0", f"{R1} l.150 [V]",
                   mention_obligatoire="NVIDIA Parakeet TDT 0.6B v3 — CC-BY-4.0"),
       "repli"),
    _f("stt.pyannote-community-1.local", "stt", "local", "pyannote.audio + speaker-diarization-community-1",
       _permissive("MIT", "CC-BY-4.0 (accès contrôlé)", f"{R1} l.156, l.381 [V]",
                   mention_obligatoire="pyannote speaker-diarization-community-1 — CC-BY-4.0"),
       "repli"),
    # ---------------------------------------------------------------- TTS (R1 §4, l.179-192, 364-367)
    _f("tts.chatterbox-multilingual.local", "tts", "local", "Chatterbox Multilingual V3 (voix sous contrat)",
       _permissive("MIT", "MIT", f"{R1} l.179 [V]"), "adopte"),
    _f("tts.kyutai-tts.local", "tts", "local", "Kyutai TTS 1.6B en_fr",
       _permissive("MIT et Apache", "CC-BY-4.0", f"{R1} l.180, l.381 [V]",
                   mention_obligatoire="Kyutai TTS — CC-BY-4.0 (page Crédits de la console)"),
       "repli"),
    _f("tts.azure-fr-ca.api", "tts", "api", "Azure Neural TTS fr-CA (Sylvie, Antoine, Jean, Thierry)",
       _api_contrat(f"{R1} l.192 [S]", "service infonuagique payant"), "repli", residence_donnees="inconnue",
       cout_unitaire=Cout("million_caracteres", "15", "USD", f"{R1} l.192 [S] (neural ; HD ≈ 30 $)")),
    _f("tts.xtts-v2", "tts", "local", "Coqui XTTS-v2",
       Licence(code="MPL-2.0 (fork idiap coqui-tts)", poids="CPML 1.0 (non commercial, sorties comprises)",
               usage_commercial="interdit", service_tiers="interdit", source=f"{R1} l.185, l.364 [V]"),
       "ecarte", raison_ecart="CPML non commerciale (FEUILLE r2 tableau A)"),
    _f("tts.f5-tts", "tts", "local", "F5-TTS (y compris réglage fin québécois communautaire)",
       Licence(code="MIT", poids="CC-BY-NC-4.0", usage_commercial="interdit", service_tiers="interdit",
               source=f"{R1} l.186, l.365 [V]"),
       "ecarte", raison_ecart="poids non commerciaux (FEUILLE r2 tableau A)"),
    _f("tts.voxtral-tts.local", "tts", "local", "Voxtral 4B TTS 2603 (poids locaux)",
       Licence(code="vLLM (Apache-2.0)", poids="CC-BY-NC-4.0", usage_commercial="interdit", service_tiers="interdit",
               source=f"{R1} l.188, l.366 [V]"),
       "ecarte", raison_ecart="poids non commerciaux en local ; seule l'API Mistral est commerciale"),
    _f("tts.fish-speech", "tts", "local", "Fish Speech / OpenAudio S1-mini",
       Licence(code="Fish Audio Community License v1.0", poids="Fish Audio Community License v1.0",
               usage_commercial="sous_seuil", seuil_revenu_usd=500_000, service_tiers="interdit",
               source=f"{R1} l.187, l.367 [V LICENSE 2026-10-13]",
               note="aucune licence pour un service hébergé de TTS ou de clonage"),
       "ecarte", raison_ecart="seuil de 500 k$ US et service hébergé interdit (FEUILLE r2 tableau A)"),
    # ---------------------------------------------------------------- Avatar (R1 §2, l.29, 113-128, 370-379)
    _f("avatar.talkinghead", "avatar", "local", "TalkingHead (three.js, rendu sur l'appareil)",
       Licence(code="MIT", poids=None, usage_commercial="autorise", service_tiers="autorise", integration="appareil",
               source=f"{R1} l.113, l.379 [V]",
               note="avatars d'exemple brunette.glb (CC-BY-NC) et avatar.glb (non commercial) exclus ; GLB propres"),
       "adopte", point_acces="appareil:talkinghead"),
    _f("avatar.audio2face-3d.local", "avatar", "local", "NVIDIA Audio2Face-3D (SDK + poids v3.0, option GPU)",
       Licence(code="MIT (SDK)", poids="NVIDIA Open Model License", usage_commercial="autorise",
               service_tiers="incertain", source=f"{R1} l.29, l.115 [V]",
               note="Audio2Emotion : licence propre, « usage permis avec Audio2Face seulement » ; aarch64 INCONNU"),
       "repli"),
    _f("avatar.musetalk-1.5.local", "avatar", "local", "MuseTalk 1.5 (worker vidéo LiveKit, option GPU)",
       Licence(code="MIT", poids="« any purpose, even commercially »", usage_commercial="autorise",
               service_tiers="autorise", verification="a_lire", source=f"{R1} l.116, l.382, question ouverte n° 9",
               note="licence exacte de S3FD inconnue ; données de test non commerciales à ne pas embarquer"),
       "repli"),
    _f("avatar.nvidia-ace-complet", "avatar", "api", "NVIDIA ACE complet (Tokkio, NIM NVAIE)",
       Licence(code="NVIDIA AI Enterprise (NVAIE)", poids=None, usage_commercial="sur_contrat",
               service_tiers="incertain", integration="api", source=f"{R1} l.286"),
       "ecarte", raison_ecart="NVAIE requis et pas de fr-CA (FEUILLE r2 tableau A)"),
    _f("avatar.wav2lip", "avatar", "local", "Wav2Lip",
       Licence(code="Aucun LICENSE ; README « personal/research/non-commercial purposes »", poids="idem",
               usage_commercial="interdit", service_tiers="interdit", source=f"{R1} l.125, l.371 [V]"),
       "ecarte", raison_ecart="usage commercial « strictly prohibited » (FEUILLE r2 tableau A)"),
    _f("avatar.insightface", "avatar", "local", "Détecteurs InsightFace (LivePortrait)",
       Licence(code="MIT (LivePortrait)", poids="InsightFace : « non-commercial research purposes only »",
               usage_commercial="interdit", service_tiers="interdit", source=f"{R1} l.120, l.370 [V]"),
       "ecarte", raison_ecart="modèles InsightFace non commerciaux (FEUILLE r2 tableau A)"),
    _f("avatar.sadtalker", "avatar", "local", "SadTalker (dépendance BFM/3DMM)",
       Licence(code="Apache-2.0 sauf composants tiers", poids="BFM/3DMM non commerciale [H]",
               usage_commercial="interdit", service_tiers="interdit", source=f"{R1} l.124, l.373"),
       "ecarte", raison_ecart="dépendance BFM non commerciale, projet abandonné (FEUILLE r2 tableau A)"),
    _f("avatar.duix", "avatar", "local", "Duix-Mobile / Duix-Avatar",
       Licence(code="DUIX.COM Community License", poids="DUIX.COM Community License (embarque fish-speech)",
               usage_commercial="sur_contrat", service_tiers="incertain",
               mention_obligatoire="Powered by Duix.com", source=f"{R1} l.127-128, l.372 [V]",
               note="licence commerciale discrétionnaire au-delà de 1 000 MAU"),
       "ecarte", raison_ecart="licence discrétionnaire au-delà de 1 000 MAU et fish-speech embarqué"),
    # ---------------------------------------------------------------- Image (R5 §1.1, l.40-59, 145-176)
    _f("image.flux2-klein-4b.local", "image", "local", "FLUX.2 [klein] 4B (worker Diffusers)",
       _permissive("Apache-2.0", "Apache-2.0", f"{R5} l.42 [V]"), "adopte"),
    _f("image.qwen-image-2512.local", "image", "local", "Qwen-Image-2512 (worker Diffusers)",
       _permissive("Apache-2.0", "Apache-2.0", f"{R5} l.47 [V]"), "adopte"),
    _f("image.qwen-image-edit-2511.local", "image", "local", "Qwen-Image-Edit-2511",
       _permissive("Apache-2.0", "Apache-2.0", f"{R5} l.48 [V]"), "adopte"),
    _f("image.qwen-image-layered.local", "image", "local", "Qwen-Image-Layered (calques RGBA)",
       _permissive("Apache-2.0", "Apache-2.0", f"{R5} l.49 [V]"), "adopte"),
    _f("image.z-image-turbo.local", "image", "local", "Z-Image / Z-Image-Turbo (Tongyi)",
       _permissive("Apache-2.0", "Apache-2.0", f"{R5} l.51 [V]"), "adopte"),
    _f("image.seedvr2.local", "image", "local", "SeedVR2 3B/7B (agrandissement image et vidéo)",
       _permissive("Apache-2.0", "Apache-2.0", f"{R5} l.163 [V]"), "adopte"),
    _f("image.recraft-v4.1.api", "image", "api", "Recraft V4.1 (raster et SVG natif)",
       _api_contrat(f"{R5} l.171, l.226", "conditions d'utilisation à lire [I]"), "repli",
       residence_donnees="inconnue",
       cout_unitaire=Cout("image", "0.035", "USD", f"{R5} l.171 [V] (raster ; SVG 0,08 $)")),
    _f("image.flux3-image-klein.local", "image", "local", "FLUX 3 Image Klein (5,6B)",
       Licence(code=None, poids="FLUX Kommunity License v1.0", usage_commercial="sous_seuil",
               seuil_revenu_usd=5_000_000, service_tiers="incertain", verification="a_lire",
               source=f"{R5} l.44, l.103, l.489, l.574",
               note="« Qualifying Users » < 5 M$ US affiliés compris ; seul le résumé de la fiche HF a été lu"),
       "conditionnel"),
    _f("image.flux1-dev", "image", "local", "FLUX.1 [dev] / FLUX.2 [dev] / Kontext [dev] / klein 9B",
       Licence(code="Apache (dépôt flux) [S]", poids="FLUX [dev] Non-Commercial License v2.0",
               usage_commercial="interdit", service_tiers="interdit", source=f"{R5} l.40-43 [V]"),
       "ecarte", raison_ecart="poids non commerciaux sans licence payante BFL (FEUILLE r2 tableau A)"),
    _f("image.qwen-image-2.1", "image", "local", "Qwen-Image 2.1 / 2.1-Turbo",
       Licence(code=None, poids="Qwen Research License", usage_commercial="interdit", service_tiers="interdit",
               source=f"{R5} l.50 [V]"),
       "ecarte", raison_ecart="licence de recherche, sorties non couvertes (FEUILLE r2 tableau A)"),
    _f("image.bria-fibo-2.0-dev", "image", "local", "Bria Fibo 2.0-dev",
       Licence(code=None, poids="CC BY-NC 4.0 (commercial sur contrat Bria)", usage_commercial="interdit",
               service_tiers="interdit", source=f"{R5} l.56 [V]"),
       "ecarte", raison_ecart="poids non commerciaux en open source (FEUILLE r2 tableau A)"),
    # ---------------------------------------------------------------- Vidéo (R5 §2.1, l.188-205)
    _f("video.wan-2.2.local", "video", "local", "Wan 2.2 T2V/I2V-A14B, TI2V-5B (worker Diffusers)",
       _permissive("Apache-2.0", "Apache-2.0", f"{R5} l.188 [V]"), "adopte"),
    _f("video.hunyuanvideo-1.5", "video", "local", "HunyuanVideo 1.5",
       Licence(code="Tencent Hunyuan Community", poids="Tencent Hunyuan Community", usage_commercial="autorise",
               territoires_exclus=("UE", "UK", "KR"), service_tiers="incertain",
               mention_obligatoire="nommer le fournisseur réel (Tencent HunyuanVideo)", source=f"{R5} l.191 [V]",
               note="licence séparée au-delà de 100 M MAU ; droit de Hong Kong"),
       "ecarte", raison_ecart="clause territoriale UE, R.-U., Corée du Sud (FEUILLE r2 tableau A)"),
    _f("video.minimax-h3", "video", "local", "MiniMax H3 (33B, audio)",
       Licence(code=None, poids="MiniMax H3 Community License (2 août 2026)", usage_commercial="autorise",
               seuil_revenu_usd=20_000_000, territoires_exclus=("UE", "UK", "KR", "US"), service_tiers="incertain",
               mention_obligatoire="MiniMax H3", source=f"{R5} l.192 [V]",
               note="autorisation écrite au-delà de 20 M$ de CA"),
       "ecarte", raison_ecart="clause territoriale UE, R.-U., Corée du Sud, États-Unis (FEUILLE r2 tableau A)"),
    _f("video.remotion", "video", "local", "Remotion (vidéo par code)",
       Licence(code="Licence maison : gratuite ≤ 3 employés, sinon Company License", poids=None,
               usage_commercial="sur_contrat", service_tiers="interdit", source=f"{R5} l.205 [V]",
               note="revente d'un dérivé interdite ; Revideo (MIT) en alternative"),
       "ecarte", raison_ecart="licence maison, revente d'un dérivé interdite (FEUILLE r2 tableau A)"),
    # ---------------------------------------------------------------- Recherche web (R4 §GEO, l.243, 260, 449)
    _f("recherche_web.api-officielle", "recherche_web", "api",
       "API officielle avec recherche web (OpenAI, Perplexity Sonar, Gemini, Anthropic : noms exacts à vérifier)",
       _api_contrat(f"{R4} l.260 [H], l.498", "conditions d'utilisation du panel GEO à lire"), "adopte",
       residence_donnees="US"),
    _f("recherche_web.scraping-serp", "recherche_web", "api", "Scraping de Google ou des interfaces d'IA (SerpApi, …)",
       Licence(code="Conditions d'utilisation de Google et des IA", poids=None, usage_commercial="interdit",
               service_tiers="interdit", integration="api", source=f"{R4} l.243, l.449"),
       "ecarte", raison_ecart="contraire aux conditions d'utilisation ; litige Google c. SerpApi (FEUILLE r2)",
       residence_donnees="US"),
)


def par_identifiant() -> dict[str, Fournisseur]:
    index = {f.identifiant: f for f in CATALOGUE}
    assert len(index) == len(CATALOGUE), "identifiants du catalogue uniques"
    return index
