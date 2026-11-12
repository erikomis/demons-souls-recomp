#include "spu_workload.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint8_t image[512], ls[SPU_LS_SIZE];
static void be16(unsigned o, uint16_t v) { image[o] = v >> 8; image[o + 1] = v; }
static void be32(unsigned o, uint32_t v) {
    image[o] = v >> 24; image[o + 1] = v >> 16; image[o + 2] = v >> 8; image[o + 3] = v;
}
static void build(void) {
    memset(image, 0, sizeof image);
    memcpy(image, "\177ELF\1\2", 6);
    be32(0x18, 0x100); be32(0x1c, 0x34); be16(0x2a, 32); be16(0x2c, 2);
    be32(0x34, 1); be32(0x38, 256); be32(0x3c, 0x100);
    be32(0x44, 16); be32(0x48, 32);
    be32(0x54, 1); be32(0x58, 272); be32(0x5c, SPU_LS_SIZE - 16);
    be32(0x64, 8); be32(0x68, 16);
    for (unsigned i = 256; i < 280; ++i) image[i] = (uint8_t)(i + 1);
}
static void rejected(size_t size) {
    memset(ls, 0xa5, sizeof ls);
    uint32_t entry = 0xdeadbeef;
    assert(!spu_elf_load_to_ls(image, size, ls, &entry));
    assert(entry == 0xdeadbeef);
    for (unsigned i = 0; i < sizeof ls; ++i) assert(ls[i] == 0xa5);
}
int main(void) {
    const uint8_t stop[] = {0, 0, 0x20, 0};
    assert(spu_workload_fingerprint(stop, sizeof stop) == 0x30E786A08645CC13ull);
    build(); memset(ls, 0xa5, sizeof ls);
    uint32_t entry = 0;
    assert(spu_elf_load_to_ls(image, 280, ls, &entry) && entry == 0x100);
    assert(!memcmp(ls + 0x100, image + 256, 16));
    for (unsigned i = 0x110; i < 0x120; ++i) assert(ls[i] == 0);
    assert(ls[0xff] == 0xa5 && ls[0x120] == 0xa5);
    assert(!memcmp(ls + SPU_LS_SIZE - 16, image + 272, 8));
    assert(ls[SPU_LS_SIZE - 1] == 0);
    assert(spu_elf_image_size(image, 280) == 280);
    /* All prefix truncations fail, including an absent second header. */
    for (size_t i = 0; i < 280; ++i) {
        rejected(i); assert(spu_elf_image_size(image, i) == 0);
    }
    build(); be32(0x64, 17); rejected(sizeof image); // filesz > memsz at LS boundary
    build(); be32(0x68, 17); rejected(sizeof image); // memory crosses LS boundary
    build(); be32(0x58, 0xfffffff8); rejected(sizeof image);
    build(); be32(0x1c, 0xfffffff0); rejected(sizeof image);
    build(); be16(0x2a, 16); rejected(sizeof image);
    build(); be16(0x2c, 0); rejected(sizeof image);
    build(); be32(0x18, SPU_LS_SIZE); rejected(sizeof image);
    build(); be32(0x18, 0x101); rejected(sizeof image);
    build(); be32(0x20, 320); be16(0x2e, 40); be16(0x30, 1);
    be32(324, 1); be32(336, 400); be32(340, 16);
    assert(spu_elf_image_size(image, sizeof image) == 416);
    assert(spu_elf_image_size(image, 415) == 0);
    be32(324, 8); be32(336, 0xfffffff0); // NOBITS does not occupy file bytes
    assert(spu_elf_image_size(image, sizeof image) == 360);
    be16(0x2e, 16); assert(spu_elf_image_size(image, sizeof image) == 0);
    puts("SPU ELF: truncated and invalid images rejected without partial LS writes");
}
