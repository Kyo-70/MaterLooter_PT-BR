#include "stack_link.h"

#include <Windows.h>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <mutex>

#include "../core/log.h"
#include "../core/text.h"

namespace ml::stack
{
    namespace
    {
        // Only the menu asks, so one thread, but the lock and the published
        // flag follow the storage link next door rather than inventing a
        // second pattern for the same job.
        std::mutex        g_lock;
        Api               g_api{};
        std::atomic<bool> g_ok{false};
        bool  g_refused = false;   // found and unusable, which does not change while the game runs
        DWORD g_nextTry = 0;
        char  g_why[128] = "not installed";
        char  g_refusedOther[160] = "";
        char  g_refusedModule[40] = "";

        // Master Stack first: when both are loaded it is the one that applies
        // the multiplier and Private Storage Master stands down.
        const wchar_t* const kModules[] = { L"MasterStack.asi", L"PrivateStorageMaster.asi" };

        bool Bind(HMODULE h, const wchar_t* name, Api* out)
        {
            Api a{};
            a.module          = name;
            a.apiVersion      = reinterpret_cast<int (*)(void)>(GetProcAddress(h, "StackApiVersion"));
            a.getStatus       = reinterpret_cast<int (*)(StackStatus*)>(GetProcAddress(h, "StackGetStatus"));
            a.getMultiplier   = reinterpret_cast<int (*)(void)>(GetProcAddress(h, "StackGetMultiplier"));
            a.standDownText   = reinterpret_cast<int (*)(int, char*, int)>(GetProcAddress(h, "StackStandDownText"));   // optional
            a.applyMultiplier = reinterpret_cast<int (*)(int, char*, int)>(GetProcAddress(h, "StackApplyMultiplier"));
            if (!a.apiVersion)
            {
                // Said rather than passed over: this module may be the one the
                // game is listening to, and the tab has to be able to name it.
                snprintf(g_why, sizeof g_why, "has no stack interface (an older build of it)");
                return false;
            }
            const int v = a.apiVersion();
            if (v != STACK_API_VERSION)
            {
                snprintf(g_why, sizeof g_why, "interface %d, this build of Master Looter speaks %d", v, STACK_API_VERSION);
                return false;
            }
            if (!a.getStatus || !a.getMultiplier || !a.applyMultiplier)
            {
                snprintf(g_why, sizeof g_why, "interface %d but a function is missing", v);
                return false;
            }
            *out = a;
            return true;
        }

        // How much a stand-down reason is worth saying, when no provider is
        // applying the multiplier and its reason is the only thing the tab can
        // show. A provider that is merely switched off, or that stood aside for
        // the other one, sends the player to the wrong file: with Master Stack
        // installed and off, Private Storage Master says "Master Stack sets the
        // stack sizes instead" and the setting to change is Master Stack's.
        // A broken hook outranks both, because that is the one a player can
        // act on.
        int Actionable(int reason)
        {
            switch (reason)
            {
            case STACK_STANDDOWN_NO_ANCHOR:
            case STACK_STANDDOWN_HOOK_FAILED:
            case STACK_STANDDOWN_TOO_LATE:   return 3;
            case STACK_STANDDOWN_OFF:        return 1;
            case STACK_STANDDOWN_OTHER_MOD:
            case STACK_STANDDOWN_NONE:       return 0;
            default:                         return 2;   // a reason added after this build
            }
        }

        // Of the providers that answered, the one to edit. Whichever says it
        // is applying the multiplier, in the order above. Failing that, the one
        // whose reason is worth showing, since editing it turns the feature on
        // from the next launch anyway. Decided once: neither applying nor the
        // reason changes without a restart.
        bool Choose(const Api* found, int n, Api* out)
        {
            if (n <= 0) return false;
            for (int i = 0; i < n; ++i)
            {
                StackStatus s{};
                s.size = sizeof s;
                if (found[i].getStatus(&s) && s.applying) { *out = found[i]; return true; }
            }
            // A provider whose status call fails is the case that looked
            // like no provider at all: Private Storage Master moved a field
            // into the middle of the struct on 19 September 2026, refused a
            // size it did not know, and the tab went quiet with nothing in the
            // log. Whoever does that next gets named.
            int best = 0, bestScore = -1;
            for (int i = 0; i < n; ++i)
            {
                StackStatus s{};
                s.size = sizeof s;
                int score = -1;
                if (found[i].getStatus(&s)) score = Actionable(s.standDownReason);
                else
                {
                    char mod[64] = {};
                    WideCharToMultiByte(CP_UTF8, 0, found[i].module, -1, mod, sizeof mod - 1, nullptr, nullptr);
                    LOG_ERR("[stacks] %s answered its interface but not its status; this build may be older than it", mod);
                }
                if (score > bestScore) { bestScore = score; best = i; }
            }
            *out = found[best];
            return true;
        }
    }

    const Api* Get()
    {
        if (g_ok.load(std::memory_order_acquire)) return &g_api;
        std::lock_guard<std::mutex> lk(g_lock);
        if (g_ok.load(std::memory_order_relaxed)) return &g_api;
        if (g_refused) return nullptr;
        const DWORD now = GetTickCount();
        if (g_nextTry && static_cast<LONG>(now - g_nextTry) < 0) return nullptr;
        g_nextTry = now + 2000;

        Api found[2]{};
        int n = 0;
        bool seen = false, refused = false;
        g_refusedOther[0] = 0;
        g_refusedModule[0] = 0;
        for (const wchar_t* name : kModules)
        {
            const HMODULE h = GetModuleHandleW(name);
            if (!h) continue;
            seen = true;
            if (Bind(h, name, &found[n])) { ++n; continue; }
            if (!g_why[0] || strcmp(g_why, "not installed") == 0) continue;
            refused = true;
            // Kept even when the other provider binds. A refusal used to be
            // reported only when nothing bound at all, so a Master Stack this
            // build cannot speak to went unmentioned while the tab quietly
            // edited the mod standing down for it.
            WideCharToMultiByte(CP_UTF8, 0, name, -1, g_refusedModule, sizeof g_refusedModule - 1, nullptr, nullptr);
            snprintf(g_refusedOther, sizeof g_refusedOther, "%s is installed and %s", g_refusedModule, g_why);
        }
        if (!n)
        {
            // A plugin that is loaded but has no stack interface is an older
            // build of it, which is not worth a tab or an error.
            if (!seen || !refused) snprintf(g_why, sizeof g_why, "not installed");
            g_refused = refused;
            if (refused) LOG_ERR("[stacks] the stack multiplier is %s", g_why);
            return nullptr;
        }
        Choose(found, n, &g_api);
        g_why[0] = 0;
        if (g_refusedOther[0]) LOG_ERR("[stacks] %s", g_refusedOther);
        char mod[64] = {};
        WideCharToMultiByte(CP_UTF8, 0, g_api.module, -1, mod, sizeof mod - 1, nullptr, nullptr);
        LOG("[stacks] stack multiplier provided by %s, interface %d%s", mod, STACK_API_VERSION,
            n > 1 ? ", one of two installed" : "");
        g_ok.store(true, std::memory_order_release);
        return &g_api;
    }

    const char* Why() { return g_why; }

    const char* RefusedOther() { Get(); return g_refusedOther; }

    const char* RefusedModule() { Get(); return g_refusedModule; }

    bool Installed()
    {
        Get();
        std::lock_guard<std::mutex> lk(g_lock);
        return g_ok.load(std::memory_order_relaxed) || g_refused;
    }

    const char* StandDownText(int code)
    {
        static char s_text[256];
        const Api* a = Get();
        if (a && a->standDownText)
        {
            s_text[0] = 0;
            // Its answer is used whether or not it knew the code: it writes a
            // printable line either way, and its line for a code added after
            // this build names the thing this build cannot.
            a->standDownText(code, s_text, sizeof s_text);
            if (s_text[0]) return s_text;
        }
        switch (code)
        {
        case STACK_STANDDOWN_NONE:        return TR("it is the one changing stack limits");
        case STACK_STANDDOWN_OFF:         return TR("the multiplier is 1, so nothing is changed");
        case STACK_STANDDOWN_OTHER_MOD:   return TR("another mod is changing stack limits instead");
        case STACK_STANDDOWN_NO_ANCHOR:   return TR("it could not find where the game reads its item table");
        case STACK_STANDDOWN_HOOK_FAILED: return TR("its hook could not be installed");
        case STACK_STANDDOWN_TOO_LATE:    return TR("the game had already read its item table");
        default:                          return TR("a reason this build of Master Looter does not know");
        }
    }
}
