# 水墨诗画 · 架构梳理

> 本文说明**这个项目在做什么、各模块如何分工、数据怎么流动**。
> 阅读顺序：先看 §1 整体逻辑，再按需跳到对应子系统。
>
> 事实来源：`README.md`（目录与约定）、`src/music/music_render.py`、`data/source/d3/jys_music.json`、
> `build/assemble.py`、`build/verify.py`、`dist/animation/ink_animations.html`。
> 文中所有路径与字段名均取自实际代码，非推测。

---

## 1. 整体逻辑

### 1.1 一句话概括

把三首绝句（江雪 / 早发白帝城 / 静夜思）从**文字**逐步加工成**水墨动画 + 吟诵配音 + 配套音乐**，
每一步都可追溯、可回放、可断言。

### 1.2 六条子链与阶段编号

项目用阶段编号组织，子系统代码目录名即编号：

| 编号 | 子系统 | 职责 | 目录 |
|---|---|---|---|
| D1 | 中古音韵 | 字 → 声 / 韵 / 平仄，韵脚判定 | `src/d1/` |
| D2 | 画法参数 | 三远 / 皴法 / 留白 / 墨阶 / 人物尺寸 + 视点 / 天候 / 时辰 / 材质 / 构图 / 钤印 | `src/d2/` |
| D5 | 语境资料 | 每首诗的语境文本 + schema 校验 | `data/source/context/` |
| D6 | 情感词表 | 七情 + 五志 × 85 词 | `data/source/emotion_lexicon.json` |
| O1 | 动画忠实度 | 判读帧 / 探针 / 评分，验证画面是否忠于诗 | `src/o1/` |
| O2 | 意象抽取 | 分词 → 抽取 → 消歧 → **可画性门控** | `src/o2/` |
| O3 | 负节点 | 判定「不该画什么」 | `src/o3/` |
| D3 | 音乐 | 读声法表 → 采样渲染 → `dist/audio/music/*.wav` | `src/music/` |
| voice | 配音 | 底样 → 吟诵版 → 情感版 + 韵律后处理 | `src/voice/` |

字母前缀 `o` =客观评估侧，`d` =设计/生成侧。这套命名来自项目早期的研究分期。

### 1.3 三条链的关系

```
诗文本
  │
  ├─ D1 音韵 ──────────→ 平仄 / 韵脚        （决定音乐结构与吟诵节奏）
  ├─ D5 语境 ──────────→ 语境约束
  ├─ D6 情感 ──────────→ V / A / T 三档
  │
  ├─ D2 画法参数 ──────→ 三远 / 皴法 / 墨阶 …（画面属性处方）
  │        │
  │        └─→ 注入 pipeline 页STEP 5/6
  │
  ├─ O2 意象 ─→ O3 负节点 ─→ 决定「画什么 / 不画什么」
  │        │
  │        └─→ 门控结果喂给 D2
  │
  ├─ voice 配音 ────────→ 逐字帧 + 实测总时长（唯一时间基准）
  │        │
  │        └─→ 行时序 line_windows ─┐
  │                                │
  └─ D3 音乐 ──────────────────────┴──→ 音乐轨（时长必须等于配音时长）

三者合成 → dist/animation/ink_animations.html（画面 + 配音 + 音乐）
                │
                └─→ build/scene_render.py 抽取几何 → data/source/scene/<pid>.json
                          └─→ 反向渲染 STEP5/6，并被 scene_assert.py 度量断言
```

**关键设计：配音是唯一的时间基准。** 音乐轨时长必须等于配音实测总时长（同一把尺子），
逐字起音按配音 `syllables[].frames` 作权重分配。画面、语音、音乐三者共用一条时间轴。

---

## 2. 数据分层

项目对数据做了**两种正交的分类**。

### 2.1 按角色域（纵向）

决定文件「给谁看、干什么用」：`docs` / `data` / `src` / `dist` / `build`。

### 2.2 按生命周期（横向）

| 分类 | 含义 | 可否重算 | 典型内容 |
|---|---|---|---|
| `source` | **冻结输入** | 否，人工维护 | 声法表、语境资料、词典、场景几何、笔顺 |
| `derived` | 由 source 推导 | 是 | D1 韵书、D2 技法、O2 意象、O3 负节点 |
| `runs` | 一次跑批的产物 | 是，每次覆盖 | 回归报告、覆盖率、探针、评分 |

### 2.3 source 内部分区

| 子目录 | 内容 |
|---|---|
| `data/source/context/` | 三首诗的 `context.json` + `语境资料.md` + `schema.json` |
| `data/source/d2_seed/` | D2 画法种子：意象—画法映射、画论规则 |
| `data/source/d3/` | **音乐层单一真源**：`<pid>_music.json` 声法表 + 各乐器采样库 + `manifest.json` |
| `data/source/rhyme/` | 平水韵字典（字 → 声 / 韵 / 平仄） |
| `data/source/scene/` | 场景几何冻结（`bd` / `jx` / `jys`） |
| `data/source/strokes/` | 笔顺 / 中线（`hanzi-writer-data`，Arphic Public License） |
| `data/source/o2_gate.json` | O2 虚实阈值真源（`conc → 实写 / 虚写 / 不可实写`） |

### 2.4 路径解析约定

- **Python**：`ROOT` 上溯到仓库根，其余一律 `os.path.join(ROOT, ...)`
- **Node**：`ROOT = path.resolve(__dirname, '..', '..')`；读数据走 `datapath()` 三级回退（`source → derived → runs`）
- **交付包内相对引用**由 `build/assemble.py` 装配时改写，源文件保持 canonical 路径

---

## 3. 模块详解

### 3.1 D3 音乐层（当前焦点）

这是最近改动最多的子系统，也是文档需要最详细的部分。

#### 3.1.1 单一真源：声法表

`data/source/d3/<pid>_music.json` 承载全部音乐决策。渲染器**只读不编曲**。

以《静夜思》为例，其结构字段：

| 字段 | 内容 |
|---|---|
| `meta` | 角色说明、依据文献、边界声明 |
| `poem` | `pid` / `title` / `author` / `lines` |
| `anchor` | **时间基准**：`T` 总时长、`line_windows` 行窗口、`breath_windows` 气口、语音 json 路径 |
| `mode` | 调式：`tonic_hz`（C5 = 523.25）、`scale_semitones`（C D E G A）、`V_A_T` |
| `instrument` | `lead` 主奏、`guest` 客声 |
| `meter` | 板式（一板三眼） |
| `structure` | 散起 → 入调 → 入慢 → 尾声 |
| `rules` | 连贯与连奏参数 |
| `events[]` | **逐字音事件**：`line` / `pos` / `char` / `deg` / `oct` / `voice` / `gain` / `rhyme` |
| `散起` / `breath_events[]` | 低音层 |
| `guest_events[]` | 客声点弦 |
| `mix` | 混响分档、峰值、软削波 |
| `checks` | 断言阈值（时长容差、静默上限、波峰因数） |

关键字段语义：

- **`anchor.T`** = 配音实测总时长（18.187 秒），音乐轨必须等于它
- **`anchor.line_windows`** = 各行的起止时间，是画面与音乐共用的行时序
- **`events[].deg`** = 音级索引（0 = 宫/C，2 = 商/D，4 = 角/E…），对应 `scale_semitones`
- **`events[].oct`** = 八度偏移。`tonic_hz` 是 C5，故`oct=0` 即 C5，`oct=-1` 即 C4
- **`rules.ring_max_s` / `ring_min_s` / `note_overlap_s`** = 连贯规则：每个音「响到下一次起音 + overlap」，
  行间气口由前音余响与气口低散音贯入，**不设长静默**
- **`rules.legato`** = 连奏：按气口切乐句（`break_gap_s`），句内只换指不重新起音（`glide_ms`），
  韵脚并入前乐句且禁止 1 字乐句

#### 3.1.2 渲染管线

`src/music/music_render.py` 的 `build()` 流程：

```
build(plan, sr, bank=…, dizi_bank=…, xiao_bank=…, khim_bank=…, guzheng_bank=…)
│
├─ 1. 读anchor.T → 分配总长度 n_total = T × sr
│
├─ 2. 逐字起音分配
│     读 voice_json的 syllables[].frames 作权重
│     → 归一化 → 累积分配到各行窗口
│     ⇒ onsets[(line, pos)] = 真实起音时刻
│
├─ 3. 音高换算：pitch(deg, oct) = tonic_hz × 2^((scale[deg] + 12×oct)/12)
│
├─ 4. 乐句切分 _legato_groups()
│     按 rules.legato.break_gap_s 切句，韵脚并入前句
│     ⇒ groups: [乐句 = [音符…]]
│
├─ 5. 主奏渲染 _render_phrase()
│     连奏路径：整句共用一条相位，音间靠换指滑音过渡
│     ├─ dizi_bank.phrase()   真实笛干声
│     └─ xiao_bank.phrase()   真实箫干声（缺失时退回 xiao_phrase 合成）
│
├─ 6. 支持层渲染
│     ├─ 散起 / breath_events → drone（guzheng 或 guqin）
│     └─ guest_events→ 筝 / 扬琴轻点（吸附乐句，不按逐字起音）
│
├─ 7. 叠加 dry → body() 琴体共鸣 → reverb() 双轨混响
│     ├─ body()  三段体腔共振，可由 mix.body_bands 覆盖
│     ├─ reverb() 近场 + 远场分档（rt60 / predelay / wet / lp_hz）
│     ├─ 可选 _tone() 主奏音色整形（lp_hz / shelf_db，须声法表显式配置）
│     └─ soft_clip 分档动态（江雪 1.0 / 静夜思 0.6 / 白帝城 0.4）
│
└─ 8. 归一化到target_peak_dbfs，尾部 tail_fade_ms 渐隐
      ⇒ (mix, meta)
```

`meta` 携带调试与断言所需的全部信息：`trace`（逐音取源记录）、
`lead_bus`（纯主奏干声轨）、`fallback_log`（退路登记）。

#### 3.1.3 采样器层

`src/music/sampler.py` 为五个乐器各提供一个 Bank，接口刻意对齐
（`pick` / `note` / `phrase`）：

| Bank | 乐器 | 素材 | 许可 |
|---|---|---|---|
| `Bank` | 古琴 | GuqinSonGest 干声 | CC BY 4.0 |
| `DiziBank` | 竹笛 | Hypnotriod（Freesound 21613） | CC0 1.0 |
| `XiaoBank` | 北箫 | pattingthestar Beixiao-Raw.sf2 | CC0 1.0 |
| `KhimBank` | 扬琴 | pattingthestar Khim | CC0 1.0 |
| `GuzhengBank` | 古筝 | Pufermufin（Freesound 396868） | CC0 1.0 |

共同职责：就近取源 → 变调播放 → 散/泛/按分色 → 走手音 → 吟猱。
`max_semi` 超限时回退全池并登记 `fallback_log`。

各乐器差异集中在**衰减长度**与**调性约束**：
扬琴 tau 0.85s、古筝 1.6s（弦长余响更慢）；
古筝为 D 五声音阶素材，`GuzhengBank.snap` 先吸附到调内音级，超容差则标「⚠ 调外」而**不改音高**。

#### 3.1.4 素材构建链

采样库不是原始录音直接可用，需经构建脚本切分定音：

```
Polyphone / Freesound 原始包
  → src/music/build_xiao.py / build_khim.py / build_guzheng.py / build_qudi.py
     ├─ 包络事件切分（不用 SF2 的 shdr name——该字段不可信）
     ├─ 谐波簇定音（不用自相关——在吹奏素材上会锁到 2×）
     └─ 断言段数，生成 data/source/d3/<lib>/<name>.wav + manifest.json
  → sampler 的 Bank 类读取
```

#### 3.1.5 护栏体系

`music_render.py` 内置 10 类护栏，每类都有配对的 `negative` 自检
（`--selftest` 注入负向扰动，证明断言**能失败**，即非空断言）：

| 护栏 | 判据 |
|---|---|
| 时长 | 等于配音实测总时长（容差 2 采样） |
| 连续性 | 最长静默 ≤ 0.30s（100ms 窗、−40 dBFS 门限） |
| 峰值 / 波峰因数 | 峰值 −6…−1 dBFS；波峰因数 ≤ 22 dB |
| 处方兑现 | 音高落点、走手音真滑 |
| 音区 `register_checks` | 每字到最近可用源的变调 ≤ 4.0 半音 |
| 音色（古琴 / 笛 / 箫） | 与参考采样的24 带对数频谱包络距离 |
| 连奏 `legato_checks` | 起伏密度 ≤ 4.5 次/秒；句内最低瞬时电平 > −46 dBFS |
| 箫音色特征 | 峰高突出度 ≤ 60 dB；非等距度 ≥ 12 音分 |

调式取自 D2 的 V/A/T 档：江雪＝羽（古琴 + 箫偶入 · 散板），
早发白帝城＝徵（笛主奏 + 扬琴点缀 · 快板），静夜思＝宫（箫为主 + 古筝轻点 · 一板三眼）。

### 3.2 D2 画法参数

`src/d2/` 把诗学处方转成**可度量的画面属性**：

| 维度 | 取值 |
|---|---|
| 三远 | 高远 / 深远 / 平远 |
| 皴法 | 披麻 / 斧劈 / 米点… |
| 留白 / 墨阶 | 浓淡五档 |
| 人物尺寸 | 四档（高人 / 中人 / 小人…） |
| 视点 / 天候 / 时辰 | — |
| 材质 / 笔法质量 / 构图 / 钤印 | — |

两个入口脚本：`d2_resolve.py`（回归 81 项）、`d2_inject.py`（注入 pipeline 页并内嵌快照）。

### 3.3 O2 意象抽取与可画性门控

`src/o2/o2_imagery.mjs` 是 Node 实现，数据走 `datapath()` 三级回退。

流程：分词 → 抽取 → 消歧 → **可画性门控**。
门控阈值单一真源冻结在 `data/source/o2_gate.json`（`conc → 实写 / 虚写 / 不可实写`），
`--check` 断言「冻结值 = gold 最大裕度中点」「阈值落可行区间」「gold 分类全对」，并做「推过界必错」证伪。

O3 负责负节点：判定**不该画什么**。

### 3.4 动画渲染层

`dist/animation/ink_animations.html` 是**自足单页**（无外部依赖），三首诗各一份配置：

```
SY = { jx / bd / jys } 每首含：
  T              总时长（与音乐轨一致）
  voice          配音 wav 路径 + 内容哈希版本戳
  music          音乐 wav 路径 + 内容哈希版本戳
  voiceLines     人声发声的四段区间（闪避触发区间）
  segs           分段：时间 + 诗句 + 镜头
```

两条时钟：

- **纯音乐模式（默认）**：`voiceOn = !cfg.music`，人声不参与，音乐满电平，以**音乐时钟**为准
- **人声模式**：启用吟诵，音乐按 `voiceLines` 闪避（压低 8 dB），以**人声时钟**为准

两者共用同一时间轴，切换不错位。

逐笔书写由 `dist/animation/strokes.js`（`window.POEM_STROKES`，64 字 / 3 字体）驱动：
每字 = 字形轮廓 `<path>` + 逐笔中线遮罩（笔锋带），按笔顺以 `stroke-dashoffset` 展开。
数据缺失时自动降级为矩形揭示，不影响可用性。

### 3.5 场景几何闭环

这是本项目较特殊的设计——**几何一致 ≠ 处方兑现**，两者分别断言。

```
ink_animations.html（动画）
   │ build/scene_render.py --extract
   ▼
data/source/scene/<pid>.json（几何单一真源）
   │ build/scene_render.py --write
   ▼
pipeline 页 STEP5 线稿 / STEP6 静帧（标记块 <!-- SCENE:<pid>:draft|ink -->）
```

`build/scene_assert.py` 从冻结场景**量取**画面属性，与 D2 现算的处方对账：

| 量取项 | 对账处方 |
|---|---|
| 有效墨浓度 `eff` | `role`（焦点须全场最深或最亮） |
| 柔度 `σ·位移` | `water`（含水档须匹配浓淡与柔度） |
| 人高占比 | `size`（须落在四档区间） |

目的是防「模型算了、画面没照做」。

### 3.6 构建与验证层

`build/` 六个脚本，职责单一：

| 脚本 | 职责 |
|---|---|
| `assemble.py` | 装配交付包（幂等，`--check` 以字节比对判定漂移） |
| `font_subset.py` | 题款七款字体子集 + 印章篆体内嵌 |
| `stroke_data.py` | 题诗逐笔数据（笔顺 + 中线 + 字形合并，含覆盖护栏） |
| `scene_render.py` | 场景几何抽取 / 冻结 / 渲染 |
| `scene_assert.py` | 度量断言（画面属性 ↔ D2 处方） |
| `verify.py` | **全链路体检**（见下） |

`verify.py` 汇总 16 项检查，任一失败即 `exit 1`：

```
── 输入端护栏
  D1 音韵护栏 / D5 语境 schema / D6 情感词表 / O2 虚实阈值 G13
── 控制链与交付
  D2 回归 / D2 注入快照 / 场景几何 / 度量断言
  题诗字体子集 / 题诗逐笔数据
  D3 音乐轨 × 3（jx / bd / jys，各含 10 类护栏）
  音频引用版本戳 / 交付包同步 / 链接检查
```

---

## 4. 数据流全景

### 4.1 音乐链（详细）

```
data/source/d3/jys_music.json（声法表 · 单一真源）
  │
  ├─ anchor.voice_json ──→ dist/audio/voice/jys_emotion_sad_*.json
  │                          └─ syllables[].frames 作权重
  │
  ▼
music_render.build()
  ├─ 采样库（sampler.*Bank）
  │   data/source/d3/{samples,xiao,dizi,guzheng,khim,qudi}/*.wav + manifest.json
  │   └─ 取源 → 变调 → 分色 → 走手音 → 吟猱
  │
  ▼
dist/audio/music/jys.wav  ← 时长严格等于 anchor.T
  │
  ├─→ src/music/stamp_audio_ver.py（盖内容哈希 ?v=xxxxxxxx）
  │      └─→ ink_animations.html 的 music 引用
  │
  └─→ build/assemble.py
         └─→ dist/三首诗歌交付/02_水墨动画_带语音/samples/music/jys.wav
```

### 4.2 画面链

```
data/source/strokes/*.json（笔顺 + 中线冻结）
  │ build/stroke_data.py
  ▼
dist/animation/strokes.js
  │
dist/animation/fonts/*.woff2 ← build/font_subset.py（源字库经 jsDelivr 镜像）
  │
  ▼
dist/animation/ink_animations.html（自足单页）
  │
  ├─→ build/scene_render.py --extract ─→ data/source/scene/<pid>.json
  │                                          │
  │                                    --write↓
  │                          pipeline 页 STEP5/6
  │
  └─→ build/scene_assert.py（度量断言）
```

### 4.3 交付链

```
dist/pipelines/*.html          ─┐
dist/animation/*               ─┤
dist/audio/voice/*.wav         ─┼─→ build/assemble.py ─→ dist/三首诗歌交付/
dist/audio/music/*.wav         ─┘
                                     01_诗全流程分析/
                                     02_水墨动画_带语音/
                                       ├── ink_animations.html（路径改写为包内 samples/）
                                       ├── strokes.js / fonts/
                                       └── samples/voice/ + samples/music/
```

注意 `index.html` **手工维护，装配不触碰**。

---

## 5. 单一真源清单

改动时只需记住这几处，其余都是派生：

| 真源 | 路径 | 管什么 |
|---|---|---|
| 声法表 | `data/source/d3/<pid>_music.json` | 音乐层全部决策 |
| 场景几何 | `data/source/scene/<pid>.json` | 动画元素坐标 |
| O2 门控阈值 | `data/source/o2_gate.json` | 实写/虚写/不可实写 |
| 题款字体 | `dist/animation/fonts/*.woff2` | 七款子集 |
| 逐笔数据 | `dist/animation/strokes.js` | 笔顺 + 中线 + 字形 |
| 平水韵字典 | `data/source/rhyme/pingshui_rhyme_dict.json` | 字 → 声/韵/平仄 |
| 语境资料 | `data/source/context/<诗名>/` | 语义约束 |

**反模式**：不要在渲染器里写死编曲参数，不要在 HTML 里写死坐标，
不要手改 `data/derived/` 与 `data/runs/`（它们会被覆盖）。

---

## 6. 常用入口

```bash
# 全链路体检（改动后 / 提交前必跑）
python build/verify.py

# 交付包
python build/assemble.py           # 装配（幂等）
python build/assemble.py --check   # 只校验同步

# 音乐层
python src/music/music_render.py --pid jys          # 渲染 → dist/audio/music/jys.wav
python src/music/music_render.py --pid jys --check  # 渲染并断言
python src/music/music_render.py --pid jys --selftest  # 负向扰动自检
python src/music/stamp_audio_ver.py                 # 重渲音频后必跑
python src/music/stamp_audio_ver.py --check

# 场景
python build/scene_render.py --extract   # 改动画后重冻几何
python build/scene_render.py --write     # 由几何重渲 STEP5/6
python build/scene_assert.py             # 度量断言

# 其他
python src/d1/d1_resolve.py --check
python src/d2/d2_resolve.py
python src/d2/d2_inject.py --check
node   src/o2/o2_imagery.mjs --check
python build/font_subset.py --check
python build/stroke_data.py --check
```

---

## 7. 两条容易踩的坑

### 7.1 音频重渲后必须盖版本戳

`file://` 下浏览器会缓存 WAV。音频更新后若不跑 `stamp_audio_ver.py`，
页面仍播旧文件——**「主奏修好了却仍听不到」正是此因**。

引用形式：`<name>.wav?v=<md5 前 8 位>`。

### 7.2 几何一致 ≠ 处方兑现

动画、场景数据、pipeline 页三者几何一致，只能说明「没有漂移」，
不能说明「画对了」。后者由 `scene_assert.py` 从冻结场景量取实际属性，
与 D2 现算处方对账——这条断言专门防「模型算了、画面没照做」。

---

## 8. 多人协作

仓库按「**代码入库、素材本地持有**」组织（307 文件 / 7.3 MB）：

- **入库**：声法表 JSON、渲染代码、页面 HTML/JS/CSS、文档
- **不入库**：音频素材（约 200 MB）、渲染产物、位图

新 PC 初始化：

```bash
git clone <仓库>
# 素材需另行拷贝 data/source/d3/{samples,xiao,dizi,guzheng,khim,qudi}/
pip install numpy scipy soundfile
python build/verify.py       # 确认素材就位
```

`manifest.json` 已入库，可用它核对素材是否齐全。

约定：一人一分支；声法表改动在 commit message 写清「改了哪首、哪个音区」；
音频产物各自生成、不提交，要交换用网盘。