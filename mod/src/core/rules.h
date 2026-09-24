#pragma once
#include <string>

#include "itemdb.h"
#include "settings.h"

namespace ml::Rules
{
    struct Verdict
    {
        bool        loot   = true;
        const char* rule   = "default"; // which rule decided
        std::string detail;             // the class, tag or key it matched
    };

    // Order: item override, tag never, protected tags (memory-fragment, gimmick),
    // tag always, quest/no-sell/dev filters, value floor, class rule, then loot.
    Verdict Decide(const Item& item, const Config& cfg);

    // The class rule alone, for something that has a class and no item: a
    // creature the game gives no item of its own is judged by the class the
    // creature table gives it.
    Verdict DecideClass(const std::string& klass, const Config& cfg);
}
