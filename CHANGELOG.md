# Changelog

Toutes les évolutions importantes de **Planche-Contact** seront documentées dans ce fichier.

Le projet suit autant que possible les recommandations de **Keep a Changelog** et du **Versioning Sémantique (SemVer)**.

## [Non publié]

### Modifié

- Statut du portage Windows mis à jour : validé sur machine réelle, sans bug apparent, publié comme release officielle (`README.md`, `windows/README.md`, `PROJECT_CONTEXT.md`).

## [1.5.3] - 2026-08-03

### Ajouté

- Procédure de contournement de l'avertissement SmartScreen Windows à l'installation, documentée pour l'utilisateur final (`windows/README.md`, `README.md`, manuel utilisateur).
- Mention transparente de l'assistance de Claude.ai (Anthropic) à la conception du logiciel, dans le `README.md`, le manuel utilisateur et l'onglet « À propos » de l'application.

## [1.5.1] - 2026-08-03

### Ajouté

- Manuel utilisateur : note sur le respect automatique de l'orientation EXIF, mention que l'onglet Aide ouvre ce manuel, exemple CLI avec `--html-per-page`.

### Retiré

- Traces de diagnostic devenues inutiles : lignes `[DIAG]` dans `FolderPreviewController` (`planche-contact-gtk.py`) et fenêtre console de l'exécutable Windows (`console=True` dans `windows/planche-contact.spec`, repassé à `False`).

## [1.5.0] - 2026-08-02

Consolide l'ensemble des évolutions depuis la 1.2.2-rc.1 (portage Windows,
sélecteur de dossier personnalisé, filigrane unifié, RAW, curseur d'images
par page HTML, métadonnées AppStream, et tous les correctifs associés).

### Ajouté

- Prise en charge des fichiers RAW (`.cr2`, `.cr3`, `.nef`, `.dng`, `.arw`), via `rawpy` — installé et embarqué automatiquement dans le `.deb`, sans étape manuelle.
- Sélecteur de dossier personnalisé (entrée/sortie), en remplacement de la boîte de dialogue native : n'affiche que les dossiers, aperçu de 20 vignettes (2 lignes) sur le dossier survolé, fil d'Ariane cliquable, signets système repris dans la barre latérale.
- Bande d'aperçu du dossier d'entrée dans la fenêtre principale, paginée par lots de 10, avec navigation numérotée.
- Bouton "Afficher les résultats" (planches, PDF, galerie HTML, index CSV) ouvrant chaque élément avec l'application par défaut du système, avec message clair si aucune application n'est disponible pour le type de fichier concerné.
- Curseur d'opacité du filigrane dans l'interface (0-100 %, défaut 40 %), ainsi que l'argument `--watermark-opacity` en ligne de commande.
- En-tête des planches : nom du dossier source affiché par défaut quand aucun des champs Titre/Auteur/Filigrane n'est renseigné.
- Onglet "À propos" : mention de la licence GNU GPL v3, nom du développeur et lien vers le dépôt GitHub.
- Portage Windows 10/11 (`windows/`) : script de build PowerShell, fichier `.spec` PyInstaller, installeur NSIS, à partir du même code source que la version Linux (le moteur `portfolio/` est strictement identique ; l'interface graphique ne reçoit que quelques ajouts ciblés et sans effet sous Linux/macOS : bloc de démarrage indiquant à GTK4 où trouver ses bibliothèques embarquées, et repli sur `os.startfile` pour ouvrir un fichier avec l'application par défaut du système).
- Documentation utilisateur entièrement réécrite (`docs/planche-contact-manual.html`) et guide de build Windows dédié (`windows/README.md`).
- Curseur "Images par page" pour la galerie HTML dans l'interface (12 à 64 par pas de 4, sur la même ligne que la case "Générer Galerie HTML"), ainsi que l'argument `--html-per-page` en ligne de commande.
- Métadonnées AppStream (`metainfo/planche-contact.metainfo.xml`), installées dans `/usr/share/metainfo/` : permet à App Center (PackageKit + AppStream, depuis Ubuntu 26.04) de reconnaître pleinement le paquet.

### Modifié

- Filigrane unifié : un seul rendu (mosaïque, orientation, opacité) utilisé de façon strictement identique sur les planches, le PDF et la galerie HTML (auparavant, trois implémentations différentes coexistaient, avec un rendu visiblement différent selon la sortie).
- Filigrane par défaut plus discret : taille réduite (~30 %) et opacité réduite (70 % → 40 %).
- Fenêtre principale : ouverture à sa taille minimale naturelle plutôt qu'une taille fixe imposée, tout en restant redimensionnable.
- Regroupement de champs pour réduire la hauteur du formulaire : Titre du projet et Nom de l'auteur sur une même ligne ; Images par planche, Format de la planche, Filigrane et Orientation sur une même ligne.
- Champs Titre du projet, Nom de l'auteur, Dossier d'entrée et Dossier de sortie : largeur fixe et raisonnable au lieu de s'étirer sur toute la largeur de la fenêtre.
- Marge haute des planches contact et du PDF réduite, espace entre l'en-tête et la grille de vignettes agrandi.
- Chargement des polices rendu multiplateforme (Linux/Windows/macOS) au lieu d'un chemin Linux codé en dur.
- Nom du projet uniformisé en "Planche-Contact" (au lieu de "Planche-Contact Linux") dans le README et ce journal, le projet n'étant plus limité à Linux.
- Bouton "Planches contact" du menu "Afficher les résultats" : ouvre désormais le dossier `planches/` (gestionnaire de fichiers) plutôt qu'une image individuelle — comportement identique quel que soit le nombre de planches générées.

### Corrigé

- Dossier de sortie non créé automatiquement avant la génération, provoquant une erreur si le dossier n'existait pas encore.
- Permissions des fichiers embarqués dans le `.deb` dépendantes du `umask` de la machine de build, pouvant rendre l'application illisible pour un utilisateur normal une fois installée.
- Icône de l'application absente du `.deb` (le script cherchait un fichier à un chemin inexistant) ; installée désormais en plusieurs tailles (48 à 256 px).
- Fichier `VERSION` du projet pouvant être incrémenté même en cas d'échec de build, désynchronisant le numéro de version affiché du contenu réellement publié.
- Fenêtre principale agrandie de ~90 px juste après son affichage (le temps que l'aperçu du dossier d'entrée se charge), empêchant un centrage vertical correct par le gestionnaire de fenêtres à l'ouverture.
- Police embarquée non appliquée sur les planches contact ni le PDF (fonctionnait uniquement pour la galerie HTML) : l'en-tête et le pied de page des planches chargeaient un chemin de police codé en dur au lieu de passer par `utils.get_font()`.
- Galerie HTML : orientation EXIF non respectée, toutes les photos affichées en paysage à la taille du capteur quel que soit leur cadrage réel — `ImageOps.exif_transpose()` n'était plus appelé depuis le passage au décodage unique (image pleine taille + vignette).
- `.deb` : les scripts `postinst`/`postrm` n'étaient en réalité jamais exécutés par dpkg (ils atterrissaient comme simples fichiers de données inertes à `/DEBIAN/`, `fpm` ne reconnaissant pas ce dossier comme `dpkg-deb --build` natif le ferait) — aucune vérification de l'environnement Python embarqué n'avait donc jamais lieu à l'installation.
- `.deb` : venv embarqué pouvant être incomplet (ex : `reportlab` manquant) selon ce qui se trouvait déjà installé au niveau système sur la machine de build, `pip install` sautant silencieusement la copie locale dans un venv `--system-site-packages` sans `--ignore-installed`.
- Windows : taille de l'application non affichée dans *Paramètres > Applications > Applications installées* — `IntFmt $0 "0xX" $0` (syntaxe NSIS 2.x non fonctionnelle en NSIS 3.x) ne convertissait pas la taille calculée en hexadécimal, `EstimatedSize` retombait systématiquement à 0.

### Performances

- Décodage des vignettes et planches nettement accéléré : préférence donnée à l'aperçu JPEG déjà embarqué dans les fichiers RAW plutôt qu'un dématriçage complet, et décodage "draft" accéléré pour les sources JPEG.
- Galerie HTML : fusion de deux passes de décodage redondantes en une seule (vignette dérivée de l'image déjà décodée, plus besoin de redécoder la source deux fois), génération pleinement parallélisée.
- Plafond de processus parallèles relevé (8 → 64), pour mieux exploiter les machines à nombreux cœurs.
- Mise en cache du chargement des polices du filigrane, rechargées depuis le disque à chaque appel auparavant.

---

## [1.2.2-rc.1] - 2026-07-23

### Première Release Candidate publique

#### Fonctionnalités

- Génération de planches contact photographiques haute qualité (300 dpi).
- Interface graphique GTK 4.
- Génération d'un document PDF.
- Génération d'une galerie HTML responsive.
- Génération d'un index CSV.
- Prise en charge des images JPEG ainsi que de nombreux formats RAW.

#### Points forts

- Fonctionnement sans base de données.
- Traitement direct des dossiers d'images.
- Interface graphique simple et rapide.
- Logiciel libre distribué sous licence GPL-3.0.

---

## [1.2.1] - 2026-07-22

- Modification de l'onglet "À propos" et amélioration de `build-deb.sh`.
- Correction du numéro de version affiché dans le `.deb` et dans l'onglet "À propos".

## [1.2.0] - 2026-07-22

- Nettoyage des champs de l'interface, correction de l'orientation du filigrane, ajout du symbole copyright au filigrane.

## [1.1.20] - 2026-07-22

- Changement du nombre d'images par planche, ajout d'une mention en bas de page sur les planches, correction de l'orientation du filigrane, amélioration du script de build.

## [1.1.17] - 2026-07-22

- Effacement de la galerie avant une nouvelle génération.

## [1.1.16] - 2026-07-22

- Optimisation de la génération de la galerie et de la navigation.

## [1.1.11] - 2026-07-22

- Précision dans la description.
- Amélioration des indicateurs de progression.

## [1.1.10] - 2026-07-17

- Amélioration de la galerie : filigrane, format des photos, mise en page.

## [1.1.8] - 2026-07-16

- Optimisation du filigrane de la galerie.

## [1.1.5] - 2026-07-16

- Correctif sur la galerie.

## [1.1.3] - 2026-07-16

- Optimisation de la création de la galerie et nouveau script `build-deb.sh`.

## [1.1.2] - 2026-07-16

- Premier import du projet sous sa forme actuelle.

## [1.0.1] - 2026-07-15

### Version initiale publique

- Ajout de l'interface graphique GTK4.
- Ajout de l'export PDF et HTML.
- Packaging Debian amélioré.
