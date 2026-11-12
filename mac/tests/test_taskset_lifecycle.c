// Real task dispatch/shutdown/join with delayed or rejected host thread creation.
#include <pthread.h>
#include <stdatomic.h>
#include <assert.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "win32_compat.h"

static atomic_int release_worker, worker_waiting, worker_done, reject_threads;
static atomic_int fast_join_wait, join_polls;
static void lifecycle_sleep(DWORD ms)
{
    // Exercise more than the former 3,000-poll deadline without wall-clock sleeps.
    if (ms == 1 && atomic_load(&fast_join_wait)) {
        atomic_fetch_add(&join_polls, 1);
        Sleep(0);
    } else Sleep(ms);
}
typedef struct { void* (*entry)(void*); void* arg; } delayed_launch;
static void* delayed_worker(void* arg)
{
    delayed_launch launch = *(delayed_launch*)arg;
    free(arg);
    atomic_store(&worker_waiting, 1);
    while (!atomic_load(&release_worker)) usleep(100);
    void* result = launch.entry(launch.arg);
    atomic_store(&worker_done, 1);
    return result;
}
static int delayed_create(pthread_t* thread, const pthread_attr_t* attr,
                          void* (*entry)(void*), void* arg)
{
    if (atomic_load(&reject_threads)) return EAGAIN;
    delayed_launch* launch = malloc(sizeof *launch);
    assert(launch);
    *launch = (delayed_launch){entry, arg};
    int rc = pthread_create(thread, attr, delayed_worker, launch);
    if (rc) free(launch);
    return rc;
}

// Include the actual implementation to inspect its pending/running bookkeeping.
// The interception delays scheduling, rather than substituting task completion.
#define pthread_create delayed_create
#define Sleep lifecycle_sleep
#include "spu_workload.c"
#undef Sleep
#undef pthread_create
// Reuse the SDK's link stubs. The invalid manufactured ELF below never enters
// the lifted runner; any unexpected execution through a stub aborts the test.
#define main sdk_dispatch_miss_main
#include "test_spu_dispatch_miss.c"
#undef main

extern int spu_taskset_is_down(uint32_t);
extern void spu_taskset_shutdown(uint32_t);
extern void spu_taskset_revive(uint32_t);

static void wait_flag(atomic_int* flag)
{
    for (int i = 0; i < 30000; ++i) {
        if (atomic_load(flag)) return;
        usleep(100);
    }
    assert(!"host thread failed to make progress");
}

enum { TASKSETS = 513 };
static uint32_t address(unsigned i) { return 0x1000u + i * 0x2000u; }
static void* shutdown_many(void* unused)
{
    (void)unused;
    for (unsigned i = 0; i < TASKSETS; ++i) {
        spu_taskset_shutdown(address(i));
        assert(spu_taskset_is_down(address(i)));
    }
    return NULL;
}
static void test_shutdown(void)
{
    // More unique tasksets than the old table could retain, even after join.
    for (unsigned i = 0; i < TASKSETS; ++i) {
        spu_taskset_shutdown(address(i));
        assert(spu_taskset_join(address(i)) == 0);
        assert(spu_taskset_is_down(address(i)));
    }
    pthread_t threads[4];
    for (unsigned i = 0; i < 4; ++i) assert(!pthread_create(&threads[i], NULL, shutdown_many, NULL));
    for (unsigned i = 0; i < 4; ++i) assert(!pthread_join(threads[i], NULL));
    assert(__atomic_load_n(&g_spu_tasksets_down, __ATOMIC_ACQUIRE) == TASKSETS);
    // Prime the memo, remove from a different registry position, and reuse EA.
    assert(spu_taskset_is_down(address(7)));
    spu_taskset_revive(address(7));
    assert(!spu_taskset_is_down(address(7)));
    spu_taskset_shutdown(address(7));
    assert(spu_taskset_is_down(address(7)));
    for (unsigned i = 0; i < TASKSETS; ++i) spu_taskset_revive(address(i));
    assert(__atomic_load_n(&g_spu_tasksets_down, __ATOMIC_ACQUIRE) == 0);
    // Running-slot and accepted-job tables must also retain every live taskset.
    for (unsigned i = 0; i < TASKSETS; ++i) {
        spu_taskset_mark_running(address(i), i % 128);
        ts_live_add(address(i), 1);
    }
    ts_lock();
    for (unsigned i = 0; i < TASKSETS; ++i) {
        uint8_t* running = ts_running(address(i));
        assert(running && (running[(i % 128) / 8] & (0x80u >> (i % 8))));
        assert(ts_live_count(address(i)) == 1);
    }
    ts_unlock();
    for (unsigned i = 0; i < TASKSETS; ++i) {
        ts_live_add(address(i), -1);
        assert(spu_taskset_join(address(i)) == 0);
    }
}

static atomic_int join_entered, join_done;
static void* join_worker(void* unused)
{
    (void)unused;
    atomic_store(&join_entered, 1);
    assert(spu_taskset_join(address(0)) == 0);
    atomic_store(&join_done, 1);
    return NULL;
}
static void never_run(spu_context* ctx) { (void)ctx; abort(); }
static uint8_t image[64]; // Deliberately invalid ELF: worker releases without guest execution.
static void setup_dispatch(void)
{
    vm_base = calloc(1, ppu_vm_size);
    assert(vm_base);
    unsetenv("LBP_PERSIST_LS");
    unsetenv("LBP_SPU_SERIAL");
    unsetenv("LBP_WS_DRAIN");
    spu_workload_register_img(spu_workload_fingerprint(image, sizeof image), never_run, 100, "lifecycle fixture");
    spu_workload_set_dispatch_task(address(0), 3);
}
static void test_queued_join(int past_deadline)
{
    setup_dispatch();
    assert(spu_workload_dispatch_async(image, sizeof image, 0));
    wait_flag(&worker_waiting);
    assert(ts_live_count(address(0)) == 1); // Accepted but not yet scheduled.
    spu_taskset_shutdown(address(0));
    atomic_store(&fast_join_wait, past_deadline);
    pthread_t joiner;
    assert(!pthread_create(&joiner, NULL, join_worker, NULL));
    wait_flag(&join_entered);
    if (past_deadline) {
        for (int i = 0; i < 30000 && atomic_load(&join_polls) < 3500 && !atomic_load(&join_done); ++i)
            usleep(100);
        assert(atomic_load(&join_polls) >= 3500);
    } else usleep(50000);
    assert(!atomic_load(&join_done));
    atomic_store(&release_worker, 1);
    wait_flag(&join_done); wait_flag(&worker_done);
    assert(!pthread_join(joiner, NULL));
    assert(ts_live_count(address(0)) == 0);
    free(vm_base);
}
static void test_exit_codes(void)
{
    ppu_vm_size = 1u << 20;
    vm_base = calloc(1, ppu_vm_size);
    assert(vm_base);
    for (unsigned i = 0; i < 32; ++i) {
        const uint32_t ea = 0x1000u + i * 0x3000u;
        vm_write32(ea + CSTS_SIZE_FIELD, 0x2900);
        const uint32_t task = i == 31 ? 127 : i;
        uint8_t* entry = vm_base + ea + 0x1980 + 16 * task;
        memset(entry, 0xA5, 16);
        // Creation sets the size; no separate host registration should be needed.
        spu_taskset2_set_exit(ea, task, 1, 0xDEADBEEFu);
        assert(entry[8] == 0xDE && entry[9] == 0xAD && entry[10] == 0xBE && entry[11] == 0xEF);
        assert(entry[14] == 0 && entry[15] == 2);
        spu_taskset2_set_exit(ea, task, 0, 0);
        for (unsigned j = 0; j < 16; ++j) assert(entry[j] == 0);
        // The same EA reused for a smaller v1 object must not receive v2 writes.
        spu_taskset2_register(ea);
        vm_write32(ea + CSTS_SIZE_FIELD, 0x1900);
        memset(entry, 0xA5, 16);
        spu_taskset2_set_exit(ea, task, 1, 0);
        for (unsigned j = 0; j < 16; ++j) assert(entry[j] == 0xA5);
    }
    const uint32_t truncated = ppu_vm_size - 0x2000u;
    vm_write32(truncated + CSTS_SIZE_FIELD, 0x2900);
    memset(vm_base + truncated + 0x1980, 0xA5, 16);
    spu_taskset2_set_exit(truncated, 0, 1, 0);
    for (unsigned j = 0; j < 16; ++j) assert(vm_base[truncated + 0x1980 + j] == 0xA5);
    spu_taskset2_set_exit(0x1000, 128, 1, 0);
    spu_taskset2_set_exit(UINT32_MAX - 15, 0, 1, 0);
    free(vm_base);
}
static void test_rejected_launch(void)
{
    setup_dispatch();
    atomic_store(&reject_threads, 1);
    assert(!spu_workload_dispatch_async(image, sizeof image, 0));
    assert(ts_live_count(address(0)) == 0);
    ts_lock();
    uint8_t* run = ts_running(address(0));
    assert(run && !(run[0] & 0x10));
    // A launch initiated while scanning pending tasks already holds this lock.
    run[0] |= 0x10;
    s_ts_held = 1;
    spu_workload_set_dispatch_task(address(0), 3);
    assert(!spu_workload_dispatch_async(image, sizeof image, 0));
    assert(!(run[0] & 0x10));
    s_ts_held = 0;
    ts_unlock();
    assert(ts_live_count(address(0)) == 0);
    assert(spu_taskset_join(address(0)) == 0);
    free(vm_base);
}
static unsigned stop_visits, stop_continued, stop_caller_continued;
static int receive_expected, receive_result, receive_calls, receive_try;
int lv2_spu_receive_event(spu_context* ctx, int try_only)
{
    assert(receive_expected && ctx->spu_group_id == 1 && try_only == receive_try);
    ++receive_calls;
    return receive_result;
}
extern void spu_halt(spu_context*);
extern void spu_stop(spu_context*);
extern void spu_begin_image(int);
extern void spu_register_function(uint32_t, void (*)(spu_context*));
extern int spu_run_with_halt(void (*)(spu_context*), spu_context*);
static void lifted_stop(spu_context* ctx)
{
    // Bound the old redispatch bug so the negative control fails without hanging.
    if (++stop_visits > 1) { spu_halt(ctx); return; }
    ctx->pc = 0x400;
    ctx->stop_code = ctx->gpr[12]._u32[0];
    spu_stop(ctx);
    ++stop_continued;
}
static void nested_stop_entry(spu_context* ctx)
{
    ctx->host_depth++;
    ctx->pc = 0x400;
    g_spu_trampoline_fn = lifted_stop;
    spu_drain_call(ctx, 0x208);
    ctx->host_depth--;
    ++stop_caller_continued;
}
static void test_stop(const char* mode)
{
    unsetenv("YDKJ_STOP_HALT");
    spu_context* ctx = calloc(1, sizeof *ctx);
    assert(ctx);
    spu_context_init(ctx, 0);
    ctx->status = SPU_STATUS_RUNNING;
    ctx->image_id = 77;
    spu_begin_image(77);
    spu_register_function(0x400, lifted_stop);
    const int nested = !strcmp(mode, "stop_nested");
    const int policy = !strcmp(mode, "stop_policy");
    const int resident = !strcmp(mode, "stop_resident");
    const int receive = !strncmp(mode, "stop_receive", 12);
    receive_try = !strcmp(mode, "stop_receive_try");
    receive_expected = receive;
    receive_result = receive && strcmp(mode, "stop_receive_empty");
    ctx->spu_group_id = receive ? 1 : 0;
    ctx->policy_mode = policy;
    ctx->resident_task = resident ? 77 : 0;
    ctx->gpr[12]._u32[0] = !strcmp(mode, "stop_code") ? 0x102u : 0;
    if (receive) ctx->gpr[12]._u32[0] = receive_try ? 0x111 : 0x110;
    const int halted = spu_run_with_halt(nested ? nested_stop_entry : lifted_stop, ctx);
    assert(stop_visits == 1);
    assert(halted == !(policy || resident || receive_result));
    assert(stop_continued == (unsigned)(policy || resident || receive_result));
    assert(!stop_caller_continued);
    assert(ctx->status == (receive_result ? SPU_STATUS_RUNNING : SPU_STATUS_STOPPED_BY_STOP));
    assert(receive_calls == receive);
    assert(ctx->stop_code == ctx->gpr[12]._u32[0]);
    assert(!g_spu_trampoline_fn);
    free(ctx);
}
int main(int argc, char** argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "shutdown")) test_shutdown();
    else if (!strcmp(argv[1], "queued")) test_queued_join(0);
    else if (!strcmp(argv[1], "join_wait")) test_queued_join(1);
    else if (!strcmp(argv[1], "exit_codes")) test_exit_codes();
    else if (!strcmp(argv[1], "rejected")) test_rejected_launch();
    else if (!strncmp(argv[1], "stop_", 5)) test_stop(argv[1]);
    else abort();
    return 0;
}
