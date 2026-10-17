// SPDX-License-Identifier: AGPL-3.0-or-later
// Isolated in-process component check. Does not install a system camera.
#include "shared.inl"
#include <dshow.h>
#include <string>
#include <vector>
#include <stdio.h>

static void require(bool value, const char* message) { if (!value) { fprintf(stderr, "%s\n", message); ExitProcess(1); } }
static unsigned char first = 0;
static void received(int width, int height, int stride, SharedImageMemory::EFormat, SharedImageMemory::EResizeMode,
    SharedImageMemory::EMirrorMode, int, uint8_t* buffer, void*) {
    require(width == 1280 && height == 720 && stride == 1280, "invalid received dimensions"); first = buffer[0];
}
int wmain(int argc, wchar_t** argv) {
    require(argc == 2, "expected component DLL path");
    HMODULE dll = LoadLibraryW(argv[1]); require(dll != nullptr, "component load failed");
    auto reg = reinterpret_cast<HRESULT(STDAPICALLTYPE*)()>(GetProcAddress(dll, "DllRegisterServer"));
    auto unreg = reinterpret_cast<HRESULT(STDAPICALLTYPE*)()>(GetProcAddress(dll, "DllUnregisterServer"));
    auto push = reinterpret_cast<int(*)(const unsigned char*, unsigned int)>(GetProcAddress(dll, "SaiphCameraWrite"));
    auto stop = reinterpret_cast<void(*)()>(GetProcAddress(dll, "SaiphCameraStop"));
    require(reg && unreg && push && stop, "component exports missing");
    // Override HKCU only in this process, into a newly owned test subtree.
    std::wstring sandbox = L"Software\\OrionMini\\CameraComponentTests\\" + std::to_wstring(GetCurrentProcessId());
    HKEY hive; DWORD disposition;
    require(RegCreateKeyExW(HKEY_CURRENT_USER, sandbox.c_str(), 0, nullptr, 0, KEY_ALL_ACCESS, nullptr, &hive, &disposition) == ERROR_SUCCESS
        && disposition == REG_CREATED_NEW_KEY, "test registry subtree already exists");
    require(RegOverridePredefKey(HKEY_CURRENT_USER, hive) == ERROR_SUCCESS, "test registry override failed");
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
    std::vector<unsigned char> rgba(1280 * 720 * 4, 37);
    require(push(rgba.data(), 1) == -1, "invalid producer frame accepted");
    for (int i = 0; i < 20 && first != 37; ++i) { receiver.Receive(received, nullptr); push(rgba.data(), static_cast<unsigned>(rgba.size())); }
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
    puts("PASS: isolated registration, DirectShow 720p streaming graph, frame IPC, bounds and stop blanking. No system camera installed.");
    return 0;
}
