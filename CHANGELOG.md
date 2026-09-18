# Changelog

Toutes les évolutions importantes de **Planche-Contact** seront documentées dans ce fichier.

Le projet suit autant que possible les recommandations de **Keep a Changelog** et du **Versioning Sémantique (SemVer)**.

## [Non publié]

### Ajouté

- Galerie HTML : clic sur une vignette ouvre désormais une visionneuse plein écran avec navigation précédent/suivant (flèches ‹ › ou clavier, fermeture par Échap ou clic en dehors), au lieu d'ouvrir chaque image dans un nouvel onglet.
- Visionneuse de la galerie HTML enrichie : indicateur de la page contenant la photo affichée, champ « aller à la page », nom du fichier affiché, bouton de téléchargement, panneau d'informations (résolution réelle d'origine, taille du fichier, date de prise de vue), bascule plein écran (raccourcis clavier `I` et `F` en plus des boutons).
- Visionneuse de la galerie HTML : zoom de 50 % à 200 % par pas de 10 % (boutons +/-, clic sur le pourcentage pour réinitialiser, raccourcis clavier `+`/`-`/`0`), réinitialisé automatiquement à chaque changement de photo.
- Visionneuse de la galerie HTML : navigation photo suivante/précédente à la molette de la souris ; zoom à la molette avec Ctrl, Alt ou Cmd maintenu (sans déclencher le zoom natif du navigateur ni faire défiler la page en arrière-plan).
- **Interface graphique traduite en anglais, allemand et espagnol** (en plus du français), avec un sélecteur de langue dans un dialogue Préférences accessible depuis un nouveau menu (bouton hamburger dans la barre de titre) : Langue système (par défaut, repli sur l'anglais avec avertissement si la langue détectée n'est pas disponible), English, Français, Deutsch, Español. Un changement de langue prend effet au redémarrage de l'application.
- **Le CLI (`portfolio.py`) et la galerie HTML générée sont également traduits** dans les 4 langues : nouvelle option `--language` (résolue avant la construction du parser, pour que `--help` s'affiche déjà dans la bonne langue), tous les messages de progression et d'aide traduits, et l'intégralité de la galerie HTML générée (en-tête, navigation, visionneuse, `<html lang="...">`). L'interface graphique transmet automatiquement sa langue active au sous-processus de génération, pour que la galerie produite corresponde toujours à la langue affichée à l'écran.
- **Le manuel utilisateur est traduit dans les 4 langues** (`docs/planche-contact-manual.{en,de,es}.html`, en plus de la version française existante) : l'onglet Aide ouvre désormais la version correspondant à la langue active de l'application, avec repli sur le français si le fichier de cette langue est absent. L'internationalisation du projet est ainsi complète — interface graphique, CLI, galerie HTML générée et manuel.
- Galerie HTML : ajout d'une mention développeur/licence (« Développé par Gilles MAGNEVILLE, sous licence GNU GPL v3 », traduite dans les 4 langues) sous « Galerie générée par Planche-Contact » en pied de chaque page.
- « Afficher les résultats » est désormais opérant sur des résultats déjà présents dans le dossier de sortie (planches, PDF, galerie HTML, index CSV d'une session précédente), sans obliger à relancer une génération pour les rouvrir : vérifié au changement du champ dossier de sortie et au démarrage si un dossier était mémorisé. La génération reste bien sûr toujours possible si souhaitée.

### Modifié

- Statut du portage Windows mis à jour : validé sur machine réelle, sans bug apparent, publié comme release officielle (`README.md`, `windows/README.md`, `PROJECT_CONTEXT.md`).
- Sélecteur de langue déplacé de l'onglet À propos vers un nouveau dialogue Préférences, accessible par un menu (bouton hamburger dans la barre de titre) : l'onglet À propos redevient purement informatif, un réglage n'ayant logiquement rien à y faire.

### Corrigé

- Récursivité sous Windows : les images déjà générées lors d'une exécution précédente (`planches/`, `gallery/`) pouvaient être re-détectées comme photos sources (ex : 185 images comptées pour 60 réelles), l'exclusion basée sur une comparaison textuelle des chemins (`Path.resolve()` + `relative_to()`) échouant lorsqu'un même dossier physique est atteint par deux chemins textuellement différents — cas typique d'un lecteur réseau mappé vs son équivalent en chemin UNC. Comparaison désormais basée sur l'identité réelle du fichier (`os.path.samefile()`), bornée au dossier d'entrée pour éviter un appel système par niveau jusqu'à la racine du système de fichiers sur chaque photo (sensible sur un partage réseau).
- Galerie HTML : filigrane parfois tronqué en bas des vignettes (mosaïque à taille de police fixe appliquée séparément sur un canevas ~6x plus petit que l'image pleine taille, produisant un motif disproportionné selon la hauteur exacte de chaque photo). La vignette est désormais dérivée par simple redimensionnement de l'image pleine taille déjà filigranée, garantissant un rendu identique (juste réduit).
- Barre de progression de l'interface graphique : dépendait en partie d'une ligne de texte en français (« Planche X/Y ») imprimée par le CLI, ce qui l'aurait cassée dans toute autre langue. Retirée avant de traduire le CLI — redondante de toute façon avec le marqueur `PROGRESS:X/100` (jamais traduit) qui suit immédiatement chaque planche générée.
- **Régression** : les boutons « Choisir... » (dossiers d'entrée et de sortie) n'ouvraient plus le sélecteur de dossier, sans aucun message d'erreur visible. Cause : `_choose_folder()` utilisait `_` comme variable jetable (`uri, _, label = line.partition(" ")`, lecture des signets GTK) dans la même méthode qui appelle par ailleurs `_("...")` pour traduire le titre du dialogue — Python traite alors `_` comme local à toute la fonction, provoquant un `UnboundLocalError` à chaque clic, silencieusement avalé par PyGObject. Variable renommée en `_sep` ; vérifié qu'aucune autre fonction du fichier ne cumule les deux usages (analyse AST systématique, pas seulement celle qui posait problème).
- Visionneuse de la galerie HTML : les flèches précédent/suivant (et la molette, et le clavier) bouclaient sur les seules photos de la page en cours au lieu de passer réellement à la photo suivante/précédente lorsqu'elle se trouve sur une autre page. La navigation franchit désormais les pages (avec bouclage sur l'ensemble de la galerie aux deux extrémités), en ouvrant automatiquement la bonne photo à l'arrivée sur la page suivante/précédente, avec un message d'avertissement (traduit dans les 4 langues) lorsque ce franchissement boucle sur l'ensemble de la galerie plutôt qu'un simple changement de page.
- Changer de langue dans l'onglet À propos sans redémarrer l'application ne mettait pas à jour la langue réellement transmise au sous-processus de génération (`self._language` restait bloquée sur la langue de démarrage, malgré la préférence sauvegardée correctement) : une génération lancée aussitôt après un changement de langue repartait avec l'ancienne langue. Détecté en testant explicitement ce scénario.
- Visionneuse de la galerie HTML : le bouton de téléchargement ouvrait l'image dans l'onglet en cours (ou un nouvel onglet) au lieu de déclencher la boîte de dialogue d'enregistrement du navigateur. Corrigé en passant par un `Blob` (`fetch()` + `URL.createObjectURL()`) plutôt que le simple attribut HTML `download`, peu fiable une fois servi via HTTP(S) selon les navigateurs — vérifié avec un vrai Chromium (Playwright), téléchargement effectif et fichier de taille identique à l'original. **Limite restante, non contournable** : si la galerie est ouverte directement en `file://` (double-clic sur `index.html`), Firefox et Chrome bloquent de façon identique toute solution JavaScript (`fetch`, `XMLHttpRequest`, lecture d'un `<canvas>`) pour accéder à un fichier voisin, depuis un correctif de sécurité largement adopté (CVE-2019-11730) — un message explicatif s'affiche alors, invitant à un clic droit « Enregistrer l'image sous » ou à consulter la galerie via un serveur web pour un téléchargement en un clic.
- Visionneuse de la galerie HTML : une fois l'image zoomée, la barre du haut (nom du fichier, actions) disparaissait derrière elle au lieu de rester visible au premier plan (`transform: scale()` fait de l'image un élément "positionné" qui se met alors à primer sur les barres fixes selon l'ordre du DOM) ; le défilement pour se déplacer dans l'image agrandie ne fonctionnait pas et affectait la page en arrière-plan à la place (chaînage de défilement par défaut d'un conteneur qui n'a lui-même rien à défiler). Corrigé en donnant un `z-index` explicite à chaque barre/bouton de la visionneuse, en ajoutant `overscroll-behavior: contain`, et en remplaçant le zoom par de vraies largeur/hauteur en pixels (`transform` ne change que le rendu visuel, jamais la taille de mise en page prise en compte par le défilement) — les trois vérifiés avec un vrai Chromium (Playwright).
- Tri par date EXIF (photos JPEG/PNG, non RAW) : `DateTimeOriginal`/`DateTimeDigitized` n'étaient en réalité jamais lus (ces tags vivent dans un sous-IFD Exif séparé, inaccessible via `Image.getexif().get()` direct), le tri retombait donc silencieusement sur la date de modification du fichier depuis le début. Découvert en ajoutant l'affichage de la date dans la nouvelle visionneuse, qui l'a rendu visible.

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
