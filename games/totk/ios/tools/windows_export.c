/* Execute the production v143 patcher on a verified image, without a Mac runtime.
   The caller checks the complete image hash, clears TOTK_* and passes its layout.
   The unused host callbacks abort if an unexpected path tries to use them. */
#include "runtime.h"
#include "game_patches.h"
#include <malloc.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

uint8_t *runtime_bench_cam;
void runtime_survey_init(Module *m) { (void)m; }
void runtime_oe_push_message(uint32_t m) { (void)m; abort(); }
void dm_gfx_set_flag(const char *s, int v) { (void)s; (void)v; abort(); }
int mfxup_output_enabled(void) { abort(); }
void *runtime_symbol(const char *s) { fprintf(stderr, "unexpected runtime symbol: %s\n", s); abort(); }
_Noreturn void runtime_fail(const char *s) { fprintf(stderr, "patch export failed: %s\n", s); exit(2); }

int wmain(int argc, wchar_t **argv) {
    if (argc != 8) return 3;
    wchar_t *end;
    unsigned long long text_end = wcstoull(argv[4], &end, 0); if (*end) return 3;
    unsigned long long ro_off = wcstoull(argv[5], &end, 0); if (*end) return 3;
    unsigned long long data_off = wcstoull(argv[6], &end, 0); if (*end) return 3;
    unsigned long long patch_off = wcstoull(argv[7], &end, 0); if (*end) return 3;
    FILE *f = _wfopen(argv[1], L"rb"); if (!f) return 4;
    if (_fseeki64(f, 0, SEEK_END)) return 4;
    __int64 end_file = _ftelli64(f); if (end_file <= 0 || _fseeki64(f, 0, SEEK_SET)) return 4;
    size_t size = (size_t)end_file, pages = (size + 0x3fff) & ~(size_t)0x3fff;
    if (pages < size || text_end > ro_off || ro_off > data_off || data_off > patch_off || patch_off > size ||
        patch_off % 0x4000 || pages > SIZE_MAX - 0x4000) return 4;
    uint8_t *base = _aligned_malloc(pages + 0x4000, 0x4000); if (!base) return 5;
    memset(base, 0, pages + 0x4000);
    if (fread(base, 1, size, f) != size || fclose(f)) return 6;
#ifdef TOTK_VERIFY_IOS
    /* Replay the exported text through the actual iOS patcher's embedded-word checks. */
    size_t text_size = (text_end + 0x3fff) & ~(size_t)0x3fff;
    f = _wfopen(argv[2], L"rb");
    if (!f || fread(base, 1, text_size, f) != text_size || fgetc(f) != EOF || fclose(f)) return 6;
    /* The iOS image also contains exported veneers in the signed patch area. */
    size_t patch_size = pages - (size_t)patch_off;
    f = _wfopen(argv[3], L"rb");
    if (!f || fread(base + patch_off, 1, patch_size, f) != patch_size || fgetc(f) != EOF || fclose(f)) return 6;
#endif
    Module m = {.name="main", .base=base, .size=pages+0x4000, .file_size=size,
                .text_end=text_end, .ro_off=ro_off, .data_off=data_off, .patch_off=patch_off};
#ifdef TOTK_VERIFY_IOS
    /* A saved choice can arrive before the game thread maps the module. */
    runtime_cheat_set(3);
#endif
    runtime_game_patches(&m);
#ifdef TOTK_VERIFY_IOS
    uint32_t flags; memcpy(&flags,base+pages+0x80,sizeof flags);
    if (!runtime_cheat_hooks_ready() || flags != (3u & runtime_cheat_hooks_available())) return 9;
    runtime_cheat_set(4); memcpy(&flags,base+pages+0x80,sizeof flags);
    if (flags != (4u & runtime_cheat_hooks_available())) return 9;
    runtime_cheat_set(0); memcpy(&flags,base+pages+0x80,sizeof flags);
    if (flags) return 9;
    _aligned_free(base);
    return 0;
#else
    size_t text = (text_end + 0x3fff) & ~(size_t)0x3fff;
    f = _wfopen(argv[2], L"wb"); if (!f || fwrite(base, 1, text, f) != text || fclose(f)) return 7;
    f = _wfopen(argv[3], L"wb"); if (!f || fwrite(base+patch_off, 1, pages-patch_off, f) != pages-patch_off || fclose(f)) return 8;
    _aligned_free(base);
    return 0;
#endif
}
