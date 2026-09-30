# 归档：mpv 实验线探针补丁（目标基线 63a0aa9）

这些补丁的完整内容已包含于实验线 tip `63a0aa9`（Goodwu/mpv 归档 tag
`archive/android-dv-p5-renderer-202609`）。构建链钉定已切换到产品线
`media-kit/android`（`5e26cf86`）：产品线自带全部产品功能且刻意不含探针，
构建无需任何 mpv 补丁；其中 `mpv_android_swap_trace.patch` 与
`mpv_p5_renderer_mapping_probe.patch` 仍可应用于产品线（诊断构建可复用），
其余三个针对实验期 aimagereader 代码、不适用。诊断探针的另一形态见
media-kit 仓 `archives/experiments/android-mpv-diagnostic-probes-20260930.patch`。
