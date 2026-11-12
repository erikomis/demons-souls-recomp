// Exercise real lv2 group creation/start/join with the SDK's manufactured SPU programs.
#include "test_spu_lifted_start.c"

// Optional stack profiling is outside this fixture's execution contract.
void ps3_perf_watch_thread(const char* name) { (void)name; }

// This fixture exercises outbound events and thread exit, not inbound queues.
// Fail if an unexpected receive path is introduced instead of faking a reply.
int32_t sys_event_queue_pop_spu(uint32_t queue, sys_event_t* event, int wait,
                               int (*keep_waiting)(void*), void* arg)
{
    (void)queue; (void)event; (void)wait; (void)keep_waiting; (void)arg;
    abort();
}
