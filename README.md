# MiniCPM-V-demo-Android

`MiniCPM-V-demo-Android` 是一个基于 Android 的本地大模型演示项目，聚焦在端侧模型加载、推理与交互体验。项目当前以 `MiniCPM-V` 系列能力为主，结合 Kotlin、JNI 与 Native 推理后端，提供文本、多模态图片理解、部分视频理解与 TTS 相关能力的验证入口。

## 项目概览

- 项目类型：单模块 Android Application
- 应用包名：`com.example.minicpm_v_demo`
- 当前版本：`2.3`
- 最低系统版本：Android 7.0 (`minSdk 24`)
- 目标系统版本：Android 16 (`targetSdk 36`)
- 支持 ABI：`arm64-v8a`
- 主要技术栈：Kotlin、Android ViewBinding、JNI、CMake、llama.cpp-omni

## 主要能力

- 本地文本模型对话
- 多模态图片理解
- `MiniCPM-V-4.6` 视频理解路径
- 模型下载、切换、加载与删除
- TTS 页面与语音相关能力入口

当前代码中已经包含多类模型接入定义，核心模型信息集中在 [app/src/main/java/com/example/minicpm_v_demo/ModelInfo.kt](app/src/main/java/com/example/minicpm_v_demo/ModelInfo.kt)。

## 项目结构

```text
.
├── app/
│   ├── src/main/java/com/example/minicpm_v_demo/
│   │   ├── MainActivity.kt
│   │   ├── ModelManagerActivity.kt
│   │   ├── TtsActivity.kt
│   │   ├── LlamaEngine.kt
│   │   ├── ModelDownloadService.kt
│   │   └── harness/
│   ├── src/main/cpp/
│   │   ├── llama_jni.cpp
│   │   ├── omni_jni.cpp
│   │   └── CMakeLists.txt
│   └── src/main/res/
├── docs/
├── gradle/
└── settings.gradle.kts
```

可以按下面的分层理解这个项目：

- UI 层：`MainActivity`、`ModelManagerActivity`、`TtsActivity`
- 编排层：`harness/` 下的统一入口与适配逻辑
- 运行时层：`LlamaEngine.kt`
- Native 层：`app/src/main/cpp/`

## 构建与运行

### 基本要求

- Android Studio
- Android SDK / NDK
- CMake `4.1.2`
- 可运行 `arm64` 镜像的真机或模拟器

由于当前 APK 仅打包 `arm64-v8a`，使用 `x86/x86_64` 模拟器通常无法直接验证本项目。

### 调试构建

在项目根目录执行：

```bash
./gradlew :app:assembleDebug
```

默认调试 APK 输出路径：

```text
app/build/outputs/apk/debug/app-debug.apk
```

## 关键文件

- [app/build.gradle.kts](app/build.gradle.kts)：Android 构建配置、ABI、NDK、CMake 与依赖声明
- [app/src/main/AndroidManifest.xml](app/src/main/AndroidManifest.xml)：应用组件、权限与前台下载服务配置
- [app/src/main/java/com/example/minicpm_v_demo/LlamaEngine.kt](app/src/main/java/com/example/minicpm_v_demo/LlamaEngine.kt)：模型加载、推理、预填充与运行时主逻辑
- [app/src/main/java/com/example/minicpm_v_demo/ModelDownloadService.kt](app/src/main/java/com/example/minicpm_v_demo/ModelDownloadService.kt)：后台模型下载服务
- [app/src/main/cpp/llama_jni.cpp](app/src/main/cpp/llama_jni.cpp)：JNI 桥接与 Native 推理接入

## 文档索引

仓库内已有更详细的设计与接入文档，建议按需阅读：

- [docs/Harness_Quickstart_Guide.md](docs/Harness_Quickstart_Guide.md)：项目整体结构、能力边界与 Harness 快速认知
- [docs/Harness/Inte_Harness.md](docs/Harness/Inte_Harness.md)：Harness 接入方案
- [docs/Harness/Lightweight_Model_SDK_Roadmap.md](docs/Harness/Lightweight_Model_SDK_Roadmap.md)：轻量模型 SDK 化演进路线
- [docs/Harness/Mini_Change.md](docs/Harness/Mini_Change.md)：相关变更说明

## 说明

这个 README 只覆盖仓库入口所需的基础信息。如果后续你希望把它扩展成更完整的使用文档，可以继续补充：

- 模型下载来源与目录规则
- 真机/模拟器运行步骤
- 常见问题排查
- Harness 与 Native 推理链路说明
