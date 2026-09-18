#pragma once
#include "psm_api.h"

// Private Storage Master, when it is installed beside this mod.
//
// Nothing here links against it. The plugin is looked up by module name and
// each function by name, and all of it is used only when the interface version
// matches the header this build was compiled with. Without it the Storage tab
// is simply not drawn.
namespace ml::psm
{
    struct Api
    {
        int         (*apiVersion)(void);
        const char* (*storageName)(int);
        const char* (*storageKey)(int);
        int         (*getStatus)(PsmStatus*);
        int         (*getSettings)(PsmSettings*);
        int         (*getDefaults)(PsmSettings*);
        int         (*applySettings)(const PsmSettings*, char*, int);
        int         (*reloadSettings)(void);
        int         (*getSize)(int, PsmSize*);
        void        (*writeDump)(void);
        void        (*pauseInput)(uint32_t);
        int         (*keyText)(PsmKey, char*, int);
        int         (*padText)(PsmPad, char*, int);
        int         (*fixedSlots)(int);   // optional, null on a plugin built before it
        int         (*getKeyBlock)(PsmKeyBlock*, int);                // optional, 1.0.1 and later
        int         (*applyKeyBlock)(const PsmKeyBlock*, char*, int); // optional, 1.0.1 and later
    };

    // Null until the plugin is found with a matching interface. Cheap to call
    // every frame: a miss is retried every two seconds.
    const Api* Get();

    // What the lookup found, for the Status line: "not installed", "interface 2,
    // this build speaks 1", and so on. Empty when Get() succeeds.
    const char* Why();

    // Found in the process, usable or not. The Storage tab shows either way,
    // with the reason when it cannot be used.
    bool Installed();
}
