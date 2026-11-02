#include <cstdlib>

// The standalone probes link Bun's mimalloc object without the executable
// that normally supplies its fatal allocation-failure hook.
extern "C" [[noreturn]] void Bun__outOfMemory()
{
    std::abort();
}
