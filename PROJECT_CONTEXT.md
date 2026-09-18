# Planche-Contact — Contexte du projet

Ce document sert de référence technique complète pour quiconque (humain ou
IA) reprend ce projet. Il couvre l'ensemble du projet : le moteur commun,
l'interface graphique, et les deux portages (Linux et Windows).

---

## 1. But du logiciel

**Planche-Contact** est un outil léger permettant de générer des planches
contact photographiques de haute qualité (300 dpi) à partir d'un dossier de
photos, sans base de données ni catalogue.

À partir d'un même dossier source, l'outil produit au choix :
- des **planches contact** (JPEG, une ou plusieurs pages) ;
- un **PDF** assemblant toutes les planches ;
- une **galerie HTML** paginée et autonome, avec vignettes cliquables ;
- un **index CSV** listant chaque photo avec son numéro.

Deux façons de l'utiliser :
- **Interface graphique GTK4** (`planche-contact-gtk.py`)
- **Ligne de commande** (`portfolio/portfolio.py`)

Formats de photos pris en charge : JPEG, PNG, TIFF, BMP, WEBP, HEIC/HEIF, et
RAW (CR2, CR3, NEF, DNG, ARW).

Plateformes : Linux (Debian/Ubuntu, paquet `.deb`) et Windows 10/11 (portable
`.zip` ou installeur `.exe`) — même code source, packaging séparé.

---

## 2. Architecture

### 2.1 Principe général

Le projet est structuré en **deux couches strictement séparées** :

1. **Le moteur (`portfolio/`)** : 100 % Python pur, aucune dépendance à
   l'interface graphique. Utilisable seul en CLI. C'est cette couche qui est
   *entièrement partagée* entre Linux et Windows, sans aucune adaptation.
2. **L'interface graphique (`planche-contact-gtk.py`)** : GTK4 (PyGObject),
   un seul fichier. Elle appelle le moteur soit en l'import direct (aperçus),
   soit en sous-processus (génération, pour ne jamais geler l'interface).

Le packaging (`.deb` d'un côté, `.exe`/`.zip` de l'autre) est la **seule**
partie réellement dupliquée entre les deux plateformes — et encore, les deux
scripts de build suivent la même logique (gestion de version, confirmation
interactive, options `-Major/-Minor/-Patch`).

### 2.2 Le moteur (`portfolio/`)

| Module | Rôle |
|---|---|
| `config.py` | Dataclass `Config` : tous les paramètres d'une génération |
| `scanner.py` | Scan du dossier (récursif ou non), tri par date EXIF ou nom (délègue à `utils.get_exif_date()`), exclut `planches/` et `gallery/` du dossier de sortie configuré pour éviter de re-scanner ses propres fichiers générés (comparaison par identité réelle de fichier via `os.path.samefile()`, pas par texte — voir §5) |
| `rawloader.py` | Chargement unifié image/RAW : aperçu JPEG embarqué en priorité (rapide), dématriçage complet (`rawpy`) uniquement si cet aperçu est absent ou trop petit ; `get_original_dimensions()` : résolution réelle d'origine (métadonnées seules, orientation EXIF/RAW appliquée), utilisée par la visionneuse de la galerie HTML |
| `thumbnail.py` | Génération de vignettes en parallèle (`ProcessPoolExecutor`, contexte `spawn` forcé) |
| `contactsheet.py` | Génère les planches contact (en-tête, grille de vignettes, pied de page, numéro de page) |
| `pdfexport.py` | Assemble les planches en PDF (`reportlab`) ; marge haute réduite indépendamment des autres marges |
| `htmlgallery.py` | Galerie HTML paginée ; **une seule passe de décodage** par photo (la vignette est dérivée de l'image pleine taille déjà décodée, pas un second décodage) ; `ImageOps.exif_transpose()` appliqué systématiquement pour respecter l'orientation (voir §5) ; filigrane appliqué **une seule fois** sur l'image pleine taille, la vignette étant dérivée par redimensionnement de cette version déjà filigranée (voir §5, évite un motif disproportionné/tronqué) ; visionneuse plein écran en JS vanilla intégrée à chaque page générée (précédent/suivant **franchissant les pages** avec bouclage sur l'ensemble de la galerie (avertissement affiché aux deux extrémités, voir §5), clavier, molette de la souris, sans dépendance externe) avec indicateur de page, saut direct à une page, nom du fichier, téléchargement (via blob, voir §5 — dégradé en `file://`), panneau d'informations (résolution/taille/date, calculées par le worker en même temps que l'image), zoom 50-200 % en largeur/hauteur réelles (boutons, clavier, Ctrl/Alt+molette — voir §5, jamais `transform: scale()`, réinitialisé à chaque changement de photo) et bascule plein écran (`Fullscreen API`) ; pied de page avec mention développeur/licence ; **entièrement traduite** dans la langue active au moment de la génération (`<html lang="...">` compris), via `i18n.py` |
| `csvindex.py` | Génère l'index CSV |
| `utils.py` | `get_font()` (police embarquée, mise en cache), `apply_watermark()` (filigrane en mosaïque, **fonction unique** utilisée par les planches, le PDF et la galerie), `get_exif_date()` (date de prise de vue, RAW compris — **fonction unique** utilisée par le tri de `scanner.py` et les informations de la visionneuse de `htmlgallery.py`), `format_file_size()`, `setup_logging()` |
| `i18n.py` | Internationalisation de **l'interface graphique, du CLI et de la galerie HTML générée** (voir §5) : `_()`, `set_language()`, `get_language()`, `detect_system_language()`. Dictionnaires Python (`locales/{fr,en,de,es}.py`), pas gettext/.po/.mo — aucune étape de compilation ni dépendance supplémentaire à empaqueter |
| `portfolio.py` | Point d'entrée CLI (`argparse`), orchestre tout ce qui précède, affiche des lignes `PROGRESS:X/100 message` sur stdout (lues par l'interface graphique — préfixe volontairement jamais traduit, voir §5) ; `--language` résolu *avant* la construction du parser pour que `--help` s'affiche déjà dans la bonne langue |
| `fonts/` | Police DejaVu Sans (normale + gras) embarquée avec le projet — licence Bitstream Vera, redistribution autorisée |

### 2.3 L'interface graphique (`planche-contact-gtk.py`)

Un seul fichier, structuré autour de la classe `PlancheContactGTK(Gtk.Application)`.

Composants principaux :
- **Formulaire de génération** : titre/auteur, dossiers d'entrée/sortie,
  images par planche, format de page, filigrane (texte, orientation,
  curseur d'opacité), cases PDF/HTML/CSV, curseur d'images par page pour la
  galerie HTML (12 à 64 par pas de 4, sur la même ligne que la case
  "Générer Galerie HTML").
- **Sélecteur de dossier personnalisé** (`_choose_folder`) : entièrement
  construit à la main (`Gtk.DirectoryList` + `Gtk.FilterListModel` +
  `Gtk.CustomFilter`), pas la boîte de dialogue native (peu fiable selon
  les systèmes). Barre latérale (dossier personnel, signets GTK sur Linux,
  liste des lecteurs sous Windows), fil d'Ariane cliquable, champ de
  saisie directe de chemin (utile pour les partages réseau), panneau
  d'aperçu avec pagination.
- **`FolderPreviewController`** : classe réutilisable pour l'aperçu à
  vignettes (bande horizontale dans la fenêtre principale, grille dans le
  sélecteur de dossier), scan en arrière-plan (thread) + notification du
  thread principal via `glib_idle_add()`.
- **Génération** : construit une commande et la lance via
  `subprocess.Popen`, lit stdout ligne à ligne pour la barre de
  progression et le journal.
- **Menu "Afficher les résultats"** : ouvre chaque livrable avec
  l'application par défaut du système (`Gio.AppInfo` sur Linux/macOS,
  `os.startfile()` sur Windows), avec fenêtre d'avertissement claire si
  aucune application n'est configurée. Les planches contact ouvrent le
  **dossier** `planches/` (gestionnaire de fichiers), pas un fichier
  individuel — comportement identique quel que soit le nombre de planches
  générées, contrairement à l'ancienne approche (visionneuse multi-images
  avec repli sur la première planche seule).
- **`glib_idle_add()`** : enveloppe autour de `GLib.idle_add()` tolérante à
  deux conventions d'appel différentes selon la plateforme/le binding (voir
  §6, bug PyGObject/Windows).
- **Sélecteur de langue** : dans un dialogue **Préférences** (`_open_preferences()`), accessible via le bouton menu (icône hamburger,
  `open-menu-symbolic`) de la barre de titre — **pas** dans l'onglet À
  propos, qui reste volontairement purement informatif (version, licence,
  crédits) ; un réglage n'a logiquement rien à y faire (retour du
  mainteneur). Options : Langue système (par défaut,
  repli sur l'anglais avec avertissement si non supportée), English,
  Français, Deutsch, Español. Un changement ne prend effet qu'au
  redémarrage — reconstruire tout l'arbre de widgets à la volée serait un
  chantier bien plus lourd pour une préférence qu'on change rarement (voir
  §5, `portfolio/i18n.py`). **Portée** : le CLI (`portfolio.py`, via
  `--language`, transmis automatiquement par l'interface graphique lors
  du lancement du sous-processus de génération) et la galerie HTML
  générée sont traduits dans la même langue. Le manuel utilisateur
  (`docs/planche-contact-manual.{en,de,es}.html`) l'est également —
  l'onglet Aide ouvre la version correspondant à la langue active, avec
  repli sur le français si le fichier de cette langue est absent.

---

## 3. Arborescence

```
planche-contact/
├── planche-contact-gtk.py          # Interface GTK4 (commune Linux/Windows)
├── planche-contact-gtk             # Wrapper de lancement (Linux)
├── build-deb.sh                    # Build du paquet .deb (Linux)
├── build-windows.ps1               # Relais racine -> windows/build-windows.ps1
│
├── portfolio/                      # Moteur, 100 % partagé
│   ├── __init__.py
│   ├── config.py
│   ├── scanner.py
│   ├── rawloader.py
│   ├── thumbnail.py
│   ├── contactsheet.py
│   ├── pdfexport.py
│   ├── htmlgallery.py
│   ├── csvindex.py
│   ├── utils.py
│   ├── i18n.py                     # Traduction de l'interface graphique uniquement
│   ├── locales/                    # fr.py (source), en.py, de.py, es.py
│   ├── portfolio.py
│   └── fonts/
│       ├── DejaVuSans.ttf
│       ├── DejaVuSans-Bold.ttf
│       └── LICENSE.txt
│
├── debian/                         # Empaquetage Linux (.deb) uniquement
│   ├── control, compat, copyright, rules
│   ├── postinst                    # Vérifie l'environnement Python embarqué à l'installation
│   └── postrm
│
├── windows/                        # Empaquetage Windows uniquement
│   ├── build-windows.ps1           # Script de build réel
│   ├── planche-contact.spec        # Config PyInstaller (embarque GTK4 + gi.overrides)
│   ├── installer.nsi               # Script NSIS (installeur .exe)
│   └── README.md                   # Prérequis, dépannage, détail du pipeline
│
├── metainfo/
│   └── planche-contact.metainfo.xml # Métadonnées AppStream (App Center, PackageKit)
│
├── docs/
│   ├── planche-contact-manual.html    # Manuel utilisateur complet (français, référence)
│   ├── planche-contact-manual.en.html
│   ├── planche-contact-manual.de.html
│   └── planche-contact-manual.es.html
├── screenshots/
│   └── application-icon.png        # Source de l'icône (convertie par chaque script de build)
│
├── requirements.txt
├── VERSION                         # Numéro de version unique, partagé par les deux scripts de build
├── README.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE                         # GNU GPL v3
└── PROJECT_CONTEXT.md              # Ce fichier
```

**Note** : `docs/screenshots/` n'existe plus depuis longtemps (retiré du
dépôt), il ne faut plus le mentionner comme faisant partie de
l'arborescence. `portfolio/Utilisation` a été corrigé (seul `--background`
était réellement obsolète parmi ses arguments d'exemple ; `--thumb` existe
bel et bien dans `portfolio.py` actuel).

---

## 4. Dépendances

### 4.1 Communes (moteur, `requirements.txt`)

| Paquet | Version | Rôle |
|---|---|---|
| Pillow | ≥ 10.0 | Traitement d'image |
| reportlab | ≥ 4.0 | Génération PDF |
| rawpy | ≥ 2.24 | Décodage RAW (bundle LibRaw). Optionnel : sans lui, les RAW sont ignorés avec un avertissement |
| exifread | ≥ 3.0 | Lecture EXIF des fichiers RAW (PIL ne le sait pas faire) |
| PyGObject (`gi`) | — | Liaisons GTK4. Non installable de façon fiable via pip : paquet système sur Linux (`python3-gi`), roues gvsbuild sur Windows |

### 4.2 Spécifiques Linux

- `python3-gi`, `gir1.2-gtk-4.0` (paquets système, prérequis avant d'utiliser l'interface graphique depuis les sources)
- `fpm` (gem Ruby) pour la construction du `.deb`
- `python3-exifread` (apt) + `rawpy` (pip) installés automatiquement dans le venv embarqué par `build-deb.sh`
- `metainfo/planche-contact.metainfo.xml` (métadonnées AppStream), installé par `build-deb.sh` dans `/usr/share/metainfo/` — nécessaire pour qu'App Center (PackageKit + AppStream, depuis Ubuntu 26.04) reconnaisse pleinement le paquet (taille, description enrichie) au lieu de se limiter au `.desktop`

### 4.3 Spécifiques Windows

- Python **doit correspondre exactement** à la version ciblée par la
  dernière publication gvsbuild (actuellement Python 3.14 — voir §6, cette
  contrainte évolue à chaque nouvelle publication de gvsbuild)
- [gvsbuild](https://github.com/wingtk/gvsbuild) : pile GTK4 précompilée
  pour Windows (téléchargée et installée automatiquement dans `C:\gtk` par
  `build-windows.ps1` si absente)
- PyInstaller (gèle l'application en `.exe`)
- NSIS (génère l'installeur `.exe` — facultatif, sinon seule la version
  portable `.zip` est produite)
- winget (utilisé pour l'installation automatique de NSIS/Python si absents)

---

## 5. Conventions de codage

- **Langue** : identifiants de code (variables, fonctions, classes) en
  anglais ; commentaires et toutes les chaînes visibles par l'utilisateur
  (interface, messages, documentation) en français.
- **Commentaires explicatifs** : systématiquement utilisés pour documenter
  le *pourquoi* d'un choix non évident (contournement spécifique à une
  plateforme, bug d'un binding, etc.), pas seulement le *quoi*.
- **`multiprocessing`** : toujours avec le contexte `spawn` explicite
  (`multiprocessing.get_context("spawn")`), y compris sur Linux — jamais
  `fork` (deadlock connu entre `rawpy`/OpenMP et `fork`).
- **Chargement de police** : toujours via `utils.get_font()` (mise en
  cache, police embarquée en priorité) — jamais de chemin de police codé
  en dur ailleurs dans le code.
- **Orientation EXIF** : toujours appliquer `ImageOps.exif_transpose()`
  juste après `rawloader.load_image()`, avant tout traitement ultérieur
  (redimensionnement, filigrane...) — y compris dans les chemins de
  décodage optimisés/fusionnés (voir `CHANGELOG.md`, bug corrigé sur la
  galerie HTML qui avait perdu cet appel lors du passage au décodage
  unique).
- **Filigrane sur une image ET sa vignette dérivée** : toujours filigraner
  la version pleine taille en premier, puis dériver la vignette par
  redimensionnement de cette version déjà filigranée — jamais appliquer
  `apply_watermark()` séparément sur les deux tailles. La mosaïque utilise
  une taille de police et un espacement fixes en pixels (voir `utils.py`),
  pensés pour les grandes tailles (planches, PDF, images "pleine taille"
  de la galerie) ; appliqués tels quels sur un canevas nettement plus
  petit (ex : vignette 400px), le motif devient disproportionné et peut
  se retrouver tronqué en bas selon la hauteur exacte de l'image (voir
  `CHANGELOG.md`, bug corrigé sur la galerie HTML).
- **`pip install` dans le venv embarqué (Linux, `build-deb.sh`)** :
  toujours avec `--ignore-installed`. Le venv est créé avec
  `--system-site-packages` ; sans ce flag, `pip` saute silencieusement la
  copie locale d'un paquet déjà visible au niveau système sur la machine
  de build, produisant un venv qui fonctionne par accident sur cette
  machine mais est réellement incomplet une fois le `.deb` installé
  ailleurs (voir `CHANGELOG.md`).
- **Comparaison de chemins (exclusion de dossiers)** : toujours comparer
  l'identité réelle du fichier via `os.path.samefile()`, jamais une
  comparaison textuelle (`Path.resolve()` + `relative_to()`/`==`). Un même
  dossier physique peut avoir plusieurs représentations textuelles
  différentes selon le chemin emprunté — un lecteur réseau mappé
  (`Z:\photos`) et son équivalent en chemin UNC
  (`\\serveur\partage\photos`) sous Windows en sont l'exemple le plus
  courant. `Path.resolve()` ne les unifie pas, contrairement à
  `os.path.samefile()` (voir `CHANGELOG.md`, bug de récursivité sous
  Windows). `os.path.samefile()` fait un appel système par comparaison :
  toujours borner la remontée des dossiers parents (paramètre `boundary`
  de `_is_within()` dans `scanner.py`) plutôt que de remonter jusqu'à la
  racine du système de fichiers à chaque fichier — sensible sur un
  partage réseau.
- **Date EXIF (formats standards, non RAW)** : toujours passer par
  `utils.get_exif_date()`, jamais par `Image.getexif().get()` direct pour
  `DateTimeOriginal`/`DateTimeDigitized` (tags `0x9003`/`0x9004`). Ces
  deux tags vivent dans un **sous-IFD Exif séparé** (pointé par le tag
  `0x8769` de l'IFD0), jamais dans l'IFD0 principal : `exif.get(0x9003)`
  renvoie toujours `None`, il faut passer par
  `exif.get_ifd(0x8769).get(0x9003)`. Seul `DateTime` (`0x0132`, date de
  *modification* du fichier, moins pertinente qu'une date de prise de
  vue) vit dans l'IFD0 et reste accessible directement. Ce bug affectait
  silencieusement le tri par date depuis le début (repli sur la date de
  modification du fichier) - découvert en ajoutant l'affichage de la
  date dans la visionneuse de la galerie HTML, qui l'a rendu visible
  (voir `CHANGELOG.md`).
- **Zoom de la visionneuse (galerie HTML) : jamais `transform: scale()`,
  toujours de vraies largeur/hauteur en pixels** (`applyZoom()` dans
  `htmlgallery.py`). Trois pièges rencontrés en le découvrant, dans
  l'ordre où ils se révèlent :
  1. **`transform` crée un nouveau contexte d'empilement.** Un élément
     transformé (même juste `scale()`) est traité comme "positionné" pour
     l'empilement visuel — il se met alors à passer devant les barres
     `position: fixed` de la visionneuse (z-index auto, départagé par
     l'ordre du DOM) au lieu de rester dessous. Confirmé avec
     `document.elementFromPoint()` sur un vrai Chromium (Playwright).
     Solution : `z-index` explicite sur chaque barre/bouton de la
     visionneuse (10, ou 20 pour les panneaux qui doivent passer devant
     même la barre du haut) plutôt que de compter sur l'ordre du DOM.
  2. **`transform` ne change QUE le rendu visuel, jamais la taille de
     mise en page.** Une image visuellement zoomée à 200 % via
     `transform: scale(2)` ne fait grossir ni son `offsetWidth`, ni le
     `scrollHeight` de son conteneur : rien ne "dépasse" au sens de
     `overflow`, donc rien n'est réellement défilable même si l'écran
     laisse penser le contraire. Solution : fixer `width`/`height` en
     pixels calculés, jamais `transform`, pour que le débordement soit
     réel et défilable.
  3. **`max-width`/`max-height` plafonnent silencieusement toute
     largeur/hauteur fixée par ailleurs**, y compris en style inline
     JavaScript — la taille réellement rendue reste bornée à ces valeurs
     quelle que soit la valeur de `width`/`height` demandée. Piège
     découvert en corrigeant le point 2 : mettre `width: 1472px` en JS ne
     servait à rien tant que `max-width: 92vw` (utilisé pour l'ajustement
     à 100 %) restait actif. Solution : neutraliser explicitement
     `max-width`/`max-height` (`style.maxWidth = 'none'`) dès que le zoom
     dépasse 100 %, et les restaurer (`= ''`, pour laisser le CSS
     reprendre la main) au retour à 100 %.
  4. **Un centrage flex classique masque le débordement en haut/à
     gauche, hors d'atteinte du défilement**, même une fois 1-3 résolus —
     seul le débordement bas/droite serait "révélé" au défilement.
     Solution, complémentaire aux trois précédentes : basculer
     dynamiquement vers `align-items: flex-start; justify-content:
     flex-start` (classe `.zoomed`) dès que le zoom dépasse 100 %, pour
     que la totalité du contenu agrandi reste atteignable au défilement.
- **Chaînage de défilement (molette qui "fuit" vers la page derrière une
  visionneuse plein écran)** : un conteneur `position: fixed` qui n'a
  lui-même rien à défiler (`overflow: auto` mais sans dépassement actuel)
  ne bloque pas la molette par défaut — le navigateur fait remonter le
  geste non consommé vers l'ancêtre défilable suivant, ici la page
  derrière l'overlay, malgré son `position: fixed` qui donne l'illusion
  visuelle d'être complètement séparée. Confirmé empiriquement (la page
  défilait alors que le `scrollTop` de la visionneuse restait à 0).
  Solution : `overscroll-behavior: contain` sur le conteneur `position:
  fixed` (`.lightbox` dans `htmlgallery.py`), à poser par défaut sur tout
  overlay plein écran de ce type, même quand rien ne semble à première
  vue nécessiter de défilement.
- **Molette de la souris dans la visionneuse** : un seul écouteur
  `wheel` sur `.lightbox`, `{{ passive: false }}` obligatoire pour que
  `preventDefault()` soit honoré. Ctrl/Alt/Cmd + molette = zoom (empêche
  aussi le zoom natif de la page de se déclencher en plus) ; molette
  seule = navigation précédent/suivant, sauf si déjà zoomé au-delà de
  100 % (`currentZoom > 100`), où la molette doit alors déplacer l'image
  agrandie plutôt que changer de photo — dans ce cas précis, ne pas
  appeler `preventDefault()` et laisser le défilement natif du conteneur
  faire le travail. Anti-rebond (`WHEEL_THROTTLE_MS`) nécessaire : un
  simple geste sur trackpad peut émettre des dizaines de micro-événements
  `wheel`, qui feraient sinon défiler plusieurs photos ou paliers de zoom
  d'un coup.
- **Navigation précédent/suivant qui franchit les pages (visionneuse
  galerie HTML)** : chaque page générée étant un fichier statique séparé
  avec son propre tableau `galleryImages` borné à ses seules photos,
  `showDelta()` doit détecter le dépassement des bornes de ce tableau
  (`newIndex < 0` ou `>= galleryImages.length`) et **naviguer vers le
  fichier de la page suivante/précédente** (`window.location.href =
  pageUrl(...)`) plutôt que boucler sur les photos de la page en cours -
  sauf pour une galerie d'une seule page (`totalPages <= 1`), qui n'a
  nulle part où aller et garde un simple bouclage local (évite de
  recharger la page pour rien). Bouclage sur l'**ensemble** de la
  galerie aux deux extrémités (dernière photo de la dernière page →
  première photo de la première page, et inversement). La page de
  destination ne sait pas d'elle-même quelle photo ouvrir : elle arrive
  avec `?open=0` (venant d'une page précédente) ou `?open=last` (venant
  d'une suivante) dans l'URL, lu par un bloc exécuté à la fin du script
  de la page cible, qui ouvre la visionneuse à la bonne photo puis
  nettoie l'URL (`history.replaceState`) pour qu'un rafraîchissement
  manuel ne la rouvre pas involontairement. Un second paramètre,
  `&wrap=fwd`/`&wrap=back`, distingue un franchissement normal (aucun
  avertissement) d'un bouclage sur l'ensemble de la galerie (dernière
  photo → première page ou l'inverse), pour afficher le bon message via
  `showToast()` uniquement dans ce second cas - la page cible ne peut
  pas déduire seule si son arrivée à l'index 0 ou dernier est un
  bouclage ou un simple hasard de pagination, il faut que la page
  source le précise explicitement. La grille de fond (derrière la
  visionneuse) reflète déjà correctement la page cible après ce
  changement, `window.location.href` étant une vraie navigation complète
  — vérifié empiriquement (pagination du haut, vignettes affichées)
  plutôt que supposé.
- **Téléchargement d'image dans la visionneuse (galerie HTML)** : le
  bouton passe par `fetch()` → `Blob` → `URL.createObjectURL()` plutôt
  que le simple attribut HTML `download` sur le lien direct, peu fiable
  une fois servi via HTTP(S) selon les navigateurs. **Limite fondamentale
  et non contournable, testée empiriquement (Playwright/Chromium) avec
  `CHANGELOG.md`** : quand la galerie est ouverte directement en `file://`
  (double-clic sur `index.html`, sans serveur web), `fetch()`,
  `XMLHttpRequest` ET la lecture d'un `<canvas>` ayant chargé l'image sont
  tous les trois bloqués de façon identique par Firefox ET Chrome (chaque
  fichier `file://` a une origine "opaque" depuis le correctif de
  sécurité **CVE-2019-11730**) - aucune API JavaScript ne permet de
  contourner ça. Le code détecte `location.protocol === 'file:'` en amont
  et affiche un message explicatif (bouton toast) plutôt que d'échouer
  silencieusement ; ne PAS retenter une solution "plus maligne" pour ce
  cas précis sans avoir revérifié que cette restriction navigateur a
  changé.
- **Filigrane** : toujours via `utils.apply_watermark()` — fonction
  unique, jamais de logique de filigrane dupliquée localement.
- **Compatibilité GTK/Windows** : pattern défensif systématique pour les
  appels PyGObject sensibles à la plateforme :
  ```python
  try:
      GLib.idle_add(fonction, *args)          # forme pythonique attendue
  except TypeError:
      GLib.idle_add(PRIORITE, fonction, *args) # repli signature C brute
  ```
- **Fichier `VERSION`** : source unique à la racine, lue et écrite par les
  deux scripts de build. N'est mis à jour qu'après un build **réussi**
  (jamais en cas d'échec, pour ne pas désynchroniser le numéro affiché du
  contenu réellement publié).
- **Livraison de code** : fichiers complets systématiquement, jamais de
  diff/patch partiel (convention de travail établie avec le mainteneur).
- **Internationalisation de l'interface graphique** (`portfolio/i18n.py` +
  `portfolio/locales/`) : dictionnaires Python par langue (`fr.py` est la
  source ; `en.py`/`de.py`/`es.py` doivent toujours avoir exactement le
  même jeu de clés — vérifié explicitement en test), pas gettext/.po/.mo
  — choix délibéré pour éviter une étape de compilation et une dépendance
  supplémentaire à empaqueter dans le `.deb`/l'installeur Windows.
  Nouvelle chaîne visible par l'utilisateur = nouvelle clé dans les 4
  fichiers de `locales/`, jamais de texte en dur dans
  `planche-contact-gtk.py`. Un changement de langue ne prend effet qu'au
  redémarrage (pas de reconstruction de l'arbre de widgets à la volée).
  **Piège rencontré à surveiller** : certains menus déroulants affichent
  un texte traduit à l'utilisateur mais doivent transmettre une valeur
  interne fixe (française) au moteur — cas de l'orientation du filigrane,
  comparée en dur en français dans `portfolio/config.py`. Toujours lire
  l'**index** sélectionné (`combo.get_selected()`) et le faire pointer
  vers une liste de valeurs internes séparée
  (`self._orient_values[index]`), jamais le texte affiché
  (`get_selected_item().get_string()`) pour ce genre de champ.
  **Second piège rencontré, plus insidieux** : `PlancheContactGTK` garde
  deux variables distinctes pour la langue — `self.language_preference`
  (le choix brut sauvegardé, peut valoir `"system"`) et `self._language`
  (le résultat déjà résolu par `set_language()`, jamais `"system"` -
  c'est celle-ci qui part dans `--language` vers le sous-processus CLI).
  Changer la langue dans le menu déroulant sans mettre à jour les
  **deux** laisse `self._language` bloquée sur la langue de démarrage :
  une génération lancée juste après un changement de langue (sans
  redémarrer) repartirait alors avec l'ancienne langue - détecté en
  testant explicitement ce scénario précis avec Xvfb, pas visible en
  relisant le code.
  **Troisième piège rencontré, le plus grave** (régression complète,
  détectée par le mainteneur en test manuel, pas par Claude) : Python
  traite `_` comme une variable **locale à toute la fonction** dès qu'on
  lui assigne quoi que ce soit quelque part dans cette fonction - même
  après l'appel qui utilise `_()`. `_choose_folder()` contenait
  `uri, _, label = line.partition(" ")` (convention Python classique
  pour une valeur jetable) dans le code de lecture des signets GTK, plus
  bas dans la même méthode qui appelle `_("folder_picker.title_input")`
  en tout début : ça levait `UnboundLocalError` **à chaque clic** sur
  "Choisir...", empêchant purement et simplement le dialogue de
  s'ouvrir - PyGObject avale l'exception au lieu de faire remonter un
  traceback visible, donnant l'impression que "le bouton ne fait rien".
  Ne plus jamais utiliser `_` comme nom de variable jetable dans un
  fichier qui importe `_` de `i18n.py` - préférer `_sep`, `_unused`, ou
  toute alternative explicite. Un contrôle statique simple (chercher, par
  AST, une fonction qui à la fois assigne `_` et appelle `_(...)`)
  permet de détecter ce genre de conflit sans avoir à cliquer sur
  chaque bouton un par un.
  **Portée** : le CLI (`portfolio.py`), la galerie HTML générée et le
  manuel utilisateur sont également traduits dans la même langue que
  l'interface (voir §2.2/§2.3). Internationalisation désormais complète
  sur l'ensemble du projet.

---

## 6. Décisions techniques prises

Décisions notables, avec leur justification (pour éviter de les remettre
en cause sans en connaître la raison) :

| Décision | Pourquoi |
|---|---|
| Sélecteur de dossier 100 % maison, pas `Gtk.FileChooserDialog` | Le filtrage natif "dossiers uniquement" s'est avéré peu fiable selon les systèmes réels des utilisateurs |
| Une seule fonction de filigrane (`utils.apply_watermark`) | Il en existait 3 versions différentes à l'origine (planches, galerie, une inutilisée), avec un vrai bug d'angle inversé entre deux d'entre elles |
| Une seule passe de décodage pour la galerie HTML | La vignette et l'image "pleine taille" étaient auparavant décodées deux fois séparément — gain de performance significatif |
| Aperçu RAW : miniature embarquée préférée au dématriçage complet | Le dématriçage complet est lent ; l'aperçu JPEG intégré par l'appareil photo suffit pour vignettes/aperçus |
| Police embarquée avec le projet (`portfolio/fonts/`) | Dépendre d'un chemin système deviné (ex: `C:/Windows/Fonts/arial.ttf`) pouvait échouer silencieusement et retomber sur la police minuscule de Pillow |
| Fenêtre principale : taille naturelle minimale, pas de taille forcée | Demande explicite : s'ouvrir aussi petite que possible tout en restant redimensionnable |
| Portage Windows : même code source, pas de fork | Le moteur est déjà 100 % portable ; dupliquer aurait doublé la charge de maintenance pour un gain nul |
| `--run-cli` : l'exe gelé se relance lui-même en mode CLI | Dans un exécutable gelé, `sys.executable` pointe vers l'exe lui-même, pas vers un interpréteur Python générique capable d'exécuter `portfolio.py` comme un script séparé |
| `multiprocessing.freeze_support()` appelé **avant** `import gi` | Double effet : (1) empêche les workers de `ProcessPoolExecutor` de planter avec "Option inconnue --multiprocessing-fork", (2) leur évite de charger inutilement toute la pile GTK4 (gain de performance sur Windows) |
| `gi.overrides` embarqué explicitement (`collect_submodules`) dans le `.spec` | PyInstaller ne détecte pas ces modules automatiquement (chargés dynamiquement par PyGObject, jamais par un `import` explicite visible) ; sans eux, plusieurs API GTK/GLib retombent sur leur signature C brute, plus stricte |
| `contents_directory='.'` dans le `.spec` PyInstaller | PyInstaller 6+ place par défaut tout dans un sous-dossier `_internal/` ; le code de démarrage Windows s'attend à trouver les DLL/typelibs directement à côté de l'exécutable |
| Dépôt renommé `planche-contact-linux` → `planche-contact` | Le projet n'est plus Linux-only depuis le portage Windows |
| `windows/build-windows.ps1` + relais à la racine | Symétrie avec `build-deb.sh` (lancement depuis la racine) sans dupliquer la logique de build elle-même |
| `fpm` (`build-deb.sh`) : scripts de maintenance via `--after-install`/`--after-remove`, jamais un dossier `DEBIAN/` dans les sources `-C` | Contrairement à `dpkg-deb --build` natif, `fpm` ne traite jamais spécialement un dossier nommé `DEBIAN/` parmi ses sources : un tel dossier finit comme contenu de données inerte (installé tel quel sur la machine cible), jamais reconnu comme scripts de maintenance ni exécuté par dpkg |
| `IntFmt` NSIS : toujours le style printf (`"0x%X"`), jamais la syntaxe mnémonique (`"0xX"`) | `"0xX"` est documentée sur le wiki NSIS (valable en NSIS 2.x) mais ne convertit plus rien en NSIS 3.x — elle retourne la chaîne littérale inchangée, faisant silencieusement échouer tout `WriteRegDWORD` qui en dépend (ex : `EstimatedSize`, repli à 0) |
| `makensis` + Wine installables via `apt` dans le bac à sable Linux de Claude | Permet de **compiler ET exécuter** un vrai installeur NSIS pour reproduire/valider un bug Windows sans accès à une machine Windows réelle. Nécessite `nsis` (paquet universe), et pour un installeur NSIS 32 bits par défaut : `dpkg --add-architecture i386` + `wine32:i386` (le simple `wine64` ne suffit pas). Les écritures registre sont vérifiables avec `wine reg query`. Ne remplace pas un vrai test utilisateur (thème visuel, UAC réel, etc.) mais permet de confirmer/infirmer un correctif de logique avant de le transmettre |
| GTK4 + Xvfb installables via `apt` dans le bac à sable Linux de Claude | Permet d'**exécuter réellement** `planche-contact-gtk.py` (pas juste vérifier sa syntaxe) : `apt-get install gir1.2-gtk-4.0 python3-gi`, puis `Xvfb :99 & DISPLAY=:99 python3 script.py`. Piloter l'appli par introspection directe des widgets (`app.win`, `app.run_button.get_label()`, `dropdown.set_selected(i)`...) via `GLib.timeout_add()` après `app.connect("activate", ...)`, plutôt qu'un outil d'automatisation UI dédié. **Xvfb ne survit jamais entre deux appels d'outil séparés** (comme les serveurs HTTP de test) : démarrer Xvfb et lancer le script Python dans la **même** commande shell, jamais deux commandes séparées |


---

## 7. Bugs connus / limitations

| Sujet | État |
|---|---|
| Couleurs GTK4 différentes du thème Windows choisi | **Limitation inhérente**, pas un bug : GTK4 utilise son propre système de thème (Adwaita), indépendant du thème natif de l'OS. Aucune correction simple possible sans un chantier de theming dédié (interroger l'API/le registre Windows et générer du CSS GTK dynamiquement) |
| Avertissement SmartScreen ("Windows a protégé votre PC") à l'installation | **Pas de correctif de code possible** : nécessite un certificat de signature de code payant (~100-500 €/an) ou l'accumulation naturelle de réputation avec le temps. La procédure de contournement (« Informations complémentaires » puis « Exécuter quand même ») est documentée pour l'utilisateur final dans `windows/README.md`, le manuel utilisateur et le `README.md` principal |
| Version Python Windows figée sur celle de la dernière publication gvsbuild | Contrainte externe, pas un bug : si gvsbuild publie une nouvelle version ciblant une autre version de Python, il faudra installer cette nouvelle version (le script la détecte et propose de l'installer automatiquement) |
| Build Windows non testable directement par Claude sur machine réelle | Aucun accès direct à une machine Windows — reste vrai pour tout futur correctif. Cela dit, `makensis` + Wine (voir §6) permettent de compiler et d'exécuter un vrai installeur NSIS dans le bac à sable Linux pour reproduire/valider un correctif de logique avant transmission — plusieurs bugs (voir historique dans `CHANGELOG.md`) ont ainsi été confirmés puis corrigés avec certitude plutôt que par déduction. Le portage a depuis été **validé sur machine Windows réelle par le mainteneur, sans bug apparent**, et publié comme release officielle |

---

## 8. Roadmap

- Internationalisation (i18n) : **fait**, sur l'ensemble du projet —
  interface graphique, CLI, galerie HTML générée et manuel utilisateur
  (anglais, français, allemand, espagnol — voir §2.2/§2.3/§5).
- Modèles de planches contact personnalisables.
- Formats d'export supplémentaires.
- Personnalisation PDF plus poussée.
- *(Optionnel, si budget)* Certificat de signature de code pour supprimer
  l'avertissement SmartScreen sous Windows.
- *(Optionnel, chantier important)* Intégration du thème natif
  Windows/couleur d'accent dans le rendu GTK4.
