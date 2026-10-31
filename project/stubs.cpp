/*
 * ps3recomp game project -- game-specific hooks and overrides.
 *
 * main.cpp is the runner and is game-agnostic. This file is where a port puts
 * everything that is not: the PRX loading hook it must answer, overrides for
 * firmware functions the HLE library gets wrong for this title, and patches
 * over recompiled code.
 *
 * It starts out as the empty version of all of that, which is what a game with
 * no lifted PRX and no overrides needs.
 */

#include <cstdio>
#include <cstring>

#include "ps3emu/ps3types.h"
#include "ps3emu/error_codes.h"

/* ---------------------------------------------------------------------------
 * PRX loading
 *
 * main.cpp calls this once, after the lifted function table is registered and
 * vm_base is live, before the game runs. A title that lifts a real system PRX
 * -- libsre, which is cellSpurs and cellSync -- loads its image into guest RAM
 * here and registers its exports. Most ports never need to: the HLE library
 * answers those modules instead.
 * -----------------------------------------------------------------------*/

extern "C" void ps3_load_prx_modules(void)
{
}

/* ---------------------------------------------------------------------------
 * Debug: TOC sanity check after every lifted call site
 *
 * Demon's Souls links with several TOCs (0x19B5040 for most code, 0x19D3BAC
 * for the SDK/runtime half, 0x19C448C for a few dozen functions) and switches
 * between them through linker stubs. A call that returns with r2 holding
 * anything else means a stub or a TOC restore went wrong. The lifted chunks'
 * DRAIN_TRAMPOLINE calls this (patched in by patch_drain.py).
 * -----------------------------------------------------------------------*/
#include "ppu_recomp.h"

extern "C" void ds_toc_check(void* p)
{
    ppu_context* ctx = (ppu_context*)p;
    uint32_t r2 = (uint32_t)ctx->gpr[2];
    if (r2 == 0x019B5040u || r2 == 0x019D3BACu || r2 == 0x019C448Cu) return;
    static int reported = 0;
    if (reported >= 6) return;
    reported++;
    fprintf(stderr, "[TOC] bad r2=0x%08X after call returning to lr=0x%08X "
            "(sp=0x%08X r3=0x%08X [sp+0x28]=0x%08X%08X)\n",
            r2, (uint32_t)ctx->lr, (uint32_t)ctx->gpr[1], (uint32_t)ctx->gpr[3],
            (uint32_t)(vm_read64(ctx->gpr[1] + 0x28) >> 32),
            (uint32_t)vm_read64(ctx->gpr[1] + 0x28));
}

/* ---------------------------------------------------------------------------
 * Example: Override a specific NID
 *
 * The module system resolves function imports by NID.  To replace a default
 * HLE stub with custom logic, register your function at init time.
 * -----------------------------------------------------------------------*/

/*
 * Example: override cellGcmSetFlipMode (NID 0xA53D12AE) to force vsync.
 *
 *   static void my_cellGcmSetFlipMode(u32 mode)
 *   {
 *       printf("[hook] cellGcmSetFlipMode: forcing VSYNC (was %u)\n", mode);
 *       // Force vsync regardless of what the game requested
 *       cellGcmSetFlipMode(CELL_GCM_DISPLAY_VSYNC);
 *   }
 *
 * Then in your init code:
 *
 *   ps3::modules::override_nid(0xA53D12AE,
 *       reinterpret_cast<void*>(my_cellGcmSetFlipMode));
 */

/* ---------------------------------------------------------------------------
 * Example: Hook into module loading
 *
 * You can intercept cellSysmoduleLoadModule to perform custom actions
 * when a particular module is loaded.
 * -----------------------------------------------------------------------*/

/*
 *   static s32 my_loadmodule_hook(u16 id)
 *   {
 *       printf("[hook] Module 0x%04X loaded\n", id);
 *
 *       if (id == CELL_SYSMODULE_AUDIO) {
 *           // Perform custom audio backend initialization
 *           init_my_audio_backend();
 *       }
 *
 *       // Call the original implementation
 *       return cellSysmoduleLoadModule(id);
 *   }
 */

/* ---------------------------------------------------------------------------
 * Game-specific patches
 *
 * Sometimes you need to patch recompiled code at specific addresses.
 * Use the patch system to modify behavior without editing generated code.
 * -----------------------------------------------------------------------*/

/*
 *   // Skip an integrity check at guest address 0x00812FA0
 *   ps3::patches::nop_range(0x00812FA0, 0x00812FB0);
 *
 *   // Replace a function call with a direct return
 *   ps3::patches::force_return(0x009A1000, 0);  // return 0
 */
