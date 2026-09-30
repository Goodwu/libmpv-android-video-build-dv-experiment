# 归档：FFmpeg 属性门控 P5 RPU 探针补丁（旧世代）

`debug.media_kit.p5_rpu_probe` 属性门控的 mediacodec P5 dovi 探针
（逐帧 + 全流），系 fff3ee7 之前的旧世代。构建链钉定已切换到 Goodwu/FFmpeg
`fff3ee7`（P5 逐帧 RPU 元数据**默认**传递，产品链世代），这两个属性门控
补丁对其不适用。保留供历史诊断构建参考；教训见 media-kit 仓
`archives/experiments/android-p5-mediacodec-color-fix-20260930.md`
（误链旧属性门控 libavcodec 会复演 `direct=0`）。
