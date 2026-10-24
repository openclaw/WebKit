#include <cstdio>
#include <cstdlib>

// The standalone embedding supplies the final executable's fatal OOM hook.
extern "C" [[noreturn]] void Bun__outOfMemory()
{
    std::fputs("unexpected allocator out of memory in standalone engine probe\n", stderr);
    std::abort();
}
