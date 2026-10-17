// SPDX-License-Identifier: AGPL-3.0-or-later
#include <windows.h>
#include <string>
#include <vector>

#ifdef _WIN64
static const wchar_t* cameraId = L"{D9B25791-5540-48BE-842C-C73BF8540340}";
static const wchar_t* propertiesId = L"{D9B25791-5540-48BE-842C-C73BF8540341}";
#else
static const wchar_t* cameraId = L"{D9B25791-5540-48BE-842C-C73BF8540342}";
static const wchar_t* propertiesId = L"{D9B25791-5540-48BE-842C-C73BF8540343}";
#endif
static const wchar_t* category = L"Software\\Classes\\CLSID\\{860BB310-5D01-11D0-BD3B-00A0C911CE86}\\Instance\\";
static std::wstring module() {
    HMODULE handle = nullptr;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCWSTR>(&module), &handle);
    wchar_t path[32768]; DWORD count = GetModuleFileNameW(handle, path, 32768);
    return count && count < 32768 ? std::wstring(path, count) : std::wstring();
}
static std::wstring classKey(const wchar_t* id) { return std::wstring(L"Software\\Classes\\CLSID\\") + id; }
static bool exists(const std::wstring& path) {
    HKEY key;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, path.c_str(), 0, KEY_READ, &key) != ERROR_SUCCESS) return false;
    RegCloseKey(key); return true;
}
static std::wstring devicePath() {
    wchar_t value[256]; DWORD size = sizeof(value);
    if (RegGetValueW(HKEY_CURRENT_USER, (std::wstring(category) + cameraId).c_str(), L"DevicePath", RRF_RT_REG_SZ,
        nullptr, value, &size) != ERROR_SUCCESS) return L"";
    return value;
}
static std::wstring registered(const wchar_t* id) {
    wchar_t path[32768]; DWORD size = sizeof(path), type = 0;
    if (RegGetValueW(HKEY_CURRENT_USER, (classKey(id) + L"\\InprocServer32").c_str(), nullptr,
        RRF_RT_REG_SZ, &type, path, &size) != ERROR_SUCCESS) return L"";
    return path;
}
static LONG write(const std::wstring& path, const wchar_t* name, const std::wstring& value) {
    HKEY key; LONG result = RegCreateKeyExW(HKEY_CURRENT_USER, path.c_str(), 0, nullptr, 0, KEY_SET_VALUE, nullptr, &key, nullptr);
    if (result != ERROR_SUCCESS) return result;
    result = RegSetValueExW(key, name, 0, REG_SZ, reinterpret_cast<const BYTE*>(value.c_str()),
        static_cast<DWORD>((value.size() + 1) * sizeof(wchar_t)));
    RegCloseKey(key); return result;
}
STDAPI DllRegisterServer() {
    std::wstring path = module();
    if (path.empty()) return E_FAIL;
    // Another installation is never silently replaced. Saiph's installer removes
    // only its owned old registration before the new release is first used.
    for (auto id : {cameraId, propertiesId}) {
        auto old = registered(id);
        if (exists(classKey(id)) && (old.empty() || _wcsicmp(old.c_str(), path.c_str()))) return HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS);
    }
    if (exists(std::wstring(category) + cameraId) && devicePath() != std::wstring(L"saiph:camera:") + cameraId)
        return HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS);
    std::vector<std::wstring> created;
    LONG result = ERROR_SUCCESS;
    for (auto id : {cameraId, propertiesId}) {
        std::wstring key = classKey(id), server = key + L"\\InprocServer32";
        created.push_back(key);
        if ((result = write(key, nullptr, L"Saiph Camera")) || (result = write(server, nullptr, path))
            || (result = write(server, L"ThreadingModel", L"Both"))) break;
    }
    std::wstring instance = std::wstring(category) + cameraId;
    if (!result) {
        created.push_back(instance);
        if (!(result = write(instance, L"CLSID", cameraId)) && !(result = write(instance, L"FriendlyName", L"Saiph Camera")))
            result = write(instance, L"DevicePath", std::wstring(L"saiph:camera:") + cameraId);
    }
    if (result) for (const auto& key : created) RegDeleteTreeW(HKEY_CURRENT_USER, key.c_str());
    return HRESULT_FROM_WIN32(result);
}
STDAPI DllUnregisterServer() {
    auto path = module();
    if (path.empty()) return E_FAIL;
    bool ownsCamera = false;
    for (auto id : {cameraId, propertiesId}) {
        auto old = registered(id);
        if (exists(classKey(id)) && (old.empty() || _wcsicmp(old.c_str(), path.c_str()))) return E_ACCESSDENIED;
        if (id == cameraId && !old.empty()) ownsCamera = true;
    }
    if (ownsCamera && devicePath() == std::wstring(L"saiph:camera:") + cameraId)
        RegDeleteTreeW(HKEY_CURRENT_USER, (std::wstring(category) + cameraId).c_str());
    for (auto id : {cameraId, propertiesId}) RegDeleteTreeW(HKEY_CURRENT_USER, classKey(id).c_str());
    return S_OK;
}
