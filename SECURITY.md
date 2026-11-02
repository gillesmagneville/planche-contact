# Security Policy

🇫🇷 [Version française](SECURITY.fr.md)

Planche-Contact is maintained by one person, on a voluntary basis. This page explains how to report a security problem and what you can expect in return.

## Supported versions

Only the **latest release** receives security fixes. If you use an older version, please update first: the releases are on the [Releases page](https://github.com/gillesmagneville/planche-contact/releases) and the changes are listed in the [CHANGELOG](CHANGELOG.md).

## Reporting a vulnerability

**Please do not report a vulnerability in a public Issue, Pull Request or discussion**: anyone could read it before a fix exists.

Report it privately, in one of these two ways:

1. **On GitHub**: open the [Security tab](https://github.com/gillesmagneville/planche-contact/security) of the repository and click **Report a vulnerability**. Only you and the maintainer can see the report.
2. **By email**: write to [gilles@magneville.fr](mailto:gilles@magneville.fr) with the subject "Planche-Contact security".

Please include, as far as you can:

- the Planche-Contact version (shown in the "About" window) and how you installed it (`.deb` package, AppImage, Windows installer or portable version, or from the source code);
- your operating system;
- a description of the problem and the steps to reproduce it;
- what you think the impact is;
- if the problem comes from a particular file, the file itself — only if you may share it.

## What to expect

These are goals, not guarantees, since there is only one maintainer:

- an acknowledgement of your report within **7 days**;
- an answer on whether it is considered a vulnerability, then news at least every few weeks until it is settled;
- a fix published in a **new release**, mentioned in the CHANGELOG; for a serious problem, a GitHub security advisory too;
- you are credited in the release notes, unless you prefer to stay anonymous.

Please keep the details private until a fixed version is available, so that users have the time to update.

## What is covered

Planche-Contact works on your computer, on your own photos, and does not send them anywhere. A report is relevant, for example, if:

- an image or RAW file, or a settings profile (JSON file), makes the program run code or read or write files it should not;
- a generated HTML gallery runs code coming from file names or photo metadata;
- the `.deb` package or its installation script, the AppImage, the Windows installer or the build scripts can be abused;
- a file of a release does not match its published `.sha256` fingerprint.

## What is not covered

- A vulnerability inside a **component developed by someone else** (Pillow, ReportLab, rawpy/LibRaw, GTK, Python…): please report it to that project. Do tell me if the version shipped with Planche-Contact is affected, so that I can update it.
- Problems that need a computer which is already compromised, or physical access to it.
- Ordinary bugs without security consequences: please open an [Issue](https://github.com/gillesmagneville/planche-contact/issues) instead.

## Checking what you download

Download Planche-Contact only from the [Releases page](https://github.com/gillesmagneville/planche-contact/releases) of this repository. Each file is published with its `.sha256` fingerprint, which is also given in the [README](README.md). The Windows installer is not code-signed (see the README), so this check is all the more useful.
