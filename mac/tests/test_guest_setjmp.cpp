// Exercise the real bridge with nested guest frames and independent host threads.
#include "ppu_context.h"
#include <cassert>
#include <setjmp.h>
#include <thread>

extern "C" {
PPU_THREAD_LOCAL void (*g_trampoline_fn)(void*) = nullptr;
static PPU_THREAD_LOCAL int depth, vcall;
int* ps3_ppu_dispatch_depth_slot() { return &depth; }
int* ps3_ppu_vcall_sp_slot() { return &vcall; }
void* ds_sj_arm(ppu_context*, void*);
void ds_sj_jump(ppu_context*, uint32_t, uint32_t);
}
static void trampoline(void*) {}

__attribute__((noinline)) static void jump(ppu_context* ctx, uint32_t buf)
{
    // Emulate the register restoration done by the lifted longjmp.
    ctx->gpr[3] = 7;
    depth = 99; vcall = 98; g_trampoline_fn = trampoline;
    ds_sj_jump(ctx, buf, 0x00CAE768);
    assert(false && "matched longjmp must leave this frame");
}

__attribute__((noinline)) static void nested(ppu_context* ctx)
{
    ctx->gpr[1] = 0x7F000; ctx->gpr[3] = 0x2000;
    void* env = ds_sj_arm(ctx, __builtin_frame_address(0));
    if (!_setjmp(*(jmp_buf*)env)) jump(ctx, 0x2000);
    assert(ctx->gpr[3] == 7 && depth == 4 && vcall == 5 && !g_trampoline_fn);
    // Jump over this live arm to the outer guest protected call.
    jump(ctx, 0x1000);
}

__attribute__((noinline)) static void protected_call(ppu_context* ctx)
{
    depth = 4; vcall = 5;
    ctx->gpr[1] = 0x80000; ctx->gpr[3] = 0x1000;
    void* env = ds_sj_arm(ctx, __builtin_frame_address(0));
    if (!_setjmp(*(jmp_buf*)env)) nested(ctx);
    assert(ctx->gpr[3] == 7 && depth == 4 && vcall == 5 && !g_trampoline_fn);
}

static void worker()
{
    ppu_context ctx{};
    // Repeated reuse also exercises pruning arms belonging to returned frames.
    for (int i = 0; i < 1000; ++i) protected_call(&ctx);
}

__attribute__((noinline)) static void deep_protected_call(ppu_context* ctx, unsigned level)
{
    ctx->gpr[1] = 0x100000 - level * 0x100;
    ctx->gpr[3] = 0x1000 + level * 16;
    void* env = ds_sj_arm(ctx, __builtin_frame_address(0));
    if (!_setjmp(*(jmp_buf*)env)) {
        if (level < 1023) deep_protected_call(ctx, level + 1);
        else jump(ctx, 0x1000); // The first buffer must survive growth past 256.
    } else {
        assert(level == 0 && ctx->gpr[3] == 7 && !g_trampoline_fn);
    }
}

int main()
{
    std::thread a(worker), b(worker);
    a.join(); b.join();
    worker();
    ppu_context ctx{};
    deep_protected_call(&ctx, 0);
}
