// The SDK checks SIMD fetch against per-element scalar fetch, byte for byte.
#define main sdk_vertex_main
#include "test_vertex_fetch_plan.c"
#undef main
#include <pthread.h>

static void* threaded_remap(void* arg)
{
    rsx_vertex_remap remap = {0};
    const u32 base = (u32)(uintptr_t)arg;
    for (u32 round = 0; round < 10000; ++round) {
        rsx_vertex_ref refs[128]; u32 unique;
        for (u32 i = 0; i < 128; ++i) refs[i] = (rsx_vertex_ref){(i + round + base) % 37, base};
        if (!rsx_vertex_remap_build(&remap, refs, 128, &unique) || unique != 37) abort();
        for (u32 i = 0; i < 37; ++i)
            if (refs[i].vertex_id != (i + round + base) % 37) abort();
        for (u32 i = 0; i < 128; ++i)
            if (rsx_vertex_remap_index(&remap, i) != i % 37) abort();
    }
    rsx_vertex_remap_destroy(&remap);
    return NULL;
}

int main(void)
{
    if (sdk_vertex_main()) return 1;
    rsx_vertex_remap remap = {0};
    for (unsigned run = 0; run < 2000; ++run) {
        rsx_vertex_ref refs[300], expected[300];
        u32 map[300], count = rnd() % 301, unique = 0, got = 0;
        for (u32 i = 0; i < count; ++i) {
            // Dense range, mixed bases, sparse range, and unsigned wrap limits.
            refs[i].vertex_id = (run % 4 == 2) ? rnd() : rnd() % 70;
            if (run % 4 == 3) refs[i].vertex_id += UINT_MAX - 70;
            refs[i].base_index = (run % 4 == 1) ? rnd() % 3 : 4;
            u32 j = 0;
            for (; j < unique; ++j)
                if (expected[j].vertex_id == refs[i].vertex_id &&
                    expected[j].base_index == refs[i].base_index) break;
            if (j == unique) expected[unique++] = refs[i];
            map[i] = j;
        }
        CHECK(rsx_vertex_remap_build(&remap, refs, count, &got), "remap allocation");
        CHECK(got == unique && !memcmp(refs, expected, unique * sizeof *refs), "unique first-use order");
        for (u32 i = 0; i < count; ++i)
            CHECK(rsx_vertex_remap_index(&remap, i) == map[i], "occurrence map");
    }
    rsx_vertex_remap_destroy(&remap);
    pthread_t threads[4];
    for (uintptr_t i = 0; i < 4; ++i) if (pthread_create(&threads[i], NULL, threaded_remap, (void*)i)) abort();
    for (unsigned i = 0; i < 4; ++i) if (pthread_join(threads[i], NULL)) abort();
    return fails ? 1 : 0;
}
