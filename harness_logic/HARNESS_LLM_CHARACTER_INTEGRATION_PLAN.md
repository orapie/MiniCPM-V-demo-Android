# Harness LLM 项目化与角色系统接入计划书

本文档基于当前两个已有模块制定后续改造计划：

- `harness_logic/harness_logic.py`：从 Android 项目提取出的 Python Harness 编排脚本。
- `character_system/`：短篇小说 NPC 角色卡、剧情事件、知识边界和 Prompt 编译系统。

目标分三步：

1. 将 `harness_logic.py` 扩展为一个可以接入真实 LLM 的完整 Python 项目。
2. 将 `character_system` 中的角色系统接入 Harness，使 Harness 可以按 NPC 身份编译 Prompt，并调用 LLM 完成角色化单轮或多轮生成。
3. 将角色能力抽象为可插拔的角色包机制，为后续端侧 LLM 游戏 SDK 保留持续扩展能力。

本文只做计划，不直接实现代码。

## 1. 当前现状

### 1.1 harness_logic 当前能力

当前 `harness_logic/harness_logic.py` 已经具备一套可运行的 Harness 雏形：

- `ModelInfo`：模型元数据，来自 Android `ModelInfo.kt`。
- `HarnessModelSpec`：通用模型描述，包含 family、capability、artifact、download source、runtime hints。
- `HarnessModelRegistry`：模型注册表，负责从 legacy model info 暴露 spec。
- `LlamaModelStore`：模型选择、本地模型路径、artifact 完整性检查、旧布局迁移。
- `LlamaDownloadManager`：生成 HuggingFace、ModelScope、Direct URL 下载计划。
- `HarnessBackend`：当前是 mock backend，不做真实推理。
- `LlamaBackendAdapter`：保留 Android adapter 形态，但 Python 里继承 mock backend。
- `HarnessFacade`：统一入口，封装模型、存储、下载和 backend 调用。
- CLI：支持 `list`、`spec`、`select`、`status`、`download-plan`、`migrate`、`touch-demo-files`、`load`、`prompt`、`delete`。

当前边界：

- 不调用 Android `LlamaEngine`。
- 不调用 JNI。
- 不加载真实 GGUF。
- 不真实下载模型。
- 不做真实 LLM 推理。
- `prompt` 只是 mock 输出。

### 1.2 character_system 当前能力

`character_system/` 已经是相对独立的角色 Prompt 编译模块。

核心数据和代码包括：

- `characters/*.json`：NPC 角色卡，目前包括 `lu_jiangxian` 和 `xuan_an`。
- `story/story_events.jsonl`：公共剧情事件，一份事件表供多个角色共享。
- `prompts/roleplay_system.prompt`：唯一共享 roleplay system prompt 模板。
- `runtime/prompt_compiler.py`：核心运行时编译器。
- `runtime/retrieval.py`：低依赖关键词检索器，可替换为 BM25 或向量检索。
- `runtime/knowledge_filter.py`：知识边界过滤，避免未来事件、越权知识、元问题进入 Prompt。
- `runtime/memory_retriever.py`：按授权事件召回角色个人经历。
- `runtime/validation.py`：角色卡、事件和引用校验。
- `tests/test_character_system.py`：验证 schema、知识边界、预算裁剪、注入隔离等行为。

核心 API：

```python
from pathlib import Path
from runtime import PromptCompiler, RuntimeContext

compiler = PromptCompiler(Path("character_system"))
compiled = compiler.build_npc_prompt(
    npc_id="lu_jiangxian",
    user_input="玄谙究竟是什么？",
    runtime_context=RuntimeContext(
        story_cutoff="evt-010",
        max_chars=4500,
        dynamic_state={"affinity": -10},
    ),
)

messages_for_model = compiled.messages
local_debug_only = compiled.debug
```

输出契约：

- `compiled.messages[0]` 是可信 `system`。
- `compiled.messages[1]` 是未经信任的原始 `user`。
- `compiled.debug` 只允许写本地日志，不能发送给模型。
- Harness 只需要接收 `messages_for_model`，再按目标模型的 chat template 序列化或直接调用 chat API。

## 2. 总体目标架构

目标不是把 `character_system` 的逻辑复制进 Harness，而是让 Harness 调用它的稳定 Runtime API。

如果后续目标是端侧 LLM 游戏 SDK，角色不应是代码分支，而应是数据资产。Harness Core 只负责加载、校验、注册、编译和调用；新增角色时应主要新增角色包和剧情数据，而不是修改核心逻辑。

SDK 级目标分层：

```text
Game LLM SDK
  ├─ Model Runtime Layer
  │   ├─ llama.cpp / Android JNI / OpenAI-compatible / mock
  │   └─ 模型加载、生成、流式输出、停止词、chat template
  ├─ Harness Core
  │   ├─ 模型注册
  │   ├─ backend 调度
  │   ├─ session 管理
  │   └─ 统一 chat / character chat API
  ├─ Character Runtime
  │   ├─ PromptCompiler
  │   ├─ 知识边界过滤
  │   ├─ 记忆检索
  │   └─ 预算裁剪
  ├─ Character Pack Registry
  │   ├─ 角色包扫描
  │   ├─ schema 校验
  │   ├─ 版本迁移
  │   └─ 角色元数据索引
  └─ Game State Adapter
      ├─ 场景
      ├─ 任务状态
      ├─ 亲近度 / 情绪 / 阵营
      └─ 游戏引擎运行时变量映射
```

推荐目标结构：

```text
harness_logic/
├── pyproject.toml
├── README.md
├── harness_logic/
│   ├── __init__.py
│   ├── models.py
│   ├── registry.py
│   ├── store.py
│   ├── download.py
│   ├── backend.py
│   ├── backends/
│   │   ├── __init__.py
│   │   ├── mock_backend.py
│   │   ├── llama_cpp_backend.py
│   │   └── openai_compatible_backend.py
│   ├── chat_template.py
│   ├── session.py
│   ├── character_adapter.py
│   ├── character_pack.py
│   ├── character_registry.py
│   ├── game_state.py
│   ├── facade.py
│   └── cli.py
├── tests/
│   ├── test_registry.py
│   ├── test_store.py
│   ├── test_chat_template.py
│   ├── test_character_adapter.py
│   ├── test_character_registry.py
│   ├── test_game_state.py
│   └── test_cli.py
└── HARNESS_LLM_CHARACTER_INTEGRATION_PLAN.md
```

当前单文件 `harness_logic.py` 可以先保留作为兼容入口，逐步拆成 package 后变成薄 wrapper。

目标运行链路：

```text
用户输入
  -> Harness CLI / API
      -> CharacterPromptAdapter
          -> character_system.PromptCompiler
              -> messages: [system, user]
      -> HarnessFacade.chat(messages)
          -> selected HarnessModelSpec
          -> BackendFactory
          -> LLMBackend.generate_chat(messages, options)
              -> llama.cpp / OpenAI-compatible API / mock
      -> assistant response
      -> SessionStore 更新对话摘要或日志
```

关键原则：

- `character_system` 负责角色知识、Prompt 编译和授权边界。
- `harness_logic` 负责模型选择、模型文件、backend、chat template、生成参数和会话。
- `CharacterPackRegistry` 负责发现、校验和注册角色包。
- `GameStateAdapter` 负责把游戏状态映射为 `RuntimeContext.dynamic_state`。
- `debug` 只能进入本地日志，不能进入 LLM prompt。
- 用户原始输入只作为 `user` message，不插值进可信 system prompt。
- 真实 backend 必须支持 `messages`，不能只接收裸字符串。

核心设计约束：

- 模型可换：角色包不绑定特定模型。
- 角色可插拔：新增角色不改 Harness Core。
- 剧情知识可检索：事件和记忆通过统一 retriever 进入 Prompt。
- 游戏状态可注入：场景、任务、亲近度、情绪由游戏运行时传入。
- Prompt 编译统一：不同角色复用同一编译流程。
- Harness 只做编排：不直接拼角色卡，不越过知识边界。

## 2.1 角色包扩展性方案

### 2.1.1 角色包是内容资产

为了支持后续游戏 SDK 中持续新增 NPC，角色应以角色包形式存在：

```text
character_packs/
  lu_jiangxian/
    pack.json
    character.json
    relationships.json
    memories.jsonl
    story_events.jsonl
    prompts/
      roleplay_system.prompt
    migrations/
      1.0.0_to_1.1.0.py

  xuan_an/
    pack.json
    character.json
    relationships.json
    memories.jsonl
    story_events.jsonl
    prompts/
      roleplay_system.prompt
```

当前 `character_system/` 可以视为第一版内置角色包集合。后续可以保持兼容：

```text
character_system/
  characters/
  story/
  prompts/
  runtime/
```

但 SDK 抽象层不应写死 `character_system/characters/*.json`，而应通过 `CharacterPackRegistry` 扫描一个或多个角色包根目录。

### 2.1.2 pack.json 契约

每个角色包建议增加 `pack.json`：

```json
{
  "pack_id": "builtin_novel_test",
  "schema_version": "1.0.0",
  "display_name": "短篇小说测试角色包",
  "characters": [
    {
      "character_id": "lu_jiangxian",
      "display_name": "陆江仙",
      "aliases": ["鉴身", "玄鉴"],
      "character_file": "character.json",
      "story_events_file": "story_events.jsonl",
      "prompt_template": "prompts/roleplay_system.prompt"
    }
  ],
  "default_cutoff": "evt-018",
  "locale": "zh-CN"
}
```

角色包必须声明：

- `pack_id`
- `schema_version`
- 可用角色列表
- 每个角色的数据文件
- story events 文件
- prompt 模板
- 默认剧情截止点
- locale

### 2.1.3 CharacterSpec

Harness 不应直接依赖某个 JSON 文件内部细节。建议抽象出 SDK 级 `CharacterSpec`：

```python
@dataclass
class CharacterSpec:
    character_id: str
    display_name: str
    aliases: list[str]
    pack_id: str
    schema_version: str
    default_cutoff: str | None
    supported_locales: list[str]
    dynamic_state_schema: dict[str, Any] | None = None
```

`CharacterSpec` 只用于注册、展示和选择；真正 Prompt 编译仍交给角色 runtime。

### 2.1.4 CharacterPackRegistry

新增 `character_registry.py`：

```python
class CharacterPackRegistry:
    def __init__(self, roots: list[Path]):
        self.roots = roots

    def scan(self) -> list[CharacterSpec]:
        ...

    def find(self, character_id: str) -> CharacterSpec | None:
        ...

    def resolve_runtime_root(self, character_id: str) -> Path:
        ...
```

它的职责：

- 扫描角色包目录。
- 读取 `pack.json`。
- 校验 schema version。
- 建立 `character_id -> CharacterSpec` 索引。
- 检查重复角色 ID。
- 提供给 UI / CLI 角色列表。

新增角色的理想流程：

```text
新增角色包目录
  -> 写 pack.json / character.json / events / memories
  -> 运行 schema 校验
  -> CharacterPackRegistry 自动发现
  -> UI 或 CLI 可以选择该角色
  -> PromptCompiler 编译
  -> Harness 调用 backend
```

核心要求：新增角色不修改 `HarnessFacade`，不修改 backend，不修改模型注册。

## 3. 第一阶段：把 harness_logic 从单脚本整理成项目

### 3.1 目标

将当前单文件脚本拆成可维护的 Python package，同时保留原 CLI 行为。

### 3.2 拆分模块

建议按当前类职责拆分：

| 当前类或函数 | 新模块 | 说明 |
| --- | --- | --- |
| `ModelInfo`、`HarnessModelSpec`、artifact 等 dataclass | `models.py` | 只放数据结构和枚举 |
| `AVAILABLE_MODELS`、`model_to_harness_spec()` | `registry.py` | 模型清单、spec 转换和注册表 |
| `JsonPreferenceStore`、`LlamaModelStore` | `store.py` | 选中模型、本地文件和状态 |
| `LlamaDownloadManager`、`DownloadCandidate` | `download.py` | 下载计划和后续真实下载入口 |
| `HarnessBackend`、backend protocol | `backend.py` | 定义统一 backend interface |
| `LlamaBackendAdapter` mock 实现 | `backends/mock_backend.py` | 保留当前可运行行为 |
| 角色包扫描、角色列表、schema version | `character_registry.py` | 面向 SDK 的角色包注册 |
| 游戏状态到角色动态状态的映射 | `game_state.py` | 解耦游戏引擎和角色 runtime |
| `HarnessFacade` | `facade.py` | 统一 API |
| argparse 命令 | `cli.py` | 命令行入口 |

### 3.3 项目文件

新增：

- `pyproject.toml`
- `README.md`
- package 内 `__init__.py`
- `tests/`

`pyproject.toml` 初期可不强制引入重依赖。真实 LLM backend 依赖应做 optional extra：

```toml
[project.optional-dependencies]
llama-cpp = ["llama-cpp-python"]
server = ["fastapi", "uvicorn"]
dev = ["pytest"]
```

### 3.4 保留兼容入口

当前 `harness_logic/harness_logic.py` 可以保留，并修改为：

```python
from harness_logic.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

这样已有命令仍可运行：

```bash
python harness_logic/harness_logic.py list
```

未来也可以支持：

```bash
python -m harness_logic list
```

## 4. 第二阶段：定义真实 LLM Backend 接口

### 4.1 目标

把当前 mock backend 抽象成统一接口，允许接入多种 LLM runtime。

建议新增协议：

```python
class LLMBackend(Protocol):
    state: LlamaState

    def load_model(self, model_files: LlamaModelFiles, spec: HarnessModelSpec) -> None:
        ...

    def unload_model(self) -> None:
        ...

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        options: GenerationOptions,
    ) -> Iterator[str]:
        ...
```

`send_user_prompt(message: str)` 作为低层兼容方法保留，但角色系统接入应使用 `generate_chat(messages)`。

### 4.2 GenerationOptions

新增统一生成参数：

```python
@dataclass
class GenerationOptions:
    max_tokens: int = 1024
    temperature: float = 0.7
    top_p: float = 0.9
    stop: list[str] = field(default_factory=list)
    stream: bool = True
    seed: int | None = None
```

可从 `HarnessModelSpec.runtime_hints` 生成默认值。

### 4.3 Backend 类型

建议分三类接入：

#### MockBackend

继续保留，用于测试和无模型演示。

用途：

- CLI 冒烟测试。
- Character adapter 测试。
- CI 不需要下载大模型。

#### LlamaCppBackend

接入本地 GGUF，优先考虑 `llama-cpp-python`。

职责：

- 加载 `llm` artifact。
- 对 vision 模型，先只记录 `vision_projector` 路径；是否真实支持多模态取决于所选 binding。
- 支持 chat messages。
- 支持 streaming。
- 支持 stop tokens。

注意：

- `llama-cpp-python` 对不同多模态模型的 mmproj 支持需要单独验证。
- MiniCPM-V / VoxCPM2 可能需要 Android 项目中 `llama.cpp-omni` 的特殊能力，不能假设普通 binding 直接支持。
- 第一版真实 LLM 项目建议先以 text-only 模型跑通，例如 `llama-3.2-1b-instruct` 或 `qwen3-0.6b`。

#### OpenAICompatibleBackend

接入本地或远端 OpenAI-compatible chat completion server。

用途：

- 快速验证角色系统效果。
- 绕过本地 GGUF 多模态支持问题。
- 支持 vLLM、llama.cpp server、Ollama 兼容层或其他本地服务。

接口：

```text
POST /v1/chat/completions
messages: [...]
stream: true/false
```

配置建议：

```json
{
  "backend": "openai_compatible",
  "base_url": "http://127.0.0.1:8000/v1",
  "api_key": "optional",
  "model": "local-model"
}
```

## 5. 第三阶段：Chat Template 与消息序列化

### 5.1 为什么需要 Chat Template

`character_system` 输出的是标准 chat messages：

```json
[
  {"role": "system", "content": "..."},
  {"role": "user", "content": "..."}
]
```

如果 backend 是 OpenAI-compatible，可以直接传 messages。

如果 backend 是裸 llama.cpp generate，需要把 messages 序列化成模型需要的 prompt 字符串。这个逻辑应属于 Harness，而不是 `character_system`。

### 5.2 建议设计

新增 `chat_template.py`：

```python
class ChatTemplate(Protocol):
    def render(self, messages: list[dict[str, str]]) -> str:
        ...
```

内置模板：

- `openai_passthrough`：不序列化，直接交给 chat API。
- `generic_chatml`
- `llama3`
- `qwen`
- `minicpm`

第一阶段只需要支持：

- OpenAI-compatible 直接传 messages。
- Mock backend 直接读取 messages。
- Llama.cpp text-only 模型使用一个明确模板。

### 5.3 模板选择

在 `HarnessRuntimeHints` 或新增字段中加入：

```python
chat_template: str | None = None
```

或者在 backend config 中覆盖：

```json
{
  "model_id": "qwen3-0.6b",
  "chat_template": "qwen"
}
```

## 6. 第四阶段：接入 character_system 与角色包机制

### 6.1 新增 CharacterPromptAdapter

建议新增 `character_adapter.py`：

```python
@dataclass
class CharacterTurnRequest:
    character_id: str
    user_input: str
    story_cutoff: str | None = None
    max_chars: int = 4500
    dynamic_state: dict[str, Any] | None = None
    conversation_summary: str = ""
    top_k: int = 8

@dataclass
class CharacterTurn:
    messages: list[dict[str, str]]
    debug: dict[str, Any]
```

核心方法：

```python
class CharacterPromptAdapter:
    def __init__(self, registry: CharacterPackRegistry):
        self.registry = registry

    def compile_turn(self, request: CharacterTurnRequest) -> CharacterTurn:
        runtime_root = self.registry.resolve_runtime_root(request.character_id)
        compiler = PromptCompiler(runtime_root)
        compiled = compiler.build_npc_prompt(
            request.character_id,
            request.user_input,
            RuntimeContext(
                story_cutoff=request.story_cutoff,
                max_chars=request.max_chars,
                dynamic_state=request.dynamic_state,
                conversation_summary=request.conversation_summary,
                top_k=request.top_k,
            ),
        )
        return CharacterTurn(messages=compiled.messages, debug=compiled.debug)
```

注意：示例中的 `PromptCompiler(runtime_root)` 是最小方案。正式项目中应缓存 compiler，并在角色包变更时失效，避免每轮重新加载事件和模板。

### 6.2 新增 CharacterPackRegistry

`CharacterPromptAdapter` 不应写死 `character_system/`，而应通过 `CharacterPackRegistry` 解析角色来源。

第一版兼容当前目录：

```text
character_system/
  characters/lu_jiangxian.json
  characters/xuan_an.json
  story/story_events.jsonl
  prompts/roleplay_system.prompt
```

可以把它注册成一个内置 pack：

```python
registry = CharacterPackRegistry.builtin(
    root=Path("character_system"),
    pack_id="builtin_novel_test",
)
```

后续扩展到多包：

```python
registry = CharacterPackRegistry([
    Path("character_system"),
    Path("game_content/character_packs"),
    Path("dlc/characters"),
])
```

### 6.3 角色新增流程

新增角色不应修改 `HarnessFacade` 或 backend。流程应是：

```text
1. 新增角色 JSON / 角色包
2. 新增或复用 story_events.jsonl
3. 新增 memories / relationships
4. 运行 validate
5. CharacterPackRegistry 扫描到角色
6. CLI/UI 可选择该角色
7. CharacterPromptAdapter 编译角色 messages
8. Harness 调用当前模型生成
```

对于 SDK，建议把“角色包构建”和“运行时加载”分开：

- 构建期：严格校验 schema、证据引用、事件引用、重复 ID。
- 运行期：只加载已通过校验的角色包，避免端侧启动时做昂贵检查。

### 6.4 角色包版本迁移

所有角色包必须带 `schema_version`。当 schema 升级时，不直接破坏旧角色包，而是提供迁移链：

```text
1.0.0 -> 1.1.0 -> 1.2.0
```

Harness 启动时的策略：

- 支持当前 schema：直接加载。
- 支持旧 schema 且有迁移器：迁移后加载。
- 不支持 schema：拒绝加载该角色包，并给出明确错误。

迁移应优先作为构建期工具执行，不建议在游戏运行时频繁改写内容资产。

### 6.5 Facade 新增角色生成方法

在 `HarnessFacade` 中新增：

```python
def generate_character_turn(
    self,
    request: CharacterTurnRequest,
    options: GenerationOptions | None = None,
) -> Iterator[str]:
    turn = self.character_adapter.compile_turn(request)
    self.log_debug(turn.debug)
    yield from self.backend.generate_chat(turn.messages, options or self.default_options())
```

约束：

- `turn.debug` 只能写入本地日志或返回给 CLI `--debug`。
- 不得把 `debug` 拼入 `messages`。
- 角色身份、知识边界、未来事件过滤由 `character_system` 完成。
- Harness 只负责发送编译后的 messages。
- Harness 不关心角色 JSON 的内部字段，只处理 `CharacterTurnRequest`、`messages` 和 `debug`。

### 6.6 CLI 设计

新增命令：

```bash
python -m harness_logic character-list
python -m harness_logic character-pack validate --path character_system
python -m harness_logic character-prompt \
  --character lu_jiangxian \
  --input "玄谙究竟是什么？" \
  --cutoff evt-010 \
  --debug

python -m harness_logic character-chat \
  --character lu_jiangxian \
  --input "玄谙究竟是什么？" \
  --cutoff evt-010 \
  --model llama-3.2-1b-instruct
```

命令职责：

- `character-list`：列出所有注册角色包中的可用角色。
- `character-pack validate`：校验角色包数据、schema、事件和引用。
- `character-prompt`：只编译并输出 messages，不调用 LLM。
- `character-chat`：编译 messages 并调用当前 backend 生成 assistant。

### 6.7 Python API 设计

目标 API：

```python
from pathlib import Path
from harness_logic import HarnessFacade, CharacterTurnRequest, CharacterPackRegistry

registry = CharacterPackRegistry([
    Path("character_system"),
    Path("game_content/character_packs"),
])

harness = HarnessFacade(
    root_dir=Path("."),
    character_registry=registry,
)

harness.set_selected_model("llama-3.2-1b-instruct")
harness.load_selected_model()

for chunk in harness.generate_character_turn(
    CharacterTurnRequest(
        character_id="lu_jiangxian",
        user_input="玄谙究竟是什么？",
        story_cutoff="evt-010",
    )
):
    print(chunk, end="")
```

### 6.8 UI / 游戏 SDK 视角

对原 Android Demo 或未来游戏 SDK，UI 不应把“模型”和“角色”混成一个选择项。

推荐 UI 概念：

```text
模型选择
  - llama-3.2-1b-instruct
  - qwen3-0.6b
  - minicpm5-0.9b

对话模式
  - 普通对话
  - 角色对话

角色对话设置
  - 角色：陆江仙 / 玄谙 / DLC 角色
  - 剧情截止点：evt-018
  - 场景：洞华天青铜门外
  - 亲近度：-20
  - 情绪：克制而警惕
```

这样同一个角色可以运行在不同模型上，同一个模型也可以用于普通对话或角色对话。

## 7. 第五阶段：会话与长对话状态

### 7.1 当前 character_system 的边界

`character_system` 支持传入：

- `conversation_summary`
- `dynamic_state`

但它不自行总结长对话，也不负责会话存储。

这部分应该由 Harness 负责。

### 7.2 新增 SessionStore

建议新增 `session.py`：

```python
@dataclass
class ConversationTurn:
    role: str
    content: str
    timestamp: str

@dataclass
class CharacterSession:
    session_id: str
    character_id: str
    character_pack_id: str
    story_cutoff: str
    selected_model_id: str
    turns: list[ConversationTurn]
    conversation_summary: str = ""
    dynamic_state: dict[str, Any] = field(default_factory=dict)
```

存储位置：

```text
<root>/sessions/<session_id>.json
```

### 7.3 长对话摘要策略

第一版不要自动调用 LLM 总结，避免新增不可控行为。先提供手动更新：

```bash
python -m harness_logic session-summary set --session xxx --text "..."
```

第二版再增加：

- 使用同一 backend 总结最近 N 轮。
- 摘要也必须走知识边界，不允许把越权信息注入角色。
- 摘要写入 `RuntimeContext.conversation_summary`。

### 7.4 GameStateAdapter 与 dynamic_state 更新

端侧游戏 SDK 不能假设所有游戏都使用同一套状态字段。Harness 应提供 `GameStateAdapter`，把不同游戏引擎或玩法系统的运行时状态映射到角色 runtime 能理解的 `dynamic_state`。

建议新增：

```python
@dataclass
class GameState:
    scene: str | None = None
    quest_state: str | None = None
    affinity: int | None = None
    emotion: dict[str, Any] | None = None
    faction: str | None = None
    inventory_flags: dict[str, bool] = field(default_factory=dict)
    world_flags: dict[str, Any] = field(default_factory=dict)


class GameStateAdapter(Protocol):
    def to_dynamic_state(
        self,
        character: CharacterSpec,
        state: GameState,
    ) -> dict[str, Any]:
        ...
```

第一版可以提供默认映射：

```text
GameState.scene        -> dynamic_state.scene
GameState.quest_state  -> dynamic_state.quest_state
GameState.affinity     -> dynamic_state.affinity
GameState.emotion      -> dynamic_state.emotion
```

更复杂的游戏项目可以实现自己的 adapter，例如：

- Unity adapter
- Unreal adapter
- Android demo adapter
- 自定义 RPG 状态 adapter

这样角色系统只消费标准 `dynamic_state`，不直接依赖游戏引擎。

第一版同时支持 CLI/API 直接传入 JSON：

```bash
python -m harness_logic character-chat \
  --character lu_jiangxian \
  --input "你现在在哪里？" \
  --dynamic-state '{"scene":"临时测试场景","emotion":{"intensity":0.1}}'
```

后续再增加规则引擎或外部游戏状态适配器。

## 8. 第六阶段：下载与模型管理完善

### 8.1 当前下载计划与真实下载分离

当前 `download-plan` 已能生成 URL，但不下载。

后续可以新增真实下载器：

- 支持 HF / ModelScope / Direct。
- 支持断点续传。
- 支持 MD5 校验。
- 支持 `.tmp` 文件。
- 支持多源竞速。

这部分可以参考 Android `LlamaEngine.downloadModels()`，但不要一开始就完整复刻。建议优先级：

1. 单源 direct 下载。
2. HF / ModelScope URL 下载。
3. MD5 校验。
4. 断点续传。
5. 多源竞速。

### 8.2 模型准备状态

新增命令：

```bash
python -m harness_logic model-status
python -m harness_logic model-download --model llama-3.2-1b-instruct
python -m harness_logic model-verify --model minicpm-v-4_6-instruct
```

角色系统本身不应关心模型文件是否存在。

## 9. 测试计划

### 9.1 保留 character_system 原测试

继续运行：

```bash
python -m unittest discover -s character_system/tests -v
```

这验证角色卡、事件、知识边界、预算裁剪、提示注入隔离等行为。

### 9.2 Harness 单元测试

新增：

- registry 测试：所有 `AVAILABLE_MODELS` 能生成 spec。
- store 测试：选中模型、artifact 路径、完整性检查。
- download plan 测试：HF / MS / Direct URL 正确展开。
- backend mock 测试：load、generate_chat、state 流转。
- chat template 测试：system/user 顺序正确，特殊 token 不错位。
- character registry 测试：角色包扫描、重复 ID 拒绝、schema version 检查。
- game state adapter 测试：游戏状态稳定映射到 `dynamic_state`。

### 9.3 Character adapter 测试

重点测试：

- `compile_turn()` 输出 `system` + `user` 两条消息。
- prompt injection 留在 user message，不进入 system。
- `debug` 不进入 messages。
- 未来事件被过滤。
- `story_cutoff` 改变时，允许事件集合随之变化。
- `character_id` 通过 `CharacterPackRegistry` 解析，而不是写死当前目录。
- 新增角色包后，无需修改 `HarnessFacade` 即可被发现。
- 不同角色包的 prompt template、events 和 cutoff 不互相污染。

### 9.4 端到端测试

使用 mock backend：

```bash
python -m harness_logic character-chat \
  --backend mock \
  --character lu_jiangxian \
  --input "你怎么看玄谙？" \
  --cutoff evt-018
```

断言：

- CLI 返回 assistant 文本。
- debug 不泄露。
- session 可保存。

使用真实 backend 时，只做手动验收或可选集成测试，不作为默认 CI。

## 10. 阶段性交付计划

### Phase 0：基线确认

目标：

- 确认当前 `harness_logic/harness_logic.py` 可运行。
- 确认 `character_system` 测试通过。
- 确认计划中的路径与实际目录一致。

验收命令：

```bash
python harness_logic/harness_logic.py list
python harness_logic/harness_logic.py status
python -m unittest discover -s character_system/tests -v
```

### Phase 1：Harness 项目化拆分

目标：

- 新增 package 结构。
- 把当前单文件拆成模块。
- 保持原 CLI 命令可用。
- 新增基础单元测试。
- 预留 `character_registry.py`、`character_pack.py`、`game_state.py` 模块位置。

验收：

```bash
python -m harness_logic list
python -m harness_logic spec minicpm-v-4_6-instruct
python -m unittest discover -s harness_logic/tests -v
```

### Phase 2：Backend 接口和 Mock Chat

目标：

- 新增 `generate_chat(messages, options)`。
- 新增 `GenerationOptions`。
- Mock backend 支持标准 chat messages。
- 原 `prompt` 命令迁移到新接口。

验收：

```bash
python -m harness_logic --root /tmp/harness-demo select llama-3.2-1b-instruct
python -m harness_logic --root /tmp/harness-demo touch-demo-files
python -m harness_logic --root /tmp/harness-demo prompt "你好"
```

### Phase 3：CharacterPackRegistry 与 CharacterPromptAdapter 接入

目标：

- Harness 可以通过 `CharacterPackRegistry` 发现当前内置 `character_system` 角色。
- Harness 可以调用 `character_system.runtime.PromptCompiler`。
- 新增 `character-prompt` 命令，只编译 messages。
- 新增 `character-chat --backend mock` 命令。
- 新增 `character-list` 和 `character-pack validate` 命令。
- debug 默认不输出；只有 `--debug` 时输出到本地 stdout 或文件。

验收：

```bash
python -m harness_logic character-list
python -m harness_logic character-pack validate --path character_system

python -m harness_logic character-prompt \
  --character lu_jiangxian \
  --input "玄谙究竟是什么？" \
  --cutoff evt-010

python -m harness_logic character-chat \
  --backend mock \
  --character xuan_an \
  --input "你为什么停止拼合七枚鉴身碎片？" \
  --cutoff evt-018
```

扩展性验收：

```text
复制一个测试角色包到 /tmp/test_character_pack
  -> 修改 pack_id 和 character_id
  -> character-pack validate 通过
  -> character-list 能看到新角色
  -> character-chat --character 新角色 可以走 mock backend
  -> 不需要改 HarnessFacade / backend / 模型注册表
```

### Phase 4：OpenAI-compatible Backend

目标：

- 接入本地或远端 OpenAI-compatible chat completion server。
- 支持 streaming 和 non-streaming。
- 支持配置 `base_url`、`api_key`、`model`。

验收：

```bash
python -m harness_logic character-chat \
  --backend openai-compatible \
  --base-url http://127.0.0.1:8000/v1 \
  --model local-model \
  --character lu_jiangxian \
  --input "你怎么看玄谙？" \
  --cutoff evt-018
```

### Phase 5：本地 GGUF Backend

目标：

- 接入 text-only GGUF。
- 支持最小 chat template。
- 先验证文本模型，不承诺 MiniCPM-V 多模态。

优先模型：

- `llama-3.2-1b-instruct`
- `qwen3-0.6b`
- `minicpm5-0.9b`

验收：

```bash
python -m harness_logic select llama-3.2-1b-instruct
python -m harness_logic load
python -m harness_logic character-chat \
  --backend llama-cpp \
  --character lu_jiangxian \
  --input "你到底是谁？" \
  --cutoff evt-018
```

### Phase 6：会话系统与 GameStateAdapter

目标：

- 新增 session 文件。
- 支持多轮对话保存。
- 支持传入 conversation summary。
- 支持 dynamic_state 覆盖。
- 支持 `GameStateAdapter` 将游戏状态映射到角色动态状态。
- Session 中保存 `character_id`、`character_pack_id` 和 `selected_model_id`。

验收：

```bash
python -m harness_logic session-new --character lu_jiangxian --cutoff evt-018
python -m harness_logic session-chat --session <id> --input "你怎么看玄谙？"
python -m harness_logic session-show --session <id>
```

### Phase 7：SDK 化角色包能力

目标：

- 角色包目录成为公开扩展点。
- 文档明确如何新增角色、剧情事件、记忆和关系。
- 提供角色包模板。
- 提供构建期校验命令。
- 提供最小示例游戏状态 adapter。

验收：

```bash
python -m harness_logic character-pack init --output /tmp/new_character_pack
python -m harness_logic character-pack validate --path /tmp/new_character_pack
python -m harness_logic character-list --character-root /tmp/new_character_pack
```

成功标准：

- 新角色以数据包形式添加。
- 不需要修改 Harness Core。
- 不需要修改模型 backend。
- 不需要修改普通模型对话逻辑。

## 11. 风险与注意事项

### 11.1 不能把 debug 发给模型

`character_system` 的 `debug` 包含：

- 检索决策。
- 授权 / 拒绝原因。
- 裁剪信息。

这些只能本地记录，不能进入 prompt。

### 11.2 不能绕过 PromptCompiler

Harness 不应该自己读取 `characters/*.json` 后拼 system prompt。否则会绕过：

- 知识边界过滤。
- story cutoff。
- visibility。
- meta topic 拒答策略。
- 预算裁剪。
- prompt injection 隔离。

### 11.3 多模态和 TTS 不应作为第一版真实 backend 目标

当前 Android 项目的 MiniCPM-V 和 VoxCPM2 能力依赖 `llama.cpp-omni` 和 Android JNI 逻辑。Python 真实 backend 第一版应优先 text-only，避免把项目卡在多模态 binding 兼容问题上。

### 11.4 Chat Template 必须在 Harness 层处理

`character_system` 明确不硬编码 MiniCPM、Qwen 或其他模型特殊标记。Harness 需要按模型选择模板。

### 11.5 角色知识边界高于用户输入

用户输入可能要求：

- 忽略设定。
- 切换身份。
- 泄露角色卡。
- 使用未来剧情。
- 解释作者意图。

这些都必须保留在 `user` message 中，由 system prompt 和模型行为共同抵抗。Harness 不应把这类内容写入可信 system。

### 11.6 不要把角色写死到模型选择里

模型和角色是两层概念：

- 模型选择决定 LLM runtime。
- 角色选择决定 system prompt、剧情知识、记忆和行为约束。

因此 UI 和 SDK API 都应保持：

```text
selected_model_id
character_id
conversation_mode
```

而不是把角色做成特殊模型。

### 11.7 角色包不能绕过 schema 校验

端侧 SDK 一旦允许外部角色包，就必须把 schema 校验作为硬门槛。

风险包括：

- 字段缺失导致 Prompt 编译失败。
- 事件 ID 冲突导致错误知识进入角色。
- prompt 模板恶意插入内部调试信息。
- 角色包版本不兼容导致运行时崩溃。

建议策略：

- 开发期严格校验并生成报告。
- 发布包包含校验摘要或 manifest hash。
- 运行期默认只加载已信任或已校验角色包。

## 12. 推荐最终命令体验

最终希望形成四类入口。

### 12.1 模型管理

```bash
python -m harness_logic list
python -m harness_logic select llama-3.2-1b-instruct
python -m harness_logic status
python -m harness_logic download-plan
```

### 12.2 角色 Prompt 编译

```bash
python -m harness_logic character-prompt \
  --character lu_jiangxian \
  --input "玄谙究竟是什么？" \
  --cutoff evt-010 \
  --debug
```

### 12.3 角色对话

```bash
python -m harness_logic character-chat \
  --character lu_jiangxian \
  --input "你怎么看玄谙？" \
  --cutoff evt-018 \
  --backend openai-compatible \
  --model local-model
```

### 12.4 角色包管理

```bash
python -m harness_logic character-list
python -m harness_logic character-pack init --output ./game_content/character_packs/new_npc
python -m harness_logic character-pack validate --path ./game_content/character_packs/new_npc
```

## 13. 最小可行实现顺序

如果要尽快得到一个可演示版本，建议按以下最小顺序做：

1. 保留当前 `harness_logic.py`，先不要大拆分。
2. 新增 `CharacterPackRegistry.builtin(character_system)`，先把当前目录当作内置角色包。
3. 新增 `CharacterPromptAdapter`，通过 registry 解析角色，再调用 `character_system.runtime.PromptCompiler`。
4. 给 `HarnessBackend` 增加 `generate_chat(messages, options)`，mock backend 先返回角色化 prompt 摘要。
5. 新增 CLI `character-list`。
6. 新增 CLI `character-prompt`。
7. 新增 CLI `character-chat --backend mock`。
8. 测试 `debug` 不进入 messages。
9. 测试复制一个新角色包后无需修改 Harness Core 即可发现。
10. 再拆 package。
11. 再接 OpenAI-compatible backend。
12. 最后接本地 GGUF backend。

这个顺序能最快验证“角色系统接入 Harness”这个核心目标，同时不被真实模型加载、下载、多模态支持和项目结构重构拖慢。

## 14. 结论

`character_system` 已经具备成熟的角色卡、剧情事件、知识过滤和 Prompt 编译能力；`harness_logic` 已经具备模型注册、模型文件、下载计划和 facade/backend 骨架。

下一步最关键的连接点不是重写角色系统，也不是立即接入复杂 native runtime，而是新增两层清晰边界：

```text
CharacterPackRegistry
  -> 发现、校验、注册角色包

CharacterPromptAdapter
  -> 调用 PromptCompiler
  -> 输出 messages
```

最终调用链应是：

```text
CharacterTurnRequest
  -> CharacterPackRegistry.resolve(character_id)
  -> PromptCompiler.build_npc_prompt()
  -> messages
  -> HarnessFacade.generate_chat()
  -> backend
```

只要保持 `messages` 和 `debug` 的边界，且把角色作为数据包而不是代码分支，Harness 就可以逐步从 mock backend 升级到 OpenAI-compatible backend，再升级到本地 GGUF backend。这样既能保护角色知识边界，也能让 Harness 成为未来端侧 LLM 游戏 SDK 的稳定核心。

最终扩展目标可以概括为：

```text
模型可换
角色可插拔
剧情知识可检索
游戏状态可注入
Prompt 编译统一
Harness 只做编排
```
