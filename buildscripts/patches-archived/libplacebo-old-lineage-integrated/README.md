# libplacebo 旧线补丁归档（MK-ROUTING-20261011 / DEVICE DV001）

这两个补丁针对旧钉定 c9fd8798（optimize/dovi-linear-decode 分支强推重写前的旧 tip）。
分支重写后 tip ea700489fbf27703d8c1f64874a1c6138f17ad28 已将这些内容以提交形式收编
（980742df PL_SAMPLER_EXTERNAL_YUV、ea700489 rgb10a2/renderable float32 即 r32f P5 登记、
9b6e0834 DV linear light 直解、6a2f2063 gamut clip）：

- libplacebo_external_yuv_sampler.patch → 由 980742df 演进版覆盖（opengl.h/gpu_tex.c/dispatch.c）
- libplacebo_gles_r32f_p5.patch → 由 ea700489 的 GL_R32F 登记覆盖（formats.c）

补丁在新 tip 上 reverse/forward 均不匹配，故从 patches/ 移出归档。
fix_gles_shader_compile_error.patch 与 fix_shaderc_vulkan_dismatch.patch 在新 tip 上仍需
且可干净应用，保留在 patches/libplacebo/。

依据：DEVICE 实机线 DV-BUILD-01 输入审计（2026-10-11），见 media-kit PR#4 DEVICE 登记。
