# Harness 最小改动接入记录

## 本次修改目标

在不重写现有 `LlamaEngine + JNI + llama.cpp-omni` 链路的前提下，以最小改动方式把 Harness 接入当前项目，使其先承担统一编排层/适配层角色。

## 实际修改内容

### 1. 新增 Harness 抽象层

新增目录：

- `app/src/main/java/com/example/minicpm_v_demo/harness/`

新增文件：

- `HarnessModelSpec.kt`
  - 定义最小模型抽象：`HarnessModelSpec`、`HarnessArtifact`、`HarnessCapability`
  - 提供 `ModelInfo.toHarnessSpec()` 映射
- `HarnessBackend.kt`
  - 定义最小后端接口
- `LlamaBackendAdapter.kt`
  - 把现有 `LlamaEngine` 封装为 Harness backend
- `HarnessFacade.kt`
  - 对 Activity 提供统一入口

### 2. Activity 层切换到 HarnessFacade

修改文件：

- `app/src/main/java/com/example/minicpm_v_demo/MainActivity.kt`
- `app/src/main/java/com/example/minicpm_v_demo/ModelManagerActivity.kt`

改动方式：

- 原先直接依赖 `LlamaEngine` 的主流程，改为依赖 `HarnessFacade`
- 保留现有 `LlamaState` 状态流，避免一次性大改 UI 状态机
- 模型加载、卸载、会话清理、图片预填充、视频预填充、文本生成、模型删除、模型切换等动作，统一从 Harness 层进入

### 3. 文档结构调整

新增目录：

- `docs/Harness/`

文档归档：

- `Inte_Harness.md` 已移动到 `docs/Harness/Inte_Harness.md`
- 本文档新增为 `docs/Harness/Mini_Change.md`

## 本次刻意没有修改的部分

为了满足“最小改动”原则，本次没有改以下部分：

- `LlamaEngine.kt` 的核心实现逻辑
- `ModelDownloadService.kt` 的前台服务实现
- `llama_jni.cpp`
- `CMakeLists.txt`
- `TtsActivity.kt` / `TtsEngine.kt`

说明：

- TTS 仍然沿用当前项目的原路径
- 下载服务仍然复用原有服务，只是调用入口可由 HarnessFacade 统一转发
- Native 推理链路不变，因此本次风险主要集中在 Kotlin 层边界调整

## 最终效果

### 代码结构上的效果

- UI 层不再直接依赖 `LlamaEngine` 作为主调用入口
- 当前本地 llama backend 被包装成 `LlamaBackendAdapter`
- 项目里已经形成最小 Harness 外壳，后续可继续接入其他 backend，而不需要先改 Activity

### App 使用层面的体现

用户界面本身不会新增一个叫 “Harness” 的功能入口，但会有这些结构性变化：

- 聊天页和模型管理页开始共享同一层编排入口
- 模型切换、加载、会话生成、图片预填充等动作不再各自直连底层实现
- 后续如果替换 backend 或增加新模型运行时，优先改 Harness 层，不必先改页面逻辑

### 当前 Harness 已覆盖的最小能力

- 统一获取当前模型与模型能力
- 统一判断模型文件是否完整
- 统一加载/卸载当前模型
- 统一发起文本生成
- 统一清理上下文
- 统一图片/视频预填充
- 统一删除当前模型文件
- 统一启动模型下载服务

## 验证结果

已执行：

```bash
./gradlew :app:compileDebugKotlin
```

结果：

- 编译成功

备注：

- 首次在受限环境下执行时，因为 `~/.gradle` 锁文件访问受限失败
- 在授权访问 `~/.gradle` 后，编译检查通过

## 结论

这次修改完成的是“最小 Harness 接入”，不是“完整 SDK 化重构”。

当前项目已经具备：

- Harness 抽象入口
- Llama backend 适配器
- Activity 对 Harness 的主链路切换

后续如果继续演进，建议下一步优先做：

1. 把 `ModelDownloadService` 的具体下载逻辑进一步抽到 Harness 层
2. 把 `LlamaEngine` 中的模型存储、下载、运行时职责继续拆分
3. 把 TTS 路径也逐步并入 Harness 能力模型
