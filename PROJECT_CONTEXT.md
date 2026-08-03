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
| `scanner.py` | Scan du dossier (récursif ou non), tri par date EXIF ou nom, exclut `planches/` et `gallery/` du dossier de sortie configuré pour éviter de re-scanner ses propres fichiers générés |
| `rawloader.py` | Chargement unifié image/RAW : aperçu JPEG embarqué en priorité (rapide), dématriçage complet (`rawpy`) uniquement si cet aperçu est absent ou trop petit |
| `thumbnail.py` | Génération de vignettes en parallèle (`ProcessPoolExecutor`, contexte `spawn` forcé) |
| `contactsheet.py` | Génère les planches contact (en-tête, grille de vignettes, pied de page, numéro de page) |
| `pdfexport.py` | Assemble les planches en PDF (`reportlab`) ; marge haute réduite indépendamment des autres marges |
| `htmlgallery.py` | Galerie HTML paginée ; **une seule passe de décodage** par photo (la vignette est dérivée de l'image pleine taille déjà décodée, pas un second décodage) ; `ImageOps.exif_transpose()` appliqué systématiquement pour respecter l'orientation (voir §5) |
| `csvindex.py` | Génère l'index CSV |
| `utils.py` | `get_font()` (police embarquée, mise en cache), `apply_watermark()` (filigrane en mosaïque, **fonction unique** utilisée par les planches, le PDF et la galerie), `setup_logging()` |
| `portfolio.py` | Point d'entrée CLI (`argparse`), orchestre tout ce qui précède, affiche des lignes `PROGRESS:X/100 message` sur stdout (lues par l'interface graphique) |
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
│   └── planche-contact-manual.html # Manuel utilisateur complet
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
  décodage optimisés/fusionnés (voir §7, bug corrigé sur la galerie HTML
  qui avait perdu cet appel lors du passage au décodage unique).
- **`pip install` dans le venv embarqué (Linux, `build-deb.sh`)** :
  toujours avec `--ignore-installed`. Le venv est créé avec
  `--system-site-packages` ; sans ce flag, `pip` saute silencieusement la
  copie locale d'un paquet déjà visible au niveau système sur la machine
  de build, produisant un venv qui fonctionne par accident sur cette
  machine mais est réellement incomplet une fois le `.deb` installé
  ailleurs (voir §7).
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

---

## 7. Bugs connus / limitations

| Sujet | État |
|---|---|
| Couleurs GTK4 différentes du thème Windows choisi | **Limitation inhérente**, pas un bug : GTK4 utilise son propre système de thème (Adwaita), indépendant du thème natif de l'OS. Aucune correction simple possible sans un chantier de theming dédié (interroger l'API/le registre Windows et générer du CSS GTK dynamiquement) |
| Avertissement SmartScreen ("Windows a protégé votre PC") à l'installation | **Pas de correctif de code possible** : nécessite un certificat de signature de code payant (~100-500 €/an) ou l'accumulation naturelle de réputation avec le temps |
| Version Python Windows figée sur celle de la dernière publication gvsbuild | Contrainte externe, pas un bug : si gvsbuild publie une nouvelle version ciblant une autre version de Python, il faudra installer cette nouvelle version (le script la détecte et propose de l'installer automatiquement) |
| Build Windows non testable directement par Claude sur machine réelle | Aucun accès direct à une machine Windows. Cela dit, `makensis` + Wine (voir §6) permettent désormais de compiler et d'exécuter un vrai installeur NSIS dans le bac à sable Linux pour reproduire/valider un correctif de logique avant transmission — plusieurs bugs (voir historique dans `CHANGELOG.md`) ont ainsi été confirmés puis corrigés avec certitude plutôt que par déduction. Un test réel sur machine Windows par le mainteneur reste néanmoins la validation finale (thème visuel, UAC, SmartScreen...) |

---

## 8. Roadmap

- Publier une release binaire Windows officielle une fois les tests
  utilisateur réels concluants.
- Internationalisation (i18n) — l'interface et les messages sont
  actuellement uniquement en français.
- Modèles de planches contact personnalisables.
- Formats d'export supplémentaires.
- Personnalisation PDF plus poussée.
- *(Optionnel, si budget)* Certificat de signature de code pour supprimer
  l'avertissement SmartScreen sous Windows.
- *(Optionnel, chantier important)* Intégration du thème natif
  Windows/couleur d'accent dans le rendu GTK4.
