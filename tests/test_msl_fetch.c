#include "nvn_msl_fetch.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    const char *src = "float4 a = spvDescriptorSet0.fp_t_tcb_22.read(uint2(3), 0);\n"
                      "float4 b = spvDescriptorSet0.fp_t_tcb_24.sample(s, uv);\n";
    assert(nvn_msl_reads_texels(src, "fp_t_tcb_22"));
    assert(!nvn_msl_reads_texels(src, "fp_t_tcb_24"));
    assert(!nvn_msl_reads_texels(src, "fp_t_tcb_2"));
    assert(!nvn_msl_reads_texels(src, "missing"));
    assert(!nvn_msl_reads_texels(src, ""));
    assert(!nvn_msl_reads_texels(NULL, "fp_t_tcb_22"));
    assert(!nvn_msl_reads_texels(src, NULL));
    puts("MSL integer texture read detection passed");
    return 0;
}
