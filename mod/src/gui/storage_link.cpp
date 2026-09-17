#include "storage_link.h"

#include <Windows.h>
#include <cstdio>

#include "../core/log.h"

namespace ml::psm
{
    namespace
    {
        Api   g_api{};
        bool  g_ok = false;
        bool  g_refused = false;   // found but unusable; that does not change while the game runs
        DWORD g_nextTry = 0;
        char  g_why[96] = "not installed";

        bool Bind(HMODULE h)
        {
            Api a{};
            bool all = true;
            const auto get = [&](const char* name) {
                const FARPROC p = GetProcAddress(h, name);
                if (!p) all = false;
                return p;
            };
            a.apiVersion     = reinterpret_cast<int (*)(void)>(get("PsmApiVersion"));
            a.storageName    = reinterpret_cast<const char* (*)(int)>(get("PsmStorageName"));
            a.storageKey     = reinterpret_cast<const char* (*)(int)>(get("PsmStorageKey"));
            a.getStatus      = reinterpret_cast<int (*)(PsmStatus*)>(get("PsmGetStatus"));
            a.getSettings    = reinterpret_cast<int (*)(PsmSettings*)>(get("PsmGetSettings"));
            a.getDefaults    = reinterpret_cast<int (*)(PsmSettings*)>(get("PsmGetDefaults"));
            a.applySettings  = reinterpret_cast<int (*)(const PsmSettings*, char*, int)>(get("PsmApplySettings"));
            a.reloadSettings = reinterpret_cast<int (*)(void)>(get("PsmReloadSettings"));
            a.getSize        = reinterpret_cast<int (*)(int, PsmSize*)>(get("PsmGetSize"));
            a.writeDump      = reinterpret_cast<void (*)(void)>(get("PsmWriteDump"));
            a.pauseInput     = reinterpret_cast<void (*)(uint32_t)>(get("PsmPauseInput"));
            a.keyText        = reinterpret_cast<int (*)(PsmKey, char*, int)>(get("PsmKeyText"));
            a.padText        = reinterpret_cast<int (*)(PsmPad, char*, int)>(get("PsmPadText"));
            a.fixedSlots     = reinterpret_cast<int (*)(int)>(GetProcAddress(h, "PsmFixedSlots"));   // optional
            if (!a.apiVersion)
            {
                snprintf(g_why, sizeof g_why, "found, but it has no interface (an older build)");
                return false;
            }
            const int v = a.apiVersion();
            if (v != PSM_API_VERSION)
            {
                snprintf(g_why, sizeof g_why, "interface %d, this build of Master Looter speaks %d", v, PSM_API_VERSION);
                return false;
            }
            if (!all)
            {
                snprintf(g_why, sizeof g_why, "interface %d but a function is missing", v);
                return false;
            }
            g_api = a;
            return true;
        }
    }

    const Api* Get()
    {
        if (g_ok) return &g_api;
        if (g_refused) return nullptr;
        const DWORD now = GetTickCount();
        if (g_nextTry && static_cast<LONG>(now - g_nextTry) < 0) return nullptr;
        g_nextTry = now + 2000;
        const HMODULE h = GetModuleHandleW(L"PrivateStorageMaster.asi");
        if (!h) { snprintf(g_why, sizeof g_why, "not installed"); return nullptr; }
        g_ok = Bind(h);
        if (g_ok) { g_why[0] = 0; LOG("[storage] Private Storage Master found, interface %d", PSM_API_VERSION); }
        else { g_refused = true; LOG_ERR("[storage] Private Storage Master %s", g_why); }
        return g_ok ? &g_api : nullptr;
    }

    const char* Why() { return g_why; }

    bool Installed() { Get(); return g_ok || g_refused; }
}
