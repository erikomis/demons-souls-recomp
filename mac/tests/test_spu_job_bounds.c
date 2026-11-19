/* Exercise staging only; the synthetic entry checks the context it receives. */
#include "spu_workload.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint8_t guest[1 << 20];
uint8_t* vm_base = guest;
uint32_t ppu_vm_size = sizeof guest;
static unsigned ran;
static unsigned io_size = 16;
static unsigned cache_count;
enum { JOB = 0x1000, BINARY = 0x2000, INPUT = 0x3000 };
void spu_mfc_release(spu_context* ctx) { (void)ctx; }
void spu_coh_unregister(spu_context* ctx) { (void)ctx; }
int spu_run_with_halt(void (*fn)(spu_context*), spu_context*);
int spu_run_with_halt(void (*fn)(spu_context*), spu_context* ctx) { fn(ctx); return 0; }
static void be16(unsigned o, uint16_t v) { guest[o] = v >> 8; guest[o + 1] = v; }
static void be32(unsigned o, uint32_t v) {
    guest[o] = v >> 24; guest[o + 1] = v >> 16; guest[o + 2] = v >> 8; guest[o + 3] = v;
}
static void build(void) {
    memset(guest, 0, sizeof guest); ran = 0; io_size = 16; cache_count = 0;
    be32(JOB + 4, BINARY); be16(JOB + 8, 64); // 1024-byte binary
    be16(JOB + 10, 8); be32(JOB + 0x14, 16);
    be32(JOB + 0x30, 16); be32(JOB + 0x34, INPUT);
    memset(guest + BINARY, 0x12, 1024); memset(guest + INPUT, 0x67, 16);
}
static void entry(spu_context* ctx) {
    ++ran;
    assert(ctx->ls[0] == 0x12 && ctx->ls[1023] == 0x12);
    unsigned io = spu_ls_read32(ctx, ctx->gpr[3]._u32[0]);
    for (unsigned i = 0; i < io_size; ++i) assert(ctx->ls[io + i] == 0x67);
    assert(ctx->gpr[1]._u32[0] + 32 <= ctx->gpr[3]._u32[0]);
    for (unsigned i = 0; i < cache_count; ++i) {
        unsigned cache = spu_ls_read32(ctx, ctx->gpr[3]._u32[0] + 4 + i * 4);
        assert(ctx->gpr[1]._u32[0] + 32 <= cache);
        for (unsigned byte = 0; byte < 16; ++byte) assert(ctx->ls[cache + byte] == 0xab);
    }
}
static void reject(unsigned ea, unsigned size) {
    assert(spu_run_spurs_job(entry, 1, ea, size) < 0); assert(ran == 0);
}
int main(void) {
    const unsigned sizes[] = {0, 64, 128, 256, 512, 1024};
    for (unsigned i = 0; i < sizeof sizes / sizeof sizes[0]; ++i) {
        build(); assert(spu_run_spurs_job(entry, 1, JOB, sizes[i]) == 0 && ran == 1);
    }
    for (unsigned count = 1; count <= 4; ++count) {
        build(); cache_count = count;
        be16(JOB + 0x1c, 0x80); be16(JOB + 0x1e, 0x40);
        be32(JOB + 0x24, count * 8);
        for (unsigned i = 0; i < count; ++i) {
            be32(JOB + 0x38 + i * 8, 16);
            be32(JOB + 0x3c + i * 8, 0x4000 + i * 16);
            memset(guest + 0x4000 + i * 16, 0xab, 16);
        }
        assert(spu_run_spurs_job(entry, 1, JOB, 256) == 0 && ran == 1);
    }
    build(); be32(JOB + 0x14, 0xffffffff); reject(JOB, 256);
    build(); be32(JOB + 0x18, 0xffffffff); reject(JOB, 256);
    build(); be16(JOB + 0x1c, 1); reject(JOB, 256); // caller frame cannot fit
    build(); be16(JOB + 0x1e, 0xffff); reject(JOB, 256);
    build(); be16(JOB + 10, 7); reject(JOB, 256);
    build(); be16(JOB + 10, 256); reject(JOB, 256);
    build(); be32(JOB + 0x14, 15); reject(JOB, 256); // DMA crosses declared input
    build(); be32(JOB + 0x34, sizeof guest - 8); reject(JOB, 256);
    build(); be32(JOB + 4, sizeof guest - 512); reject(JOB, 256);
    build(); be32(JOB, 1); reject(JOB, 256); // unsupported 64-bit EA
    build(); be32(JOB + 0x24, 40); reject(JOB, 256); // five cache buffers
    build(); be32(JOB + 0x24, 8); be32(JOB + 0x38, 0xfffffff0);
    be32(JOB + 0x3c, INPUT); reject(JOB, 256);
    build(); be32(JOB + 0x24, 8); be32(JOB + 0x38, 16);
    be32(JOB + 0x3c, sizeof guest - 8); reject(JOB, 256);
    build(); reject(JOB, 63); reject(JOB, 129); reject(JOB, 2048);
    build(); reject(sizeof guest - 128, 256); reject(0xfffffff0, 256);
    puts("SPURS job: valid descriptors staged; overflowing regions and DMA lists rejected");
}
