# 堆叠卡片滑动切换实现说明（南杉提供，React 版原文，移植 vanilla JS 时逻辑照搬）

## 目标效果
- 多张时合并成叠图卡片，只显示当前一张，后面露边缘成一摞
- 横向滑动切换，一次只切相邻一张；点击只针对当前最前一张
- 切换时当前图退到后面、下一张从后面滑到前面
- 切换结束后不允许再弹/重排/抖

## 核心状态（关键：稳定状态+临时运动状态分离）
- activeIndex：稳定状态下最前的索引
- motion: { phase: dragging|settling, baseIndex, direction: 1|-1, targetIndex, progress: 0-1, accepted }
- motionRef 同步保存最新 motion，避免动画回调拿旧状态
- baseIndex 在拖动开始时固定，拖动中不变

## 姿态函数 stackPose(offset)
- offset 0 → x0 y0 scale1 rotate0 opacity1 zIndex20
- 深度 depth=min(|offset|,3)，firstLayer=min(depth,1)，extra=max(depth-1,0)
- xSpread = 18*firstLayer + extra*12（对称场景；原文有 towardAvatar 收窄逻辑，eco 无头像可对称化）
- y = 6*firstLayer + extra*5；scale = 1-depth*0.04；rotate = side*(1.15*firstLayer+extra*0.5)
- opacity = max(0.44, 1-depth*0.18)；zIndex = max(1, 10-ceil(depth))

## 三层渲染
background（非当前非目标）/ target（切入中）/ current（切出中），全部绝对定位同容器。
容器：position relative; overflow visible; touch-action: pan-y; perspective 800px。
卡片层 pointer-events none，事件统一在外层容器。

## 避免结束重排（最重要）
拖动过程中背景层就移动到最终位置：
- motionProgress = dragging 时 pow(progress, 0.92)，settling 时 progress
- stackShift = direction * motionProgress（有 target 时）
- stackAnchorIndex = baseIndex + stackShift
- 背景 offset = index - stackAnchorIndex；过滤 |offset|<=3.2 且非 base 非 target
progress 到 1 时背景已在终位，清 motion 无肉眼重排。

## 当前/目标图插值
mixPose(from,to,p) 线性插值 x/y/scale/rotate/opacity。
- current: frontPose → stackPose(-direction)
- target: stackPose(direction) → frontPose

## z-index 固定翻层点
layerFlipProgress = 0.48：
- target 在 progress<0.48 用背景 zIndex，之后 24
- current 在 progress>=0.48 用背景位 zIndex，之前 24
禁止 z-index 随手指抖动来回变。

## 滑动参数
swipeDistance=136, dragActivationDistance=14, commitDistance=42
- pointerdown：settling 中忽略；记 startX、baseIndex；setPointerCapture；清 motion
- pointermove：|deltaX|>6 → suppressClick；<=14 不动；方向首次确定后锁定；
  effectiveDistance = max(0, directionalDelta-14)；有 target 时 progress=min(d/136,1)，无 target（越界）压到 0.18 橡皮筋
- pointerup：accepted = effectiveDistance>=42 且有 target；settling progress 置 1（accepted）或 0（回弹）；queueSettleFallback
- pointercancel 同 up 的回弹路径

## 动画结束
只在 current 层监听 transitionend 且 propertyName==='transform'；
finishSettling：accepted 则 setActiveIndex(targetIndex)，然后清 motion。
fallback：setTimeout 320ms 兜底（WebView 可能丢 transitionend）。

## 点击
suppressClickRef 吞掉滑动后的 click，未滑动的 click 才触发卡片操作。

## 禁令清单
- 不要滑完后重排背景（用 stackAnchorIndex 滑动中就位）
- 不要按拖动距离跳多张，一次只切相邻
- 不要全卡动态排序，必须 current/target/background 三层
- 不要 z-index 抖动，用固定翻层点
- 不要内层接管触摸事件
- 不要忘吞 click
