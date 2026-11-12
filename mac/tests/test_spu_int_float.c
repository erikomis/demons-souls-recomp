/* Exact differential coverage for the integer-to-SPU-float NEON helpers. */
#include "spu_helpers.h"
#include <assert.h>
#include <fenv.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static unsigned long long checked;
static uint32_t random_state = 0x82a91635u;

static uint32_t random_word(void) {
    random_state ^= random_state << 13;
    random_state ^= random_state >> 17;
    random_state ^= random_state << 5;
    return random_state;
}

static void compare(u128 a, int scale) {
    const u128 got[] = {spu_csflt(a, scale), spu_cuflt(a, scale)};
    const u128 expected[] = {spu_csflt_ref(a, scale), spu_cuflt_ref(a, scale)};
    for (int op = 0; op < 2; ++op) {
        for (int lane = 0; lane < 4; ++lane) {
            if (got[op]._u32[lane] != expected[op]._u32[lane]) {
                fprintf(stderr, "%s input=%08x scale=%d lane=%d got=%08x expected=%08x\n",
                        op ? "cuflt" : "csflt", a._u32[lane], scale, lane,
                        got[op]._u32[lane], expected[op]._u32[lane]);
                abort();
            }
            ++checked;
        }
    }
}

static void boundaries(void) {
    for (int scale = 0; scale < 256; ++scale) {
        for (int bit = 0; bit < 32; ++bit) {
            const uint32_t power = 1u << bit;
            for (int delta = -2; delta <= 2; ++delta) {
                const uint32_t v = power + (uint32_t)delta;
                const u128 a = {._u32 = {v, 0u - v, v ^ 0x80000000u, ~v}};
                compare(a, scale);
                compare(a, scale - 256);
                compare(a, scale + 512);
            }
        }
        compare((u128){._u32 = {0, 0x80000000u, 0x7fffffffu, 0xffffffffu}}, scale);
    }
}

typedef u128 (*converter)(u128, int);
static __attribute__((noinline)) u128 fast_signed(u128 a, int i) { return spu_csflt(a, i); }
static __attribute__((noinline)) u128 ref_signed(u128 a, int i) { return spu_csflt_ref(a, i); }
static __attribute__((noinline)) u128 fast_unsigned(u128 a, int i) { return spu_cuflt(a, i); }
static __attribute__((noinline)) u128 ref_unsigned(u128 a, int i) { return spu_cuflt_ref(a, i); }

static double measure(converter fn, const u128 *data, uint32_t *checksum) {
    struct timespec start, end;
    uint32_t sum = 0;
    clock_gettime(CLOCK_MONOTONIC, &start);
    for (unsigned i = 0; i < 2000000; ++i) {
        const u128 r = fn(data[i & 4095], 28 + (int)(i & 127));
        sum += r._u32[0] ^ r._u32[1] ^ r._u32[2] ^ r._u32[3];
    }
    clock_gettime(CLOCK_MONOTONIC, &end);
    *checksum = sum;
    return (end.tv_sec - start.tv_sec) * 1000.0 + (end.tv_nsec - start.tv_nsec) / 1e6;
}

static void benchmark(void) {
    u128 data[4096];
    for (int i = 0; i < 4096; ++i)
        for (int lane = 0; lane < 4; ++lane) data[i]._u32[lane] = random_word();
    const converter fast[] = {fast_signed, fast_unsigned};
    const converter ref[] = {ref_signed, ref_unsigned};
    for (int op = 0; op < 2; ++op) {
        double fast_best = 1e30, ref_best = 1e30;
        for (int round = 0; round < 6; ++round) {
            uint32_t a, b;
            double ft, rt;
            /* Alternate order to reduce warm-up and thermal bias. */
            if (round & 1) { ft = measure(fast[op], data, &a); rt = measure(ref[op], data, &b); }
            else { rt = measure(ref[op], data, &b); ft = measure(fast[op], data, &a); }
            assert(a == b);
            if (ft < fast_best) fast_best = ft;
            if (rt < ref_best) ref_best = rt;
        }
        printf("%s: 2M vectors, scalar %.3f ms, active %.3f ms, %.2fx\n",
               op ? "cuflt" : "csflt", ref_best, fast_best, ref_best / fast_best);
    }
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--benchmark") == 0) { benchmark(); return 0; }

    /* Known SPU truncation, underflow and extended-exponent results. */
    u128 a = {._u32 = {0, 1, 0x80000000u, 0xffffffffu}};
    u128 r = spu_csflt(a, 155);
    assert(r._u32[0] == 0 && r._u32[1] == 0x3f800000u);
    assert(r._u32[2] == 0xcf000000u && r._u32[3] == 0xbf800000u);
    r = spu_cuflt(a, 155);
    assert(r._u32[2] == 0x4f000000u && r._u32[3] == 0x4f7fffffu);
    a = (u128){._u32 = {1, 1u << 28, 1u << 29, 0xffffffffu}};
    r = spu_cuflt(a, 0);
    assert(r._u32[0] == 0 && r._u32[1] == 0 && r._u32[2] == 0x00800000u);
    r = spu_cuflt(a, 255);
    assert(r._u32[1] == 0x7f800000u && r._u32[2] == 0x7fffffffu && r._u32[3] == 0x7fffffffu);

    const int rounding[] = {FE_TONEAREST, FE_DOWNWARD, FE_UPWARD, FE_TOWARDZERO};
    const int saved_rounding = fegetround();
    for (unsigned mode = 0; mode < sizeof(rounding) / sizeof(rounding[0]); ++mode) {
        assert(fesetround(rounding[mode]) == 0);
        boundaries();
    }
    assert(fesetround(saved_rounding) == 0);
    /* Every 16-bit pattern in low/high halves, all 256 encoded scales. */
    for (unsigned scale = 0; scale < 256; ++scale) {
        for (uint32_t v = 0; v < 65536; ++v) {
            a = (u128){._u32 = {v, v << 16, v * 0x10001u, ~(v * 0x10001u)}};
            compare(a, (int)scale);
        }
    }
    for (unsigned i = 0; i < 1000000; ++i) {
        for (int lane = 0; lane < 4; ++lane) a._u32[lane] = random_word();
        compare(a, (int)(i & 255));
    }
    printf("SPU integer/float: %llu lane results match the exact scalar reference\n", checked);
    return 0;
}
