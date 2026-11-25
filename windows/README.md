# Planche-Contact — Windows Port

🇫🇷 [Version française](README.fr.md)

This folder contains everything needed to build a Windows package
(portable `.zip` version and `.exe` installer) from the same source code as
the Linux version (`portfolio/` and `planche-contact-gtk.py` at the root of
the repository are **not** duplicated — they are the same files).

✅ **Port validated on a real Windows machine, with no apparent bug — official
release.** Several problems encountered during real-world testing were
fixed along the way (see `CHANGELOG.md`).

## Usage

⚠️ **First launch**: by default, Windows blocks the execution of local
PowerShell scripts (error such as *"running scripts is disabled on this
system"*). Allow it, for the current session only (it changes nothing
permanently):

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then, from a PowerShell prompt, **at the root of the repository** (no need
to enter `windows\`, a relay script `build-windows.ps1` is available there,
symmetrical to `build-deb.sh`):

```powershell
.\build-windows.ps1
```

Options identical to `build-deb.sh`:

```powershell
.\build-windows.ps1 -Major              # 1.2.3 -> 2.0.0
.\build-windows.ps1 -Minor              # 1.2.3 -> 1.3.0
.\build-windows.ps1 -Patch              # 1.2.3 -> 1.2.4
.\build-windows.ps1 -NoVersionChange    # rebuilds without changing the version
.\build-windows.ps1 -Clean              # cleans the build folder
.\build-windows.ps1 -Help               # help
```

The script automatically checks the prerequisites and offers to install them
if they are missing (see below). Every question it asks (confirmation of the
version, installation of a missing prerequisite) is answered with `y` to accept;
any other answer declines. At the end, two files appear at the root of
the repository:

- `planche-contact_X.Y.Z_windows-portable.zip` — standalone folder to
  unzip and launch without installation.
- `planche-contact_X.Y.Z_windows-setup.exe` — classic installer
  (optional Start menu and Desktop shortcuts, option to launch the program at
  the end, uninstaller), if NSIS is available. It speaks
  English, French, Spanish and German, following the language of Windows
  (English if Windows is in another language).

## SmartScreen warning at installation

⚠️ **To warn end users about**: on the first launch of
`planche-contact_X.Y.Z_windows-setup.exe` (or of the portable executable),
Windows will very likely display a blue **"Windows protected your PC"**
screen (SmartScreen). This is normal and expected — the installer is
not digitally signed (see §7 of `PROJECT_CONTEXT.md`), it is not a sign of
malicious software.

To continue:

1. Click **More info**.
2. Click **Run anyway**.

This warning naturally fades over time, as the installer accumulates
reputation with Microsoft's SmartScreen service (downloads, absence of
reports), or disappears immediately with a paid code-signing certificate
(~€100-500/year — see the Roadmap in `PROJECT_CONTEXT.md`). No code fix
can remove it.

## Prerequisites (checked and offered for installation automatically)

⚠️ **64-bit Windows (x64) only.** gvsbuild does not publish a 32-bit build
of GTK4, and the script checks that the detected Python is indeed 64-bit
before continuing (otherwise, it stops with a clear message). 32-bit
Windows 10/11 is extremely rare today anyway.

| Tool | Role | Automatic installation |
|---|---|---|
| Python 3.10+ | Interpreter | No — the script stops with a link if it is missing |
| [gvsbuild](https://github.com/wingtk/gvsbuild) | Precompiled GTK4 stack for Windows | Yes, if you accept (~300 MB download from the GitHub Releases, extracted into `C:\gtk`) |
| PyInstaller | Freezes the Python application into an `.exe` | Yes, through pip in the build's virtual environment |
| [NSIS](https://nsis.sourceforge.io/) | Generates the `.exe` installer (optional) | Yes, through `winget`, if you accept |

Without NSIS, only the portable `.zip` version is produced (the script
continues normally, it is not blocking).

Optional, only for the Explorer context menu (see the section below; the script
never installs them and never stops if they are missing):

| Tool | Role |
|---|---|
| Visual Studio (or Build Tools) with the **"Desktop development with C++"** workload | Compiles the context menu DLL (MSVC) |
| Windows 10/11 SDK (`makeappx.exe`, `signtool.exe`) | Builds and signs the package that puts the entry on the **first level** of the Windows 11 menu |

## Files in this folder

| File | Role |
|---|---|
| `build-windows.ps1` | Main script, Windows equivalent of `build-deb.sh` |
| `planche-contact.spec` | PyInstaller configuration file (bundles GTK4) |
| `installer.nsi` | NSIS script generating the `.exe` installer |
| `build-shellext.ps1` | Builds the Explorer context menu (called by `build-windows.ps1`) |
| `shellext/` | Sources of the context menu: C++ DLL, package manifest, registration scripts |

A second, tiny `build-windows.ps1` exists **at the root of the repository**:
it only relays to this one (symmetrical to `build-deb.sh`, which is also
launched from the root) — that is the one you run in practice.

## How it works (to understand or troubleshoot)

1. A Python virtual environment is created, with the same dependencies as
   the Linux version (Pillow, reportlab, rawpy, exifread) + PyInstaller.
2. The PyGObject/pycairo wheels provided by gvsbuild (`C:\gtk\wheels\`) are
   installed in this same environment — they are wheels compiled
   specifically to be linked to this GTK4 stack, not the generic PyPI
   versions.
3. PyInstaller freezes `planche-contact-gtk.py` into an executable, bundling
   in the same folder:
   - all the DLLs from `C:\gtk\bin\` (GTK4 and its dependencies);
   - the GObject-Introspection typelibs (`C:\gtk\lib\girepository-1.0\`),
     in a `gi_typelibs\` subfolder;
   - the shared GTK data (icons, schemas...) from `C:\gtk\share\`.
4. `planche-contact-gtk.py` contains a small startup block (active
   only under Windows, in a frozen executable) that tells
   PyGObject where to find these bundled typelibs and DLLs, before the very first
   `import gi`.
5. The resulting folder is zipped as is (portable version), and/or
   bundled into an NSIS installer.

## Explorer context menu ("Open in Planche-Contact")

A right click on a **folder** or on a **selection of photos** offers
**Open in Planche-Contact** (in the language of Windows: English, French,
Spanish or German). The program opens with that folder, or with only those
photos (see §3.9 of the manual). On Windows 11 the entry is on the **first
level** of the menu, not under "Show more options". There is no entry on the
background of an open folder on Windows (it exists on Linux).

### Installing and removing it

- **Installer**: the component *Explorer context menu* is ticked by default.
  It registers the entry and **may restart the Windows Explorer** (its windows
  close for a moment: Windows shows a new entry only then). The uninstaller
  removes it.
- **Portable version**: double-click `register-context-menu.cmd` (current user,
  no administrator rights needed), and `unregister-context-menu.cmd` to remove
  it. The folder of the program must not be moved afterwards (register again
  if it is). Options of the PowerShell scripts: `-Machine` (all users,
  administrator), `-RestartExplorer`, `-Quiet`.

### How it is built

`build-windows.ps1` calls `build-shellext.ps1` once the application is frozen.
A failure there is only reported as a warning: the application, the `.zip` and
the installer are produced anyway, just without the menu entry. It produces,
next to `planche-contact-gtk.exe`:

| File | Role |
|---|---|
| `planche_shellext_classic.dll` | The COM component (`IExplorerCommand`), registered the classic way (registry): Windows 10, and "Show more options" on Windows 11 |
| `planche_shellext.dll` | The same, with the identity of the package embedded: first level of the Windows 11 menu |
| `planche-contact-shell.msix` | Sparse package declaring the entry (`*` and `Directory`) and the DLL |
| `planche-contact-shell.cer` | Public certificate that signed the package |
| `register-context-menu.*`, `unregister-context-menu.*`, `shellext-info.json` | Registration scripts and the identifiers they share with the build |

- **Visual Studio C++ build tools are required** to compile the DLL. If they
  are missing, there is no menu entry at all.
- The **Windows SDK** is only needed for the package. Without it, the build
  carries the classic entry only (so, on Windows 11, under "Show more options").
- The identifiers (CLSID, package name, certificate subject) are defined **once**,
  at the top of `build-shellext.ps1`. **Never change the CLSID of a published
  version.**

### Why a certificate, and what it implies

Windows 11 only shows the first-level entries of applications that have an
*identity*, which means a package, and a package must be signed. The package
is signed with a **self-signed** certificate (`CN=Planche-Contact`), created
the first time on the build machine and kept in its *Current user > Personal*
store: its private key never leaves that machine and only the public `.cer` is
shipped. To install the package, the registration script puts that
certificate in the **"Trusted People"** store (of the machine with the
installer, of the user otherwise).

This is a real trust decision, to be told to the users: a package signed by
this certificate is then accepted by Windows without warning, on that
computer. The key stays with the maintainer, the certificate is valid for ten
years, and the uninstaller (or `unregister-context-menu.*`) removes it from the
store. It does not work where Windows refuses packages from outside the
Microsoft Store (S mode, some company policies): the entry is then registered
the classic way, under "Show more options", the program itself being
unaffected.

### Limits

- The package is registered for **one user** (the one who ran the installer
  or the script). Another account of the same computer runs
  `register-context-menu.cmd` once to get the entry on the first level (the
  classic entry is registered for everybody by the installer).
- Updating while the Explorer holds the DLL: the installer renames the loaded
  DLL and deletes it at the next restart, so an update never fails on it.
- Not tested on a real Windows machine at the time of writing (see the
  CHANGELOG): the C++ source compiles without warning with a cross-compiler
  and the scripts are checked by automatic tests, but nothing replaces a test
  of the build with Visual Studio and of the registration on Windows 10 and 11.

## Troubleshooting

**"Namespace Gtk not Available" when launching the frozen executable**
Indicates that the typelibs or the GTK4 DLLs were not found at runtime.
Check that `gi_typelibs\` does exist next to `planche-contact-gtk.exe`
in the output folder, and that the startup block at the top of
`planche-contact-gtk.py` does run before `import gi` (this is the case by
default, but check that no minification/obfuscation tool has moved
it).

**PyInstaller fails with an error related to `libgtk-4-1.dll` not found**
Check that `C:\gtk\bin\` does contain the DLLs (a correct gvsbuild
installation should contain several hundred). If `C:\gtk` is incomplete,
delete it and rerun `build-windows.ps1` to download it again.

**`makensis` fails on `!getenv`**
Some older versions of NSIS do not support `!getenv` natively
without the `EnvVarUpdate` plugin or equivalent. If that is the case, update NSIS
to a recent version (3.x), or replace the `!getenv` lines at the top of
`installer.nsi` with hard-coded values for a quick test.

**Frozen application, but GTK window invisible or silent crash**
Try launching the executable from a command prompt rather than by
double-clicking, to see any error messages (the `.spec`
uses `console=False` for a silent launch in normal use;
temporarily set `console=True` in `planche-contact.spec` for
debugging, then rerun `pyinstaller` manually).

**Missing icon on the executable or in the installer**
Check that `screenshots/application-icon.png` does exist at the root of the
repository, and that the `.png` → `.ico` conversion (done by `build-windows.ps1`
via Pillow) went through without any error in the script's output.

**Application size missing in *Settings > Apps***
Fixed (see `CHANGELOG.md`): `installer.nsi` used `IntFmt $0
"0xX" $0`, a syntax documented on the NSIS wiki but non-functional
in NSIS 3.x (it converts nothing, returns the literal string unchanged),
silently making `EstimatedSize` fall back to 0. If this symptom
reappears after a change to this block, check that the conversion
does use the printf style (`"0x%X"`). This fix was validated by
actually compiling and **running** the installer via `makensis` +
Wine in a Linux environment (see §6 of `PROJECT_CONTEXT.md`),
without needing a Windows machine.

**The menu entry does not appear (Windows 11)**
Restart the Windows Explorer (or sign out and in). Then run
`register-context-menu.cmd` again and read its messages: it says whether
the first level could be set up or whether the classic entry was used instead
("Show more options"). Check in *Settings > Apps > Advanced app settings*
that installing apps from outside the Store is not blocked. As a last
resort, `Get-AppxPackage PlancheContact.ShellExtension` in PowerShell tells
whether the package is registered.

**The build says "Visual Studio C++ build tools not found"**
Install *Build Tools for Visual Studio* with the "Desktop development with
C++" workload, then rerun `build-windows.ps1` (or only
`windows\build-shellext.ps1 -OutDir <folder> -Version X.Y.Z`).

## What is shared with the Linux version (no duplication)

- `portfolio/` — the complete engine (scan, thumbnails, sheets, PDF, gallery,
  CSV): 100% identical, no adaptation needed.
- `planche-contact-gtk.py` — graphical interface: identical, except for the
  small Windows startup block described above (no effect on
  Linux/macOS).

Any fix made to these files for the Linux version therefore benefits the
Windows version automatically, and vice versa.
