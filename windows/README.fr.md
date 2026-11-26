# Planche-Contact — Portage Windows

🇬🇧 [English version](README.md)

Ce dossier contient tout ce qui est nécessaire pour construire un paquet
Windows (version portable `.zip` et installeur `.exe`) à partir du même
code source que la version Linux (`portfolio/` et `planche-contact-gtk.py`
à la racine du dépôt ne sont **pas** dupliqués — ce sont les mêmes fichiers).

✅ **Portage validé sur machine Windows réelle, sans bug apparent — release
officielle.** Plusieurs problèmes rencontrés lors des tests réels ont été
corrigés au fil de l'eau (voir `CHANGELOG.fr.md`).

## Utilisation

⚠️ **Premier lancement** : par défaut, Windows bloque l'exécution des
scripts PowerShell locaux (erreur du type *"l'exécution de scripts est
désactivée sur ce système"*). Autorisez-la, pour la session en cours
uniquement (ne change rien de façon permanente) :

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Puis, depuis une invite PowerShell, **à la racine du dépôt** (pas besoin
d'entrer dans `windows\`, un script relais `build-windows.ps1` y est
disponible, symétrique à `build-deb.sh`) :

```powershell
.\build-windows.ps1
```

Options identiques à `build-deb.sh` :

```powershell
.\build-windows.ps1 -Major              # 1.2.3 -> 2.0.0
.\build-windows.ps1 -Minor              # 1.2.3 -> 1.3.0
.\build-windows.ps1 -Patch              # 1.2.3 -> 1.2.4
.\build-windows.ps1 -NoVersionChange    # reconstruit sans changer la version
.\build-windows.ps1 -Clean              # nettoie le dossier de build
.\build-windows.ps1 -Help               # aide
```

Le script vérifie automatiquement les prérequis et propose de les installer
s'ils manquent (voir ci-dessous). Chaque question qu'il pose (confirmation de la
version, installation d'un prérequis manquant) se valide par `y` ; toute autre
réponse refuse. À la fin, deux fichiers apparaissent à la racine du dépôt :

- `planche-contact_X.Y.Z_windows-portable.zip` — dossier autonome à
  décompresser et lancer sans installation.
- `planche-contact_X.Y.Z_windows-setup.exe` — installeur classique
  (raccourcis facultatifs du menu Démarrer et du Bureau, lancement du
  programme en fin d'installation, désinstalleur), si NSIS est disponible. Il parle anglais, français, espagnol et allemand, selon la langue de
  Windows (anglais si Windows est dans une autre langue).

## Avertissement SmartScreen à l'installation

⚠️ **À prévenir auprès des utilisateurs finaux** : au premier lancement de
`planche-contact_X.Y.Z_windows-setup.exe` (ou de l'exécutable portable),
Windows affiche très probablement un écran bleu **« Windows a protégé
votre PC »** (SmartScreen). C'est normal et attendu — l'installeur n'est
pas signé numériquement (voir §7 de `PROJECT_CONTEXT.fr.md`), pas un signe de
logiciel malveillant.

Pour continuer :

1. Cliquer sur **Informations complémentaires**.
2. Cliquer sur **Exécuter quand même**.

Cet avertissement s'atténue naturellement avec le temps, à mesure que
l'installeur accumule de la réputation auprès du service SmartScreen de
Microsoft (téléchargements, absence de signalement), ou disparaît
immédiatement avec un certificat de signature de code payant (~100-500
€/an — voir la Roadmap de `PROJECT_CONTEXT.fr.md`). Aucun correctif de code
ne peut le supprimer.

## Prérequis (vérifiés et proposés à l'installation automatiquement)

⚠️ **Windows 64 bits (x64) exclusivement.** gvsbuild ne publie pas de build
32 bits de GTK4, et le script vérifie que le Python détecté est bien en 64
bits avant de continuer (sinon, arrêt avec message clair). Windows 10/11
en 32 bits est de toute façon extrêmement rare aujourd'hui.

| Outil | Rôle | Installation automatique |
|---|---|---|
| Python 3.10+ | Interpréteur | Non — le script s'arrête avec un lien si absent |
| [gvsbuild](https://github.com/wingtk/gvsbuild) | Pile GTK4 précompilée pour Windows | Oui, si vous acceptez (téléchargement ~300 Mo depuis les Releases GitHub, extrait dans `C:\gtk`) |
| PyInstaller | Gèle l'application Python en `.exe` | Oui, via pip dans l'environnement virtuel du build |
| [NSIS](https://nsis.sourceforge.io/) | Génère l'installeur `.exe` (facultatif) | Oui, via `winget`, si vous acceptez |

Sans NSIS, seule la version portable `.zip` est produite (le script continue
normalement, ce n'est pas bloquant).

Facultatif, uniquement pour le menu contextuel de l'Explorateur (voir la
section ci-dessous ; le script ne les installe jamais et ne s'arrête jamais
s'ils manquent) :

| Outil | Rôle |
|---|---|
| Visual Studio (ou Build Tools) avec la charge de travail **« Développement Desktop en C++ »** | Compile la DLL du menu contextuel (MSVC) |
| SDK Windows 10/11 (`makeappx.exe`, `signtool.exe`) | Construit et signe le paquet qui place l'entrée au **premier niveau** du menu de Windows 11 |

## Fichiers de ce dossier

| Fichier | Rôle |
|---|---|
| `build-windows.ps1` | Script principal, équivalent Windows de `build-deb.sh` |
| `planche-contact.spec` | Fichier de configuration PyInstaller (embarque GTK4) |
| `installer.nsi` | Script NSIS générant l'installeur `.exe` |
| `build-shellext.ps1` | Construit le menu contextuel de l'Explorateur (appelé par `build-windows.ps1`) |
| `shellext/` | Sources du menu contextuel : DLL C++, manifeste du paquet, scripts d'enregistrement |

Un second `build-windows.ps1`, minuscule, existe **à la racine du dépôt** :
il ne fait que relayer vers celui-ci (symétrique à `build-deb.sh`, qui se
lance aussi depuis la racine) — c'est celui-là qu'on lance en pratique.

## Comment ça marche (pour comprendre ou dépanner)

1. Un environnement virtuel Python est créé, avec les mêmes dépendances que
   la version Linux (Pillow, reportlab, rawpy, exifread) + PyInstaller.
2. Les roues PyGObject/pycairo fournies par gvsbuild (`C:\gtk\wheels\`) sont
   installées dans ce même environnement — ce sont des roues compilées
   spécifiquement pour être liées à cette pile GTK4, pas les versions
   génériques de PyPI.
3. PyInstaller gèle `planche-contact-gtk.py` en exécutable, en embarquant
   dans le même dossier :
   - toutes les DLL de `C:\gtk\bin\` (GTK4 et ses dépendances) ;
   - les typelibs GObject-Introspection (`C:\gtk\lib\girepository-1.0\`),
     dans un sous-dossier `gi_typelibs\` ;
   - les données partagées GTK (icônes, schémas...) depuis `C:\gtk\share\`.
4. `planche-contact-gtk.py` contient un petit bloc de démarrage (actif
   uniquement sous Windows, dans un exécutable gelé) qui indique à
   PyGObject où trouver ces typelibs et DLL embarqués, avant le tout premier
   `import gi`.
5. Le dossier résultant est zippé tel quel (version portable), et/ou
   embarqué dans un installeur NSIS.

## Menu contextuel de l'Explorateur (« Ouvrir dans Planche-Contact »)

Un clic droit sur un **dossier** ou sur une **sélection de photos** propose
**Ouvrir dans Planche-Contact** (dans la langue de Windows : anglais, français,
espagnol ou allemand). Le programme s'ouvre avec ce dossier, ou avec ces seules
photos (voir §3.9 du manuel). Sous Windows 11, l'entrée est au **premier
niveau** du menu, et seulement là (voir les limites plus bas). Il n'y a pas
d'entrée sur le fond d'un dossier ouvert sous Windows (elle existe sous Linux).

### L'installer et la retirer

- **Installeur** : le composant *Menu contextuel de l'Explorateur* est coché
  par défaut. Il enregistre l'entrée et **peut relancer l'Explorateur de
  Windows** (ses fenêtres se ferment un instant : Windows n'affiche une
  nouvelle entrée qu'à ce moment). Le désinstalleur la retire.
- **Version portable** : double-cliquer sur `register-context-menu.cmd`
  (utilisateur courant, sans droits d'administrateur), et sur
  `unregister-context-menu.cmd` pour la retirer. Le dossier du programme ne
  doit pas être déplacé ensuite (enregistrer de nouveau s'il l'est). Options
  des scripts PowerShell : `-Machine` (tous les utilisateurs,
  administrateur), `-RestartExplorer`, `-Quiet`.

### Comment il est construit

`build-windows.ps1` appelle `build-shellext.ps1` une fois l'application
gelée. Un échec n'y est signalé que par un avertissement : l'application, le
`.zip` et l'installeur sont produits quand même, simplement sans l'entrée de
menu. Il produit, à côté de `planche-contact-gtk.exe` :

| Fichier | Rôle |
|---|---|
| `planche_shellext_classic.dll` | Le composant COM (`IExplorerCommand`), enregistré à la manière classique (registre) : Windows 10, et « Afficher plus d'options » sous Windows 11 |
| `planche_shellext.dll` | Le même, avec l'identité du paquet intégrée : premier niveau du menu de Windows 11 |
| `planche-contact-shell.msix` | Paquet partiel (*sparse*) déclarant l'entrée (`*` et `Directory`) et la DLL |
| `planche-contact-shell.cer` | Certificat public qui a signé le paquet |
| `register-context-menu.*`, `unregister-context-menu.*`, `shellext-info.json` | Scripts d'enregistrement et identifiants qu'ils partagent avec la construction |

- **Les outils de compilation C++ de Visual Studio sont indispensables** pour
  compiler la DLL. S'ils manquent, il n'y a aucune entrée de menu.
- Le **SDK Windows** n'est nécessaire que pour le paquet. Sans lui, la
  construction n'embarque que l'entrée classique (donc, sous Windows 11, sous
  « Afficher plus d'options »).
- Les identifiants (CLSID, nom du paquet, sujet du certificat) sont définis
  **une seule fois**, en tête de `build-shellext.ps1`. **Ne jamais changer le
  CLSID d'une version publiée.**

### Pourquoi un certificat, et ce que cela implique

Windows 11 n'affiche au premier niveau que les entrées d'applications qui ont
une *identité*, c'est-à-dire un paquet, et un paquet doit être signé. Le
paquet est signé avec un certificat **auto-signé** (`CN=Planche-Contact`), créé
la première fois sur la machine de construction et conservé dans son magasin
*Utilisateur actuel > Personnel* : sa clé privée ne quitte jamais cette machine
et seul le `.cer` public est distribué. Pour installer le paquet, le script
d'enregistrement place ce certificat dans le magasin **« Personnes de
confiance »** (de la machine avec l'installeur, de l'utilisateur sinon).

C'est une vraie décision de confiance, à dire aux utilisateurs : un paquet
signé par ce certificat est ensuite accepté par Windows sans avertissement, sur
cet ordinateur. La clé reste chez le mainteneur, le certificat est valable dix
ans, et le désinstalleur (ou `unregister-context-menu.*`) le retire du
magasin. Cela ne fonctionne pas là où Windows refuse les paquets extérieurs au
Microsoft Store (mode S, certaines stratégies d'entreprise) : l'entrée est
alors enregistrée à la manière classique, sous « Afficher plus d'options », le
programme lui-même n'étant pas affecté.

### Limites

- Le paquet est enregistré pour **un seul utilisateur** (celui qui a lancé
  l'installeur ou le script). Un autre compte du même ordinateur lance une
  fois `register-context-menu.cmd` pour avoir l'entrée au premier niveau
  (l'entrée classique, elle, est enregistrée pour tout le monde par
  l'installeur).
- Mise à jour pendant que l'Explorateur tient la DLL : l'installeur renomme la
  DLL chargée et la supprime au prochain redémarrage, si bien qu'une mise à
  jour n'échoue jamais à cause d'elle.
- **La copie sous « Afficher plus d'options » est masquée par la DLL
  elle-même.** Windows liste deux fois une entrée déclarée par un paquet, au
  premier niveau et sous « Afficher plus d'options », et rien dans le manifeste
  du paquet ne l'empêche. La DLL du paquet reconnaît l'appel venant de l'ancien
  menu (l'objet que Windows lui remet est l'ancien menu, et l'appel est celui
  qui est fait sans attendre) et s'y masque. C'est un comportement observé,
  pas une fonction documentée de Windows : si une version future le change, la
  seconde entrée revient, mais celle du premier niveau n'est jamais perdue. La
  DLL classique (Windows 10, ou le repli ci-dessus) ne se masque jamais.
- Testé par le mainteneur sous Windows 11 (build 26300) ; pas sous Windows 10.
  Le source C++ compile aussi sans avertissement avec un compilateur croisé et
  les scripts sont vérifiés par des tests automatiques.

## Dépannage

**"Namespace Gtk not Available" au lancement de l'exécutable gelé**
Signale que les typelibs ou les DLL GTK4 n'ont pas été trouvés au runtime.
Vérifiez que `gi_typelibs\` existe bien à côté de `planche-contact-gtk.exe`
dans le dossier de sortie, et que le bloc de démarrage en tête de
`planche-contact-gtk.py` s'exécute bien avant `import gi` (c'est le cas par
défaut, mais vérifiez qu'aucun outil de minification/obfuscation ne l'ait
déplacé).

**PyInstaller échoue avec une erreur liée à `libgtk-4-1.dll` introuvable**
Vérifiez que `C:\gtk\bin\` contient bien les DLL (une installation gvsbuild
correcte doit en contenir plusieurs centaines). Si `C:\gtk` est incomplet,
supprimez-le et relancez `build-windows.ps1` pour le retélécharger.

**`makensis` échoue sur `!getenv`**
Certaines versions anciennes de NSIS ne supportent pas `!getenv` nativement
sans le plugin `EnvVarUpdate` ou équivalent. Si c'est le cas, mettez NSIS à
jour vers une version récente (3.x), ou remplacez les lignes `!getenv` en
tête de `installer.nsi` par des valeurs codées en dur pour un test rapide.

**Application gelée, mais fenêtre GTK invisible ou plantage silencieux**
Essayez de lancer l'exécutable depuis une invite de commandes plutôt qu'en
double-cliquant, pour voir les éventuels messages d'erreur (le `.spec`
utilise `console=False` pour un lancement silencieux en usage normal ;
passez temporairement `console=True` dans `planche-contact.spec` pour du
débogage, puis relancez `pyinstaller` manuellement).

**Icône manquante sur l'exécutable ou dans l'installeur**
Vérifiez que `screenshots/application-icon.png` existe bien à la racine du
dépôt, et que la conversion `.png` → `.ico` (faite par `build-windows.ps1`
via Pillow) s'est bien déroulée sans erreur dans la sortie du script.

**Taille de l'application absente dans *Paramètres > Applications***
Corrigé (voir `CHANGELOG.fr.md`) : `installer.nsi` utilisait `IntFmt $0
"0xX" $0`, une syntaxe documentée sur le wiki NSIS mais non fonctionnelle
en NSIS 3.x (ne convertit rien, renvoie la chaîne littérale inchangée),
faisant retomber `EstimatedSize` à 0 silencieusement. Si ce symptôme
réapparaît après une modification de ce bloc, vérifier que la conversion
utilise bien le style printf (`"0x%X"`). Ce correctif a été validé en
compilant et en **exécutant** réellement l'installeur via `makensis` +
Wine dans un environnement Linux (voir §6 de `PROJECT_CONTEXT.fr.md`),
sans nécessiter de machine Windows.

**L'entrée de menu n'apparaît pas (Windows 11)**
Relancer l'Explorateur de Windows (ou fermer et rouvrir la session), puis
relancer `register-context-menu.cmd` et lire ses messages : il indique si le
premier niveau a pu être mis en place ou si l'entrée classique a été utilisée
à la place (« Afficher plus d'options »). Vérifier dans *Paramètres >
Applications > Paramètres avancés des applications* que l'installation
d'applications extérieures au Store n'est pas bloquée. En dernier recours,
`Get-AppxPackage PlancheContact.ShellExtension` dans PowerShell indique si le
paquet est enregistré.

**L'entrée apparaît deux fois (Windows 11)**
Une fois au premier niveau et une fois sous « Afficher plus d'options » : la
DLL n'a pas reconnu l'ancien menu (voir les limites plus haut), ou un
enregistrement classique est encore là à côté du paquet. Lancer
`unregister-context-menu.cmd`, puis de nouveau `register-context-menu.cmd`. Si
la seconde entrée est toujours là, noter le numéro de build de Windows
(`winver`) dans un ticket.

**La construction dit « Visual Studio C++ build tools not found »**
Installer *Build Tools for Visual Studio* avec la charge de travail
« Développement Desktop en C++ », puis relancer `build-windows.ps1` (ou
seulement `windows\build-shellext.ps1 -OutDir <dossier> -Version X.Y.Z`).

## Ce qui est partagé avec la version Linux (aucune duplication)

- `portfolio/` — moteur complet (scan, vignettes, planches, PDF, galerie,
  CSV) : 100 % identique, aucune adaptation nécessaire.
- `planche-contact-gtk.py` — interface graphique : identique, à l'exception
  du petit bloc de démarrage Windows décrit ci-dessus (sans effet sur
  Linux/macOS).

Tout correctif apporté à ces fichiers pour la version Linux profite donc
automatiquement à la version Windows, et inversement.
