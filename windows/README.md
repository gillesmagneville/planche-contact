# Planche-Contact — Portage Windows

Ce dossier contient tout ce qui est nécessaire pour construire un paquet
Windows (version portable `.zip` et installeur `.exe`) à partir du même
code source que la version Linux (`portfolio/` et `planche-contact-gtk.py`
à la racine du dépôt ne sont **pas** dupliqués — ce sont les mêmes fichiers).

✅ **Portage validé sur machine Windows réelle, sans bug apparent — release
officielle.** Plusieurs problèmes rencontrés lors des tests réels ont été
corrigés au fil de l'eau (voir `CHANGELOG.md`).

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
s'ils manquent (voir ci-dessous). À la fin, deux fichiers apparaissent à la
racine du dépôt :

- `planche-contact_X.Y.Z_windows-portable.zip` — dossier autonome à
  décompresser et lancer sans installation.
- `planche-contact_X.Y.Z_windows-setup.exe` — installeur classique
  (raccourcis menu Démarrer, désinstalleur), si NSIS est disponible.

## Avertissement SmartScreen à l'installation

⚠️ **À prévenir auprès des utilisateurs finaux** : au premier lancement de
`planche-contact_X.Y.Z_windows-setup.exe` (ou de l'exécutable portable),
Windows affiche très probablement un écran bleu **« Windows a protégé
votre PC »** (SmartScreen). C'est normal et attendu — l'installeur n'est
pas signé numériquement (voir §7 de `PROJECT_CONTEXT.md`), pas un signe de
logiciel malveillant.

Pour continuer :

1. Cliquer sur **Informations complémentaires**.
2. Cliquer sur **Exécuter quand même**.

Cet avertissement s'atténue naturellement avec le temps, à mesure que
l'installeur accumule de la réputation auprès du service SmartScreen de
Microsoft (téléchargements, absence de signalement), ou disparaît
immédiatement avec un certificat de signature de code payant (~100-500
€/an — voir la Roadmap de `PROJECT_CONTEXT.md`). Aucun correctif de code
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

## Fichiers de ce dossier

| Fichier | Rôle |
|---|---|
| `build-windows.ps1` | Script principal, équivalent Windows de `build-deb.sh` |
| `planche-contact.spec` | Fichier de configuration PyInstaller (embarque GTK4) |
| `installer.nsi` | Script NSIS générant l'installeur `.exe` |

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
Corrigé (voir `CHANGELOG.md`) : `installer.nsi` utilisait `IntFmt $0
"0xX" $0`, une syntaxe documentée sur le wiki NSIS mais non fonctionnelle
en NSIS 3.x (ne convertit rien, renvoie la chaîne littérale inchangée),
faisant retomber `EstimatedSize` à 0 silencieusement. Si ce symptôme
réapparaît après une modification de ce bloc, vérifier que la conversion
utilise bien le style printf (`"0x%X"`). Ce correctif a été validé en
compilant et en **exécutant** réellement l'installeur via `makensis` +
Wine dans un environnement Linux (voir §6 de `PROJECT_CONTEXT.md`),
sans nécessiter de machine Windows.

## Ce qui est partagé avec la version Linux (aucune duplication)

- `portfolio/` — moteur complet (scan, vignettes, planches, PDF, galerie,
  CSV) : 100 % identique, aucune adaptation nécessaire.
- `planche-contact-gtk.py` — interface graphique : identique, à l'exception
  du petit bloc de démarrage Windows décrit ci-dessus (sans effet sur
  Linux/macOS).

Tout correctif apporté à ces fichiers pour la version Linux profite donc
automatiquement à la version Windows, et inversement.
