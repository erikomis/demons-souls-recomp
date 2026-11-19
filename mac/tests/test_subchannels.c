// Run the SDK's engine suite, then reproduce 2D writes corrupting 3D alpha/blend.
#define main sdk_engine_main
#include "test_rsx_draw_engine.c"
#undef main

int main(void)
{
    if (sdk_engine_main()) return 1;
    vm_base = calloc(1, GUEST_BYTES);
    if (!vm_base) return 2;
    ppu_vm_size = GUEST_BYTES;
    engine_up();
    m(0x0304, 1);      // alpha test enabled
    m(0x0308, 0x204);  // GREATER
    m(0x030C, 0x80);
    m(0x0310, 1);      // blend enabled
    draw_triangle();
    const u32 pipeline = stub.bound_pipeline;
    const int builds = stub.n_pipeline_create;
    CHECK(pipeline != 0, "3D pipeline built before transfers");
    const u32 subchannels[] = {0x2000, 0x6000, 0x8000, 0xA000, 0xC000};
    for (unsigned i = 0; i < sizeof subchannels / sizeof *subchannels; ++i) {
        m(subchannels[i] + 0x0300, 0xB);
        m(subchannels[i] + 0x0304, 4);
        m(subchannels[i] + 0x0308, 0x10004);
        m(subchannels[i] + 0x030C, 0x10004);
        m(subchannels[i] + 0x0310, 0);
        draw_triangle();
        CHECK(stub.bound_pipeline == pipeline && stub.n_pipeline_create == builds,
              "transfer on subchannel 0x%X preserves 3D pipeline state", subchannels[i]);
    }
    rsx_draw_engine_shutdown();
    free(vm_base);
    return g_failures ? 1 : 0;
}
