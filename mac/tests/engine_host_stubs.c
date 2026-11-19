/* The host pieces rsx_draw_engine.c reaches for its keyboard / mouse button icons (stb_image for the
 * icon files, cellPad for which input was used last). The engine tests have neither a pad nor icon
 * files, so: no keyboard or mouse in use, and no image ever loads. */
#include <stddef.h>

int ps3_host_kbm_active(void) { return 0; }
unsigned char* stbi_load(const char* path, int* x, int* y, int* comp, int req)
{
    (void)path; (void)x; (void)y; (void)comp; (void)req;
    return NULL;
}
int stbi_info(const char* path, int* x, int* y, int* comp)
{
    (void)path; (void)x; (void)y; (void)comp;
    return 0;
}
void stbi_image_free(void* p) { (void)p; }
