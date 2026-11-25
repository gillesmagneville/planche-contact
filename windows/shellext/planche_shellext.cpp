// planche_shellext.cpp - "Open in Planche-Contact" entry of the Windows
// Explorer context menu.
//
// A small COM DLL implementing IExplorerCommand. It does nothing but gather
// the paths of the selected folders and photos and start
// planche-contact-gtk.exe (located in the same folder as this DLL) with
//     planche-contact-gtk.exe --paths-from <list file>
// where the list file is a UTF-8 text file, one path per line, in the
// temporary folder. The application reads it and deletes it (see
// portfolio/launch.py): no command-line length limit, whatever the number of
// photos selected.
//
// The same source is built in two flavours (see windows/build-shellext.ps1):
//   - planche_shellext.dll         with an embedded "msix" identity manifest,
//     declared as a COM surrogate server by the sparse package of Windows 11
//     (first level of the new context menu);
//   - planche_shellext_classic.dll without it, registered the classic way
//     (HKLM\Software\Classes\...\ExplorerCommandHandler) for Windows 10 and
//     for the "Show more options" menu of Windows 11.
//
// The CLSID comes from pc_clsid.h, a one-line header generated at build time
// by build-shellext.ps1 (#define PC_CLSID_STRING L"{...}"): it stays defined
// in ONE place, shared with the package manifest and the registration
// scripts.
//
// Deliberately minimal: no exception leaves a COM method, nothing is cached,
// nothing is written outside the temporary list file.

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN

#include <windows.h>
#include <ocidl.h>
#include <shlwapi.h>
#include <shobjidl.h>

#include <new>
#include <string>
#include <vector>

#include "pc_clsid.h"  // generated: #define PC_CLSID_STRING L"{...}"

namespace {

// Name of the application, in the folder of this DLL.
const wchar_t kExeName[] = L"planche-contact-gtk.exe";

// Start of the name of the temporary list file. Must stay identical to
// SELECTION_FILE_PREFIX in portfolio/launch.py: the application deletes the
// files of this name once read (tests/test_windows_shellext.py checks it).
const wchar_t kListPrefix[] = L"planche-contact-selection-";

// Photo formats of the application. A copy of
// ImageScanner.SUPPORTED_EXTENSIONS in portfolio/scanner.py
// (tests/test_windows_shellext.py checks that both stay identical).
const wchar_t* const kPhotoExtensions[] = {
    L".jpg", L".jpeg", L".png", L".tif", L".tiff", L".bmp", L".webp",
    L".heic", L".heif", L".cr2", L".cr3", L".nef", L".dng", L".arw",
};

HMODULE g_module = nullptr;
volatile LONG g_liveObjects = 0;  // COM objects alive + LockServer calls

CLSID ServerClsid() {
    CLSID clsid = {};
    CLSIDFromString(PC_CLSID_STRING, &clsid);
    return clsid;
}

std::wstring ModuleDirectory() {
    std::wstring path(MAX_PATH, L'\0');
    for (;;) {
        DWORD n = GetModuleFileNameW(g_module, &path[0], static_cast<DWORD>(path.size()));
        if (n == 0) return std::wstring();
        if (n < path.size()) {
            path.resize(n);
            break;
        }
        path.resize(path.size() * 2);  // truncated: a longer buffer
    }
    size_t slash = path.find_last_of(L'\\');
    return slash == std::wstring::npos ? std::wstring() : path.substr(0, slash);
}

std::wstring ExePath() { return ModuleDirectory() + L"\\" + kExeName; }

const wchar_t* Title() {
    switch (PRIMARYLANGID(GetUserDefaultUILanguage())) {
        case LANG_FRENCH:  return L"Ouvrir dans Planche-Contact";
        case LANG_GERMAN:  return L"In Planche-Contact \u00f6ffnen";
        case LANG_SPANISH: return L"Abrir en Planche-Contact";
        default:           return L"Open in Planche-Contact";
    }
}

bool IsPhotoPath(const std::wstring& path) {
    const wchar_t* ext = PathFindExtensionW(path.c_str());
    if (!ext || !*ext) return false;
    for (const wchar_t* known : kPhotoExtensions) {
        if (_wcsicmp(ext, known) == 0) return true;
    }
    return false;
}

// True (and `path` filled in) for what the application can open: a real
// folder of the file system, or a photo file. Virtual items (This PC, Recycle
// Bin...), compressed folders (.zip) and every other file are left out.
bool OpenablePath(IShellItem* item, std::wstring* path) {
    SFGAOF attributes = 0;
    if (FAILED(item->GetAttributes(SFGAO_FOLDER | SFGAO_FILESYSTEM | SFGAO_STREAM, &attributes))) {
        return false;
    }
    PWSTR name = nullptr;
    if (FAILED(item->GetDisplayName(SIGDN_FILESYSPATH, &name)) || !name) return false;
    std::wstring candidate(name);
    CoTaskMemFree(name);

    bool is_folder = (attributes & SFGAO_FOLDER) != 0;
    bool real_folder = is_folder && (attributes & SFGAO_FILESYSTEM) && !(attributes & SFGAO_STREAM);
    if (real_folder || (!is_folder && IsPhotoPath(candidate))) {
        if (path) *path = candidate;
        return true;
    }
    return false;
}

std::vector<std::wstring> OpenablePaths(IShellItemArray* items) {
    std::vector<std::wstring> paths;
    DWORD count = 0;
    if (!items || FAILED(items->GetCount(&count))) return paths;
    for (DWORD i = 0; i < count; ++i) {
        IShellItem* item = nullptr;
        if (FAILED(items->GetItemAt(i, &item)) || !item) continue;
        std::wstring path;
        if (OpenablePath(item, &path)) paths.push_back(path);
        item->Release();
    }
    return paths;
}

std::string ToUtf8(const std::wstring& text) {
    if (text.empty()) return std::string();
    int size = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                                   nullptr, 0, nullptr, nullptr);
    if (size <= 0) return std::string();
    std::string utf8(static_cast<size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                        &utf8[0], size, nullptr, nullptr);
    return utf8;
}

// Writes the paths (UTF-8, one per line) to a new file of the temporary
// folder; returns its path, or an empty string on failure.
std::wstring WriteListFile(const std::vector<std::wstring>& paths) {
    wchar_t temp_dir[MAX_PATH + 2];
    DWORD n = GetTempPathW(MAX_PATH + 1, temp_dir);
    if (n == 0 || n > MAX_PATH) return std::wstring();

    GUID guid = {};
    if (FAILED(CoCreateGuid(&guid))) return std::wstring();
    wchar_t guid_text[64];
    if (StringFromGUID2(guid, guid_text, 64) == 0) return std::wstring();
    std::wstring id(guid_text);  // "{xxxxxxxx-xxxx-...}"
    id = id.substr(1, id.size() - 2);

    std::wstring list_path = std::wstring(temp_dir) + kListPrefix + id + L".txt";
    HANDLE file = CreateFileW(list_path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                              FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return std::wstring();

    std::string content;
    for (const std::wstring& path : paths) {
        content += ToUtf8(path);
        content += '\n';
    }
    DWORD written = 0;
    BOOL ok = WriteFile(file, content.data(), static_cast<DWORD>(content.size()), &written, nullptr);
    CloseHandle(file);
    if (!ok || written != content.size()) {
        DeleteFileW(list_path.c_str());
        return std::wstring();
    }
    return list_path;
}

HRESULT LaunchApplication(const std::vector<std::wstring>& paths) {
    std::wstring exe = ExePath();
    if (GetFileAttributesW(exe.c_str()) == INVALID_FILE_ATTRIBUTES) {
        return HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND);
    }
    std::wstring list_path = WriteListFile(paths);
    if (list_path.empty()) return E_FAIL;

    // CreateProcessW may modify the command line buffer: a writable copy.
    std::wstring command = L"\"" + exe + L"\" --paths-from \"" + list_path + L"\"";
    std::vector<wchar_t> buffer(command.begin(), command.end());
    buffer.push_back(L'\0');
    std::wstring directory = ModuleDirectory();

    STARTUPINFOW startup = {};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process = {};
    if (!CreateProcessW(exe.c_str(), buffer.data(), nullptr, nullptr, FALSE, 0, nullptr,
                        directory.c_str(), &startup, &process)) {
        HRESULT error = HRESULT_FROM_WIN32(GetLastError());
        DeleteFileW(list_path.c_str());  // nobody will read it
        return error;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return S_OK;
}

// ---------------------------------------------------------------------------

class PlancheCommand final : public IExplorerCommand, public IObjectWithSite {
public:
    PlancheCommand() : refs_(1), site_(nullptr) { InterlockedIncrement(&g_liveObjects); }

    // IUnknown
    IFACEMETHODIMP QueryInterface(REFIID riid, void** object) override {
        if (!object) return E_POINTER;
        *object = nullptr;
        if (riid == IID_IUnknown || riid == IID_IExplorerCommand) {
            *object = static_cast<IExplorerCommand*>(this);
        } else if (riid == IID_IObjectWithSite) {
            *object = static_cast<IObjectWithSite*>(this);
        } else {
            return E_NOINTERFACE;
        }
        AddRef();
        return S_OK;
    }
    IFACEMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    IFACEMETHODIMP_(ULONG) Release() override {
        ULONG left = InterlockedDecrement(&refs_);
        if (left == 0) delete this;
        return left;
    }

    // IExplorerCommand
    IFACEMETHODIMP GetTitle(IShellItemArray*, PWSTR* name) override {
        return SHStrDupW(Title(), name);
    }
    IFACEMETHODIMP GetIcon(IShellItemArray*, PWSTR* icon) override {
        try {
            return SHStrDupW((ExePath() + L",0").c_str(), icon);
        } catch (...) {
            *icon = nullptr;
            return E_FAIL;
        }
    }
    IFACEMETHODIMP GetToolTip(IShellItemArray*, PWSTR* tip) override {
        *tip = nullptr;
        return E_NOTIMPL;
    }
    IFACEMETHODIMP GetCanonicalName(GUID* name) override {
        *name = ServerClsid();
        return S_OK;
    }
    // Shown only when the selection holds at least one folder or photo.
    IFACEMETHODIMP GetState(IShellItemArray* items, BOOL, EXPCMDSTATE* state) override {
        *state = ECS_HIDDEN;
        try {
            DWORD count = 0;
            if (!items || FAILED(items->GetCount(&count))) return S_OK;
            for (DWORD i = 0; i < count; ++i) {
                IShellItem* item = nullptr;
                if (FAILED(items->GetItemAt(i, &item)) || !item) continue;
                bool openable = OpenablePath(item, nullptr);
                item->Release();
                if (openable) {
                    *state = ECS_ENABLED;
                    break;
                }
            }
        } catch (...) {
        }
        return S_OK;
    }
    IFACEMETHODIMP Invoke(IShellItemArray* items, IBindCtx*) override {
        try {
            std::vector<std::wstring> paths = OpenablePaths(items);
            if (paths.empty()) return S_OK;
            return LaunchApplication(paths);
        } catch (...) {
            return E_FAIL;
        }
    }
    IFACEMETHODIMP GetFlags(EXPCMDFLAGS* flags) override {
        *flags = ECF_DEFAULT;
        return S_OK;
    }
    IFACEMETHODIMP EnumSubCommands(IEnumExplorerCommand** commands) override {
        *commands = nullptr;
        return E_NOTIMPL;
    }

    // IObjectWithSite
    IFACEMETHODIMP SetSite(IUnknown* site) override {
        if (site) site->AddRef();
        if (site_) site_->Release();
        site_ = site;
        return S_OK;
    }
    IFACEMETHODIMP GetSite(REFIID riid, void** site) override {
        if (!site_) {
            *site = nullptr;
            return E_FAIL;
        }
        return site_->QueryInterface(riid, site);
    }

private:
    ~PlancheCommand() {
        if (site_) site_->Release();
        InterlockedDecrement(&g_liveObjects);
    }

    LONG refs_;
    IUnknown* site_;
};

class PlancheFactory final : public IClassFactory {
public:
    PlancheFactory() : refs_(1) { InterlockedIncrement(&g_liveObjects); }

    IFACEMETHODIMP QueryInterface(REFIID riid, void** object) override {
        if (!object) return E_POINTER;
        if (riid == IID_IUnknown || riid == IID_IClassFactory) {
            *object = static_cast<IClassFactory*>(this);
            AddRef();
            return S_OK;
        }
        *object = nullptr;
        return E_NOINTERFACE;
    }
    IFACEMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    IFACEMETHODIMP_(ULONG) Release() override {
        ULONG left = InterlockedDecrement(&refs_);
        if (left == 0) delete this;
        return left;
    }
    IFACEMETHODIMP CreateInstance(IUnknown* outer, REFIID riid, void** object) override {
        if (!object) return E_POINTER;
        *object = nullptr;
        if (outer) return CLASS_E_NOAGGREGATION;
        PlancheCommand* command = new (std::nothrow) PlancheCommand();
        if (!command) return E_OUTOFMEMORY;
        HRESULT result = command->QueryInterface(riid, object);
        command->Release();
        return result;
    }
    IFACEMETHODIMP LockServer(BOOL lock) override {
        if (lock) {
            InterlockedIncrement(&g_liveObjects);
        } else {
            InterlockedDecrement(&g_liveObjects);
        }
        return S_OK;
    }

private:
    ~PlancheFactory() { InterlockedDecrement(&g_liveObjects); }
    LONG refs_;
};

}  // namespace

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = module;
        DisableThreadLibraryCalls(module);
    }
    return TRUE;
}

STDAPI DllGetClassObject(REFCLSID clsid, REFIID riid, void** object) {
    if (!object) return E_POINTER;
    *object = nullptr;
    if (clsid != ServerClsid()) return CLASS_E_CLASSNOTAVAILABLE;
    PlancheFactory* factory = new (std::nothrow) PlancheFactory();
    if (!factory) return E_OUTOFMEMORY;
    HRESULT result = factory->QueryInterface(riid, object);
    factory->Release();
    return result;
}

STDAPI DllCanUnloadNow() { return g_liveObjects == 0 ? S_OK : S_FALSE; }
