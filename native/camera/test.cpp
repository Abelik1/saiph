// SPDX-License-Identifier: AGPL-3.0-or-later
// Isolated in-process component check. Does not install a system camera.
#include "shared.inl"
#include <dshow.h>
#include <string>
#include <vector>
#include <stdio.h>

static void require(bool value, const char* message) { if (!value) { fprintf(stderr, "%s\n", message); ExitProcess(1); } }
#ifdef _WIN64
static const wchar_t* cameraClass = L"{D9B25791-5540-48BE-842C-C73BF8540340}";
static const wchar_t* propertiesClass = L"{D9B25791-5540-48BE-842C-C73BF8540341}";
static const wchar_t* componentName = L"SaiphCamera64.dll";
#else
static const wchar_t* cameraClass = L"{D9B25791-5540-48BE-842C-C73BF8540342}";
static const wchar_t* propertiesClass = L"{D9B25791-5540-48BE-842C-C73BF8540343}";
static const wchar_t* componentName = L"SaiphCamera32.dll";
#endif
static void seed(const std::wstring& server) {
    for (auto id : {cameraClass, propertiesClass})
        require(RegSetKeyValueW(HKEY_CURRENT_USER, (std::wstring(L"Software\\Classes\\CLSID\\") + id + L"\\InprocServer32").c_str(), nullptr, REG_SZ,
            server.c_str(), static_cast<DWORD>((server.size() + 1) * sizeof(wchar_t))) == ERROR_SUCCESS, "test registration seed failed");
}
static std::wstring server(const wchar_t* id) {
    wchar_t value[32768]; DWORD size = sizeof(value);
    if (RegGetValueW(HKEY_CURRENT_USER, (std::wstring(L"Software\\Classes\\CLSID\\") + id + L"\\InprocServer32").c_str(), nullptr,
        RRF_RT_REG_SZ, nullptr, value, &size) != ERROR_SUCCESS) return L"";
    return value;
}
// A release-folder copy of the component replaces a registration from another release
// folder of its own installation, and still refuses every other existing registration.
static void releaseFolderRegistration(const wchar_t* source) {
    wchar_t temp[MAX_PATH + 1]; require(GetTempPathW(MAX_PATH + 1, temp) > 0, "temporary folder missing");
    std::wstring root = std::wstring(temp) + L"SaiphCameraTest-" + std::to_wstring(GetCurrentProcessId()), folder = root;
    std::vector<std::wstring> created;
    for (auto part : {L"\\releases", L"\\2", L"\\app", L"\\_internal", L"\\camera"}) {
        if (created.empty()) { require(CreateDirectoryW(root.c_str(), nullptr) != 0, "test release root already exists"); created.push_back(root); }
        folder += part; require(CreateDirectoryW(folder.c_str(), nullptr) != 0, "test release folder failed"); created.push_back(folder);
    }
    std::wstring copy = folder + L"\\" + componentName;
    require(CopyFileW(source, copy.c_str(), TRUE) != 0, "test release component copy failed");
    HMODULE dll = LoadLibraryW(copy.c_str()); require(dll != nullptr, "release-folder component load failed");
    auto reg = reinterpret_cast<HRESULT(STDAPICALLTYPE*)()>(GetProcAddress(dll, "DllRegisterServer"));
    auto unreg = reinterpret_cast<HRESULT(STDAPICALLTYPE*)()>(GetProcAddress(dll, "DllUnregisterServer"));
    wchar_t loaded[32768]; DWORD length = GetModuleFileNameW(dll, loaded, 32768); require(length > 0 && length < 32768, "component path missing");
    std::wstring sibling = root + L"\\releases\\1\\app\\_internal\\camera\\" + componentName;
    seed(sibling);
    require(SUCCEEDED(reg()), "an earlier release folder's registration was not replaced");
    require(server(cameraClass) == loaded && server(propertiesClass) == loaded, "replacement did not register the new release");
    require(SUCCEEDED(unreg()), "replaced registration cleanup failed");
    for (const std::wstring& foreign : {root + L"-other\\releases\\1\\app\\_internal\\camera\\" + componentName,
                                        root + L"\\releases\\1\\app\\_internal\\camera\\SaiphCameraOther.dll",
                                        root + L"\\camera\\" + componentName, std::wstring(L"C:\\Windows\\System32\\") + componentName}) {
        seed(foreign);
        require(reg() == HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS) && server(cameraClass) == foreign, "a foreign registration was replaced");
    }
    for (auto id : {cameraClass, propertiesClass}) RegDeleteTreeW(HKEY_CURRENT_USER, (std::wstring(L"Software\\Classes\\CLSID\\") + id).c_str());
    FreeLibrary(dll);
    require(DeleteFileW(copy.c_str()) != 0, "test release component removal failed");
    for (auto it = created.rbegin(); it != created.rend(); ++it) RemoveDirectoryW(it->c_str());
}
static unsigned char first = 0;
static int expectedWidth = 1280, expectedHeight = 720;
static void received(int width, int height, int stride, SharedImageMemory::EFormat, SharedImageMemory::EResizeMode,
    SharedImageMemory::EMirrorMode, int, uint8_t* buffer, void*) {
    require(width == expectedWidth && height == expectedHeight && stride == expectedWidth, "invalid received dimensions"); first = buffer[0];
}
int wmain(int argc, wchar_t** argv) {
    require(argc == 2 || argc == 3, "expected component DLL path and optional 1080p");
    if (argc == 3) { require(!wcscmp(argv[2], L"1080p"), "unknown test mode"); expectedWidth = 1920; expectedHeight = 1080; }
    HMODULE dll = LoadLibraryW(argv[1]); require(dll != nullptr, "component load failed");
    auto reg = reinterpret_cast<HRESULT(STDAPICALLTYPE*)()>(GetProcAddress(dll, "DllRegisterServer"));
    auto unreg = reinterpret_cast<HRESULT(STDAPICALLTYPE*)()>(GetProcAddress(dll, "DllUnregisterServer"));
    auto push = reinterpret_cast<int(*)(const unsigned char*, unsigned int)>(GetProcAddress(dll, "SaiphCameraWrite"));
    auto pushSized = reinterpret_cast<int(*)(const unsigned char*, unsigned int, unsigned int, unsigned int)>(GetProcAddress(dll, "SaiphCameraWriteSized"));
    auto stop = reinterpret_cast<void(*)()>(GetProcAddress(dll, "SaiphCameraStop"));
    require(reg && unreg && push && pushSized && stop, "component exports missing");
    // Override HKCU only in this process, into a newly owned test subtree.
    std::wstring sandbox = L"Software\\OrionMini\\CameraComponentTests\\" + std::to_wstring(GetCurrentProcessId());
    HKEY hive; DWORD disposition;
    require(RegCreateKeyExW(HKEY_CURRENT_USER, sandbox.c_str(), 0, nullptr, 0, KEY_ALL_ACCESS, nullptr, &hive, &disposition) == ERROR_SUCCESS
        && disposition == REG_CREATED_NEW_KEY, "test registry subtree already exists");
    require(RegOverridePredefKey(HKEY_CURRENT_USER, hive) == ERROR_SUCCESS, "test registry override failed");
    releaseFolderRegistration(argv[1]);
    require(SUCCEEDED(reg()), "per-user camera registration failed");
    require(SUCCEEDED(reg()), "idempotent camera registration failed");
    // The class factory is loaded directly, without global COM registration.
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    auto get = reinterpret_cast<HRESULT(STDAPICALLTYPE*)(REFCLSID, REFIID, LPVOID*)>(GetProcAddress(dll, "DllGetClassObject"));
#ifdef _WIN64
    const wchar_t* id = L"{D9B25791-5540-48BE-842C-C73BF8540340}";
#else
    const wchar_t* id = L"{D9B25791-5540-48BE-842C-C73BF8540342}";
#endif
    CLSID clsid; require(SUCCEEDED(CLSIDFromString(id, &clsid)), "CLSID failed");
    IClassFactory* factory = nullptr;
    require(SUCCEEDED(get(clsid, IID_IClassFactory, reinterpret_cast<void**>(&factory))), "camera class factory failed");
    IBaseFilter* filter = nullptr;
    require(SUCCEEDED(factory->CreateInstance(nullptr, IID_IBaseFilter, reinterpret_cast<void**>(&filter))), "DirectShow source creation failed");
    IEnumPins* pins = nullptr; IPin* pin = nullptr;
    require(SUCCEEDED(filter->EnumPins(&pins)) && pins->Next(1, &pin, nullptr) == S_OK, "DirectShow output pin missing");
    IAMStreamConfig* config = nullptr;
    require(SUCCEEDED(pin->QueryInterface(IID_IAMStreamConfig, reinterpret_cast<void**>(&config))), "camera stream configuration missing");
    AM_MEDIA_TYPE* media = nullptr;
    require(SUCCEEDED(config->GetFormat(&media)), "camera media format missing");
    auto video = reinterpret_cast<VIDEOINFOHEADER*>(media->pbFormat);
    require(video->bmiHeader.biWidth == 1280 && video->bmiHeader.biHeight == 720, "camera default is not 720p");
    CoTaskMemFree(media->pbFormat); CoTaskMemFree(media);
    VIDEO_STREAM_CONFIG_CAPS caps;
    require(SUCCEEDED(config->GetStreamCaps(1, &media, reinterpret_cast<BYTE*>(&caps))), "1080p format missing");
    video = reinterpret_cast<VIDEOINFOHEADER*>(media->pbFormat);
    require(video->bmiHeader.biWidth == 1920 && video->bmiHeader.biHeight == 1080, "camera does not advertise 1080p");
    require(caps.MinFrameInterval == 10000000 / 30 && caps.MaxFrameInterval == 10000000 / 15, "incorrect frame-rate capabilities");
    if (argc == 3) { video->AvgTimePerFrame = 10000000 / 20; require(SUCCEEDED(config->SetFormat(media)), "1080p20 negotiation failed"); }
    CoTaskMemFree(media->pbFormat); CoTaskMemFree(media);
    IGraphBuilder* graph = nullptr; IBaseFilter* renderer = nullptr;
    CLSID nullRendererId;
    require(SUCCEEDED(CLSIDFromString(L"{C1F400A4-3F08-11D3-9F0B-006008039E37}", &nullRendererId)), "null renderer identifier failed");
    require(SUCCEEDED(CoCreateInstance(CLSID_FilterGraph, nullptr, CLSCTX_INPROC_SERVER, IID_IGraphBuilder, reinterpret_cast<void**>(&graph))), "DirectShow graph missing");
    require(SUCCEEDED(CoCreateInstance(nullRendererId, nullptr, CLSCTX_INPROC_SERVER, IID_IBaseFilter, reinterpret_cast<void**>(&renderer))), "DirectShow test renderer missing");
    require(SUCCEEDED(graph->AddFilter(filter, L"Saiph camera test")) && SUCCEEDED(graph->AddFilter(renderer, L"Synthetic receiver")), "DirectShow graph setup failed");
    IEnumPins* receiverPins = nullptr; IPin* receiverPin = nullptr;
    require(SUCCEEDED(renderer->EnumPins(&receiverPins)) && receiverPins->Next(1, &receiverPin, nullptr) == S_OK, "test receiver pin missing");
    require(SUCCEEDED(graph->ConnectDirect(pin, receiverPin, nullptr)), "DirectShow consumer could not negotiate the camera format");
    IMediaControl* control = nullptr;
    require(SUCCEEDED(graph->QueryInterface(IID_IMediaControl, reinterpret_cast<void**>(&control))) && SUCCEEDED(control->Run()), "DirectShow capture could not run");
    SharedImageMemory receiver(0);
    std::vector<unsigned char> rgba(expectedWidth * expectedHeight * 4, 37);
    require(push(rgba.data(), 1) == -1, "invalid producer frame accepted");
    require(pushSized(rgba.data(), 1, expectedWidth, expectedHeight) == -1, "invalid sized frame accepted");
    require(pushSized(rgba.data(), static_cast<unsigned>(rgba.size()), 65535, 65535) == -1, "invalid dimensions accepted");
    for (int i = 0; i < 20 && first != 37; ++i) { receiver.Receive(received, nullptr); pushSized(rgba.data(), static_cast<unsigned>(rgba.size()), expectedWidth, expectedHeight); }
    receiver.Receive(received, nullptr); require(first == 37, "native frame IPC round trip failed");
    stop(); receiver.Receive(received, nullptr); require(first == 0, "stop did not blank the camera");
    OAFilterState state;
    require(SUCCEEDED(control->GetState(2000, &state)) && state == State_Running, "DirectShow consumer did not stream");
    ICreateDevEnum* devices = nullptr;
    require(SUCCEEDED(CoCreateInstance(CLSID_SystemDeviceEnum, nullptr, CLSCTX_INPROC_SERVER, IID_ICreateDevEnum, reinterpret_cast<void**>(&devices))), "DirectShow device enumeration missing");
    HKEY classes;
    require(RegOpenKeyExW(hive, L"Software\\Classes", 0, KEY_ALL_ACCESS, &classes) == ERROR_SUCCESS, "test classes missing");
    require(RegOverridePredefKey(HKEY_CLASSES_ROOT, classes) == ERROR_SUCCESS, "test class-view override failed");
    IEnumMoniker* cameras = nullptr; IMoniker* camera = nullptr;
    require(devices->CreateClassEnumerator(CLSID_VideoInputDeviceCategory, &cameras, 0) == S_OK,
        "registered camera does not enumerate in the isolated DirectShow category");
    bool found = false;
    while (cameras->Next(1, &camera, nullptr) == S_OK) {
        IPropertyBag* properties = nullptr;
        require(SUCCEEDED(camera->BindToStorage(nullptr, nullptr, IID_IPropertyBag, reinterpret_cast<void**>(&properties))), "camera device properties missing");
        VARIANT name; VariantInit(&name);
        if (SUCCEEDED(properties->Read(L"FriendlyName", &name, nullptr)) && name.vt == VT_BSTR && !wcscmp(name.bstrVal, L"Saiph Camera")) found = true;
        VariantClear(&name); properties->Release(); camera->Release();
    }
    require(found, "Saiph Camera device name was not enumerated");
    cameras->Release(); devices->Release();
    require(RegOverridePredefKey(HKEY_CLASSES_ROOT, nullptr) == ERROR_SUCCESS, "test class-view restore failed");
    RegCloseKey(classes);
    control->Stop(); control->Release(); receiverPin->Release(); receiverPins->Release(); renderer->Release(); graph->Release();
    config->Release(); pin->Release(); pins->Release(); filter->Release(); factory->Release(); CoUninitialize();
    require(SUCCEEDED(unreg()), "owned camera cleanup failed");
    require(RegOverridePredefKey(HKEY_CURRENT_USER, nullptr) == ERROR_SUCCESS, "test registry restore failed");
    RegCloseKey(hive); RegDeleteTreeW(HKEY_CURRENT_USER, sandbox.c_str());
    FreeLibrary(dll);
    puts("PASS: isolated registration, DirectShow streaming graph, 720p/1080p capabilities, frame IPC, bounds, stop blanking and release-folder re-registration. No system camera installed.");
    return 0;
}
