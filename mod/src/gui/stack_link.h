#pragma once
#include "stack_api.h"

// The item stack multiplier, from whichever plugin beside this one provides
// it. Stack Master and Private Storage Master both can; Stack Master wins
// when both are loaded, by their own arrangement, and the other stands down.
//
// Nothing here links against either. Each module is looked up by name and
// each function by name, and a provider is used only when its interface
// version matches the header this build was compiled with. With neither
// present the Stacks tab is not drawn.
namespace ml::stack
{
    struct Api
    {
        int (*apiVersion)(void);
        int (*getStatus)(StackStatus*);
        int (*getMultiplier)(void);
        int (*standDownText)(int, char*, int);   // optional; a provider built before it is null
        int (*applyMultiplier)(int, char*, int);
        const wchar_t* module;   // the module name it was found under
    };

    // The provider to edit: the one that says it is applying the multiplier,
    // Stack Master first when both claim it, and otherwise the first that
    // answered at all, since applying it there turns the feature on. Null
    // when neither is installed or neither has a usable interface. Cheap to
    // call every frame; a miss is retried every two seconds.
    const Api* Get();

    // What the lookup found, for the tab's first line: "not installed",
    // "interface 2, this build speaks 1", and so on. Empty on success.
    const char* Why();

    // Found in the process, usable or not. The tab shows either way, with the
    // reason when it cannot be used.
    bool Installed();

    // A provider that is loaded and could not be used, when another one was.
    // Empty when there is none. It matters because the one refused may be the
    // one the game is listening to: the other then stands down for it, and a
    // multiplier written to the other changes nothing.
    const char* RefusedOther();

    // Just the module name from that refusal, "StackMaster.asi", for a
    // sentence that has to name the mod to set the multiplier in. Empty when
    // nothing was refused, which is also the case when the mod in charge is
    // one this build has never heard of.
    const char* RefusedModule();

    // Why stacks are not being changed. The provider writes it, because it
    // knows what a number cannot, such as which mod took precedence. Falls
    // back to this mod's own wording, translated, when the provider has no
    // such export or does not know the code. Never null; valid until the next
    // call, and only the menu thread calls it.
    const char* StandDownText(int code);
}
