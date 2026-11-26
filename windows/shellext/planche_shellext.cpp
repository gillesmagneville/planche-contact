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
//     (first level of the new context menu). Built with
//     PC_HIDE_IN_CLASSIC_MENU: Windows also lists a packaged entry under
//     "Show more options", where this flavour hides itself (see
//     IsClassicMenuSite), so that the entry appears once, in the first level;
//   - planche_shellext_classic.dll without it, registered the classic way
//     (HKLM\Software\Classes\...\ExplorerCommandHandler) for Windows 10 and
//     for the "Show more options" menu of Windows 11 when the package could
//     not be registered. It never hides itself.
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

#ifdef PC_PROBE
#include <docobj.h>
#include <servprov.h>
#endif

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

#ifdef PC_PROBE
// ---------------------------------------------------------------------------
// DIAGNOSTIC BUILD ONLY (build-shellext.ps1 -Probe). Behaviour is unchanged;
// every call Windows makes to this entry is written to
// %PUBLIC%\planche-shellext-probe.log, to find out how the copy of the entry
// shown under "Show more options" differs from the one of the first level of
// the Windows 11 menu (process, thread, interfaces asked for, call stack...).
// Never part of a released build.

std::wstring ProbeBaseName(const wchar_t* path) {
    const wchar_t* slash = wcsrchr(path, L'\\');
    return slash ? std::wstring(slash + 1) : std::wstring(path);
}

std::wstring ProbeHex(unsigned long value) {
    wchar_t text[16] = {};
    wsprintfW(text, L"0x%08lx", value);
    return text;
}

std::wstring ProbeGuid(REFGUID guid) {
    wchar_t text[64] = {};
    if (StringFromGUID2(guid, text, 64) == 0) return L"?";
    return text;
}

std::wstring ProbeLogPath() {
    wchar_t buffer[MAX_PATH + 2] = {};
    std::wstring dir;
    DWORD n = GetEnvironmentVariableW(L"PUBLIC", buffer, MAX_PATH);
    if (n > 0 && n < MAX_PATH) {
        dir = buffer;
    } else {
        n = GetTempPathW(MAX_PATH, buffer);
        if (n == 0 || n >= MAX_PATH) return std::wstring();
        dir = buffer;
    }
    if (!dir.empty() && dir.back() != L'\\') dir += L'\\';
    return dir + L"planche-shellext-probe.log";
}

// The modules the call comes through, innermost first (consecutive duplicates
// merged): shows whether Explorer itself or the COM runtime is calling.
std::wstring ProbeStack() {
    void* frames[16] = {};
    USHORT count = RtlCaptureStackBackTrace(2, 16, frames, nullptr);
    std::wstring out;
    std::wstring last;
    for (USHORT i = 0; i < count; ++i) {
        HMODULE module = nullptr;
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                    GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                reinterpret_cast<LPCWSTR>(frames[i]), &module) || !module) {
            continue;
        }
        wchar_t name[MAX_PATH] = {};
        if (GetModuleFileNameW(module, name, MAX_PATH) == 0) continue;
        std::wstring base = ProbeBaseName(name);
        if (base == last) continue;
        last = base;
        if (!out.empty()) out += L" < ";
        out += base;
    }
    return out;
}

void ProbeLog(const std::wstring& message) {
    try {
        std::wstring path = ProbeLogPath();
        if (path.empty()) return;
        wchar_t module_path[MAX_PATH] = {};
        GetModuleFileNameW(nullptr, module_path, MAX_PATH);
        long apartment = -1;
        long qualifier = -1;
        APTTYPE apartment_type = APTTYPE_CURRENT;
        APTTYPEQUALIFIER apartment_qualifier = APTTYPEQUALIFIER_NONE;
        if (SUCCEEDED(CoGetApartmentType(&apartment_type, &apartment_qualifier))) {
            apartment = static_cast<long>(apartment_type);
            qualifier = static_cast<long>(apartment_qualifier);
        }
        std::wstring line = L"t=" + std::to_wstring(GetTickCount64()) +
                            L" pid=" + std::to_wstring(GetCurrentProcessId()) +
                            L" tid=" + std::to_wstring(GetCurrentThreadId()) +
                            L" proc=" + ProbeBaseName(module_path) +
                            L" apt=" + std::to_wstring(apartment) + L"/" + std::to_wstring(qualifier) +
                            L" | " + message +
                            L" | stack=" + ProbeStack() + L"\r\n";
        std::string utf8 = ToUtf8(line);
        HANDLE file = CreateFileW(path.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                  nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (file == INVALID_HANDLE_VALUE) return;
        DWORD written = 0;
        WriteFile(file, utf8.data(), static_cast<DWORD>(utf8.size()), &written, nullptr);
        CloseHandle(file);
    } catch (...) {
    }
}

bool ProbeSupports(IUnknown* object, REFIID iid) {
    void* other = nullptr;
    if (object && SUCCEEDED(object->QueryInterface(iid, &other)) && other) {
        static_cast<IUnknown*>(other)->Release();
        return true;
    }
    return false;
}

// "proxy" when the object lives in another process (COM proxies, and only
// them, answer IClientSecurity).
std::wstring ProbeKind(IUnknown* object) {
    if (!object) return L"null";
    return ProbeSupports(object, IID_IClientSecurity) ? L"proxy" : L"local";
}

std::wstring ProbeItems(IShellItemArray* items) {
    if (!items) return L"items=null";
    std::wstring out = L"items(" + ProbeKind(items) + L")=";
    DWORD count = 0;
    if (FAILED(items->GetCount(&count))) return out + L"?";
    out += std::to_wstring(count);
    IShellItem* item = nullptr;
    if (count > 0 && SUCCEEDED(items->GetItemAt(0, &item)) && item) {
        PWSTR name = nullptr;
        if (SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH, &name)) && name) {
            out += L" first=" + std::wstring(name);
            CoTaskMemFree(name);
        }
        SFGAOF attributes = 0;
        if (SUCCEEDED(item->GetAttributes(SFGAO_FOLDER | SFGAO_FILESYSTEM | SFGAO_STREAM, &attributes))) {
            out += L" attr=" + ProbeHex(static_cast<unsigned long>(attributes));
        }
        item->Release();
    }
    return out;
}

std::wstring ProbeSite(IUnknown* site) {
    if (!site) return L"site=null";
    struct Entry {
        const wchar_t* name;
        const IID* iid;
    };
    const Entry entries[] = {
        {L"IServiceProvider", &IID_IServiceProvider},
        {L"IOleWindow", &IID_IOleWindow},
        {L"IOleCommandTarget", &IID_IOleCommandTarget},
        {L"IObjectWithSite", &IID_IObjectWithSite},
        {L"IContextMenu", &IID_IContextMenu},
        {L"IContextMenu2", &IID_IContextMenu2},
        {L"IContextMenu3", &IID_IContextMenu3},
        {L"IShellBrowser", &IID_IShellBrowser},
        {L"IShellView", &IID_IShellView},
        {L"IFolderView", &IID_IFolderView},
        {L"IFolderView2", &IID_IFolderView2},
        {L"IDataObject", &IID_IDataObject},
        {L"IShellFolder", &IID_IShellFolder},
    };
    std::wstring out = L"site(" + ProbeKind(site) + L"):";
    for (const Entry& entry : entries) {
        if (ProbeSupports(site, *entry.iid)) {
            out += L" ";
            out += entry.name;
        }
    }
    IServiceProvider* services = nullptr;
    if (SUCCEEDED(site->QueryInterface(IID_IServiceProvider, reinterpret_cast<void**>(&services))) &&
        services) {
        void* browser = nullptr;
        if (SUCCEEDED(services->QueryService(IID_IShellBrowser, IID_IShellBrowser, &browser)) && browser) {
            out += L" [service:IShellBrowser]";
            static_cast<IUnknown*>(browser)->Release();
        }
        services->Release();
    }
    return out;
}

#define PROBE(expression) ProbeLog(expression)
#else
#define PROBE(expression) ((void)0)
#endif

#ifdef PC_HIDE_IN_CLASSIC_MENU
bool Supports(IUnknown* object, REFIID iid) {
    void* other = nullptr;
    if (object && SUCCEEDED(object->QueryInterface(iid, &other)) && other) {
        static_cast<IUnknown*>(other)->Release();
        return true;
    }
    return false;
}

// Windows lists an entry declared by the package twice: in the first level of
// the new menu and, as it did for the menu of Windows 10, under "Show more
// options". It is the same IExplorerCommand, called in two different ways
// (measured with a logging build on Windows 11, build 26300):
//   new menu       the site only offers IServiceProvider and IObjectWithSite;
//                  GetState comes first, with fOkToBeSlow = TRUE
//   classic menu   the site is the classic menu object: it also offers
//                  IOleWindow and IContextMenu / IContextMenu2 / IContextMenu3;
//                  GetState comes last, with fOkToBeSlow = FALSE
// The entry hides itself in the second case. Both signs are required, so that
// a change in a future Windows can only make the classic copy come back,
// never make the first-level entry disappear.
bool IsClassicMenuSite(IUnknown* site) {
    return Supports(site, IID_IContextMenu) && Supports(site, IID_IContextMenu2) &&
           Supports(site, IID_IContextMenu3) && Supports(site, IID_IOleWindow);
}
#endif

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
    PlancheCommand() : refs_(1), site_(nullptr) {
        InterlockedIncrement(&g_liveObjects);
        PROBE(L"ctor cmdline=" + std::wstring(GetCommandLineW()).substr(0, 220));
    }

    // IUnknown
    IFACEMETHODIMP QueryInterface(REFIID riid, void** object) override {
        if (!object) return E_POINTER;
        *object = nullptr;
        HRESULT result = S_OK;
        if (riid == IID_IUnknown || riid == IID_IExplorerCommand) {
            *object = static_cast<IExplorerCommand*>(this);
        } else if (riid == IID_IObjectWithSite) {
            *object = static_cast<IObjectWithSite*>(this);
        } else {
            result = E_NOINTERFACE;
        }
        if (SUCCEEDED(result)) AddRef();
        PROBE(L"QueryInterface iid=" + ProbeGuid(riid) + (SUCCEEDED(result) ? L" accepted" : L" refused"));
        return result;
    }
    IFACEMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    IFACEMETHODIMP_(ULONG) Release() override {
        ULONG left = InterlockedDecrement(&refs_);
        if (left == 0) delete this;
        return left;
    }

    // IExplorerCommand
    IFACEMETHODIMP GetTitle(IShellItemArray* items, PWSTR* name) override {
        PROBE(L"GetTitle " + ProbeItems(items));
        return SHStrDupW(Title(), name);
    }
    IFACEMETHODIMP GetIcon(IShellItemArray* items, PWSTR* icon) override {
        PROBE(L"GetIcon " + ProbeItems(items));
        try {
            return SHStrDupW((ExePath() + L",0").c_str(), icon);
        } catch (...) {
            *icon = nullptr;
            return E_FAIL;
        }
    }
    IFACEMETHODIMP GetToolTip(IShellItemArray* items, PWSTR* tip) override {
        PROBE(L"GetToolTip " + ProbeItems(items));
        *tip = nullptr;
        return E_NOTIMPL;
    }
    IFACEMETHODIMP GetCanonicalName(GUID* name) override {
        PROBE(L"GetCanonicalName");
        *name = ServerClsid();
        return S_OK;
    }
    // Shown only when the selection holds at least one folder or photo.
    IFACEMETHODIMP GetState(IShellItemArray* items, BOOL ok_to_be_slow, EXPCMDSTATE* state) override {
        HRESULT result = ComputeState(items, state);
#ifdef PC_HIDE_IN_CLASSIC_MENU
        if (classic_site_ && !ok_to_be_slow) {
            *state = ECS_HIDDEN;  // the copy under "Show more options"
            PROBE(L"classic menu site: entry hidden here");
        }
#endif
        PROBE(L"GetState ok_to_be_slow=" + std::to_wstring(ok_to_be_slow) + L" " + ProbeItems(items) +
              L" -> state=" + std::to_wstring(static_cast<int>(*state)));
        (void)ok_to_be_slow;
        return result;
    }
    static HRESULT ComputeState(IShellItemArray* items, EXPCMDSTATE* state) {
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
    IFACEMETHODIMP Invoke(IShellItemArray* items, IBindCtx* bind_context) override {
        PROBE(L"Invoke " + ProbeItems(items) + (bind_context ? L" bindctx=set" : L" bindctx=null"));
        (void)bind_context;
        try {
            std::vector<std::wstring> paths = OpenablePaths(items);
            if (paths.empty()) return S_OK;
            return LaunchApplication(paths);
        } catch (...) {
            return E_FAIL;
        }
    }
    IFACEMETHODIMP GetFlags(EXPCMDFLAGS* flags) override {
        PROBE(L"GetFlags");
        *flags = ECF_DEFAULT;
        return S_OK;
    }
    IFACEMETHODIMP EnumSubCommands(IEnumExplorerCommand** commands) override {
        PROBE(L"EnumSubCommands");
        *commands = nullptr;
        return E_NOTIMPL;
    }

    // IObjectWithSite
    IFACEMETHODIMP SetSite(IUnknown* site) override {
        PROBE(L"SetSite " + ProbeSite(site));
        if (site) site->AddRef();
        if (site_) site_->Release();
        site_ = site;
#ifdef PC_HIDE_IN_CLASSIC_MENU
        classic_site_ = IsClassicMenuSite(site);
#endif
        return S_OK;
    }
    IFACEMETHODIMP GetSite(REFIID riid, void** site) override {
        PROBE(L"GetSite iid=" + ProbeGuid(riid));
        if (!site_) {
            *site = nullptr;
            return E_FAIL;
        }
        return site_->QueryInterface(riid, site);
    }

private:
    ~PlancheCommand() {
        PROBE(L"dtor");
        if (site_) site_->Release();
        InterlockedDecrement(&g_liveObjects);
    }

    LONG refs_;
    IUnknown* site_;
#ifdef PC_HIDE_IN_CLASSIC_MENU
    bool classic_site_ = false;  // set by SetSite: the classic menu is calling
#endif
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
    PROBE(L"DllGetClassObject clsid=" + ProbeGuid(clsid) + L" iid=" + ProbeGuid(riid) +
          L" dll=" + ModuleDirectory());
    if (clsid != ServerClsid()) return CLASS_E_CLASSNOTAVAILABLE;
    PlancheFactory* factory = new (std::nothrow) PlancheFactory();
    if (!factory) return E_OUTOFMEMORY;
    HRESULT result = factory->QueryInterface(riid, object);
    factory->Release();
    return result;
}

STDAPI DllCanUnloadNow() { return g_liveObjects == 0 ? S_OK : S_FALSE; }
