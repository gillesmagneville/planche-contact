# Changelog

Toutes les évolutions importantes de **Planche-Contact** seront documentées dans ce fichier.

Le projet suit autant que possible les recommandations de **Keep a Changelog** et du **Versioning Sémantique (SemVer)**.

## [Non publié]

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

### Modifié

- Filigrane unifié : un seul rendu (mosaïque, orientation, opacité) utilisé de façon strictement identique sur les planches, le PDF et la galerie HTML (auparavant, trois implémentations différentes coexistaient, avec un rendu visiblement différent selon la sortie).
- Filigrane par défaut plus discret : taille réduite (~30 %) et opacité réduite (70 % → 40 %).
- Fenêtre principale : ouverture à sa taille minimale naturelle plutôt qu'une taille fixe imposée, tout en restant redimensionnable.
- Regroupement de champs pour réduire la hauteur du formulaire : Titre du projet et Nom de l'auteur sur une même ligne ; Images par planche, Format de la planche, Filigrane et Orientation sur une même ligne.
- Champs Titre du projet, Nom de l'auteur, Dossier d'entrée et Dossier de sortie : largeur fixe et raisonnable au lieu de s'étirer sur toute la largeur de la fenêtre.
- Marge haute des planches contact et du PDF réduite, espace entre l'en-tête et la grille de vignettes agrandi.
- Chargement des polices rendu multiplateforme (Linux/Windows/macOS) au lieu d'un chemin Linux codé en dur.
- Nom du projet uniformisé en "Planche-Contact" (au lieu de "Planche-Contact Linux") dans le README et ce journal, le projet n'étant plus limité à Linux.

### Corrigé

- Dossier de sortie non créé automatiquement avant la génération, provoquant une erreur si le dossier n'existait pas encore.
- Permissions des fichiers embarqués dans le `.deb` dépendantes du `umask` de la machine de build, pouvant rendre l'application illisible pour un utilisateur normal une fois installée.
- Icône de l'application absente du `.deb` (le script cherchait un fichier à un chemin inexistant) ; installée désormais en plusieurs tailles (48 à 256 px).
- Fichier `VERSION` du projet pouvant être incrémenté même en cas d'échec de build, désynchronisant le numéro de version affiché du contenu réellement publié.
- Fenêtre principale agrandie de ~90 px juste après son affichage (le temps que l'aperçu du dossier d'entrée se charge), empêchant un centrage vertical correct par le gestionnaire de fenêtres à l'ouverture.

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

## À venir

### [1.2.2]

Première version stable officielle.
