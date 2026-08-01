#!/usr/bin/env python3
"""
Standalone Python extraction of this project's Android harness layer.

The original project runs through Kotlin + Android + JNI:
    Activity -> HarnessFacade -> LlamaModelStore / LlamaBackendAdapter
        -> LlamaEngine -> native llama.cpp-omni

This script preserves the harness logic that can run outside Android:
    - model metadata and ModelInfo -> HarnessModelSpec mapping
    - model registry lookup
    - selected-model state
    - model artifact path, availability, deletion, and legacy layout migration
    - facade/backend orchestration with a runnable mock backend
    - download-source planning for HuggingFace, ModelScope, and direct URLs

It intentionally does not call the Android JNI runtime or download multi-GB
model files by default. Use it as a runnable, inspectable harness model of the
project's current app-side orchestration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Set


DEFAULT_PREDICT_LENGTH = 1024
MODEL_SUBDIR = "models"
MIN_IMAGE_SLICE = 1
MAX_IMAGE_SLICE = 9
DEFAULT_IMAGE_SLICE = MAX_IMAGE_SLICE


class LlamaState(str, Enum):
    UNINITIALIZED = "Uninitialized"
    INITIALIZING = "Initializing"
    INITIALIZED = "Initialized"
    LOADING_MODEL = "LoadingModel"
    MODEL_READY = "ModelReady"
    PROCESSING_SYSTEM_PROMPT = "ProcessingSystemPrompt"
    PREFILLING_IMAGE = "PrefillingImage"
    PROCESSING_USER_PROMPT = "ProcessingUserPrompt"
    GENERATING = "Generating"
    UNLOADING_MODEL = "UnloadingModel"
    ERROR = "Error"


class HarnessCapability(str, Enum):
    TEXT = "TEXT"
    VISION = "VISION"
    VIDEO = "VIDEO"
    TTS = "TTS"


class HarnessModelFamily(str, Enum):
    MINICPM_VISION = "MINICPM_VISION"
    MINICPM_TEXT = "MINICPM_TEXT"
    VOXCPM2 = "VOXCPM2"
    LLAMA = "LLAMA"
    QWEN = "QWEN"
    OTHER = "OTHER"


class HarnessDownloadSourceType(str, Enum):
    HUGGING_FACE = "HUGGING_FACE"
    MODELSCOPE = "MODELSCOPE"
    DIRECT = "DIRECT"


@dataclass(frozen=True)
class ModelInfo:
    id: str
    display_name: str
    description_res_name: str
    gguf_file_name: str
    mmproj_file_name: Optional[str] = None
    acoustic_file_name: Optional[str] = None
    hf_repo: Optional[str] = None
    ms_repo: Optional[str] = None
    hf_branch: str = "main"
    ms_branch: str = "master"
    gguf_remote_name: Optional[str] = None
    mmproj_remote_name: Optional[str] = None
    acoustic_remote_name: Optional[str] = None
    direct_gguf_url: Optional[str] = None
    direct_mmproj_url: Optional[str] = None
    direct_acoustic_url: Optional[str] = None
    gguf_md5: Optional[str] = None
    mmproj_md5: Optional[str] = None
    acoustic_md5: Optional[str] = None

    @property
    def is_text_only(self) -> bool:
        return self.mmproj_file_name is None and self.acoustic_file_name is None

    @property
    def is_tts(self) -> bool:
        return self.acoustic_file_name is not None

    @property
    def gguf_remote_path(self) -> str:
        return self.gguf_remote_name or self.gguf_file_name

    @property
    def mmproj_remote_path(self) -> Optional[str]:
        if self.mmproj_file_name is None:
            return None
        return self.mmproj_remote_name or self.mmproj_file_name

    @property
    def acoustic_remote_path(self) -> Optional[str]:
        if self.acoustic_file_name is None:
            return None
        return self.acoustic_remote_name or self.acoustic_file_name

    @property
    def has_direct_urls(self) -> bool:
        if self.is_text_only:
            return bool(self.direct_gguf_url)
        if self.is_tts:
            return bool(self.direct_gguf_url and self.direct_acoustic_url)
        return bool(self.direct_gguf_url and self.direct_mmproj_url)

    @property
    def has_hf_ms_sources(self) -> bool:
        return bool(self.hf_repo and self.ms_repo)


@dataclass(frozen=True)
class HarnessArtifact:
    id: str
    file_name: str
    required: bool = True
    remote_path: Optional[str] = None
    md5: Optional[str] = None


@dataclass(frozen=True)
class HarnessDownloadSource:
    artifact_id: str
    type: HarnessDownloadSourceType
    repo: Optional[str] = None
    branch: Optional[str] = None
    remote_path: Optional[str] = None
    url: Optional[str] = None


@dataclass(frozen=True)
class HarnessRuntimeHints:
    default_predict_length: int = DEFAULT_PREDICT_LENGTH
    recommended_threads: int = 4
    default_image_max_slice_nums: Optional[int] = None
    context_size: Optional[int] = None
    supports_system_prompt: bool = True


@dataclass(frozen=True)
class HarnessModelSpec:
    id: str
    display_name: str
    family: HarnessModelFamily
    capabilities: Set[HarnessCapability]
    artifacts: List[HarnessArtifact]
    download_sources: List[HarnessDownloadSource]
    runtime_hints: HarnessRuntimeHints


@dataclass(frozen=True)
class HarnessModelEntry:
    legacy_model_info: ModelInfo
    spec: HarnessModelSpec


@dataclass(frozen=True)
class HarnessModelAvailability:
    model: ModelInfo
    gguf_missing: bool
    support_artifact_missing: bool

    @property
    def complete(self) -> bool:
        return not self.gguf_missing and not self.support_artifact_missing


@dataclass(frozen=True)
class LlamaModelFiles:
    model: ModelInfo
    spec: HarnessModelSpec
    artifact_files: Dict[str, Path]


@dataclass(frozen=True)
class DownloadCandidate:
    artifact_id: str
    file_name: str
    source_label: str
    url: str
    md5: Optional[str] = None


AVAILABLE_MODELS: List[ModelInfo] = [
    ModelInfo(
        id="minicpm-v-4",
        display_name="MiniCPM-V-4 (Q4_K_M)",
        description_res_name="model_desc_v4",
        gguf_file_name="ggml-model-Q4_K_M.gguf",
        mmproj_file_name="mmproj-model-f16.gguf",
        hf_repo="openbmb/MiniCPM-V-4-gguf",
        ms_repo="OpenBMB/MiniCPM-V-4-gguf",
    ),
    ModelInfo(
        id="minicpm-v-4_6-instruct",
        display_name="MiniCPM-V-4.6 (Q4_K_M)",
        description_res_name="model_desc_v46",
        gguf_file_name="MiniCPM-V-4_6-Q4_K_M.gguf",
        mmproj_file_name="mmproj-model-f16.gguf",
        hf_repo="openbmb/MiniCPM-V-4.6-gguf",
        ms_repo="OpenBMB/MiniCPM-V-4.6-gguf",
        gguf_md5="fd778481dd56b6036dd8f9cf7c1519cf",
        mmproj_md5="54aea6e04d752f47309a48f12795a1a3",
    ),
    ModelInfo(
        id="minicpm5-0.9b",
        display_name="MiniCPM5-1B (Q4_K_M)",
        description_res_name="model_desc_minicpm5",
        gguf_file_name="MiniCPM5-1B-Q4_K_M.gguf",
        hf_repo="openbmb/MiniCPM5-1B-GGUF",
        ms_repo="OpenBMB/MiniCPM5-1B-GGUF",
    ),
    ModelInfo(
        id="voxcpm2",
        display_name="VoxCPM2",
        description_res_name="model_desc_voxcpm2",
        gguf_file_name="VoxCPM2-BaseLM-Q4_K_M.gguf",
        acoustic_file_name="VoxCPM2-Acoustic-F16.gguf",
        hf_repo="tc-mb/MiniCPM-V-Apps-gguf",
        direct_gguf_url=(
            "https://huggingface.co/tc-mb/MiniCPM-V-Apps-gguf/resolve/main/"
            "VoxCPM2-BaseLM-Q4_K_M.gguf"
        ),
        direct_acoustic_url=(
            "https://huggingface.co/tc-mb/MiniCPM-V-Apps-gguf/resolve/main/"
            "VoxCPM2-Acoustic-F16.gguf"
        ),
        gguf_md5="d8cd571526464d225187d326caa289be",
        acoustic_md5="0f16229cfffe935102d21433f6969f8b",
    ),
    ModelInfo(
        id="llama-3.2-1b-instruct",
        display_name="Llama 3.2 1B Instruct (Q4_K_M)",
        description_res_name="model_desc_llama32_1b",
        gguf_file_name="Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        direct_gguf_url=(
            "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/"
            "resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
        ),
    ),
    ModelInfo(
        id="qwen3-0.6b",
        display_name="qwen3-0.6b",
        description_res_name="验证模型",
        gguf_file_name="Qwen3.5-0.8B-Q4_K_M.gguf",
        hf_repo="unsloth/Qwen3.5-0.8B-GGUF",
        ms_repo="unsloth/Qwen3.5-0.8B-GGUF",
    ),
]


LEGACY_FILE_RENAMES: Dict[str, List[tuple[str, str]]] = {
    "minicpm-v-4_6-instruct": [
        ("MiniCPM-V4.6-instruct-Q4_K_M.gguf", "MiniCPM-V-4_6-Q4_K_M.gguf"),
        ("minicpmv46-llm-Q4_K_M.gguf", "MiniCPM-V-4_6-Q4_K_M.gguf"),
    ],
    "minicpm5-0.9b": [
        ("MiniCPM5-0.9B-Q4_K_M.gguf", "MiniCPM5-1B-Q4_K_M.gguf"),
    ],
    "voxcpm2": [
        ("VoxCPM2-BaseLM-F16.gguf", "VoxCPM2-BaseLM-Q4_K_M.gguf"),
    ],
}


STALE_MMPROJ_NAMES: Dict[str, List[str]] = {
    "minicpm-v-4_6-instruct": [
        "mmproj-v46-model-f16.gguf",
        "mmproj-model-merger-f16.gguf",
    ],
}


def infer_harness_model_family(model: ModelInfo) -> HarnessModelFamily:
    if model.is_tts:
        return HarnessModelFamily.VOXCPM2
    if model.id.startswith("minicpm-v"):
        return HarnessModelFamily.MINICPM_VISION
    if model.id.startswith("minicpm5"):
        return HarnessModelFamily.MINICPM_TEXT
    if model.id.startswith("llama"):
        return HarnessModelFamily.LLAMA
    if model.id.startswith("qwen"):
        return HarnessModelFamily.QWEN
    return HarnessModelFamily.OTHER


def infer_runtime_hints(model: ModelInfo) -> HarnessRuntimeHints:
    if model.id == "minicpm-v-4_6-instruct":
        return HarnessRuntimeHints(
            default_image_max_slice_nums=DEFAULT_IMAGE_SLICE,
            context_size=8192,
        )
    if model.mmproj_file_name is not None:
        return HarnessRuntimeHints(
            default_image_max_slice_nums=DEFAULT_IMAGE_SLICE,
            context_size=4096,
        )
    return HarnessRuntimeHints(context_size=4096)


def model_to_harness_spec(model: ModelInfo) -> HarnessModelSpec:
    capabilities: Set[HarnessCapability] = {HarnessCapability.TEXT}
    if model.mmproj_file_name is not None:
        capabilities.add(HarnessCapability.VISION)
        if model.id == "minicpm-v-4_6-instruct":
            capabilities.add(HarnessCapability.VIDEO)
    if model.is_tts:
        capabilities.add(HarnessCapability.TTS)

    artifacts = [
        HarnessArtifact(
            id="llm",
            file_name=model.gguf_file_name,
            remote_path=model.gguf_remote_path,
            md5=model.gguf_md5,
        )
    ]
    if model.mmproj_file_name is not None:
        artifacts.append(
            HarnessArtifact(
                id="vision_projector",
                file_name=model.mmproj_file_name,
                remote_path=model.mmproj_remote_path,
                md5=model.mmproj_md5,
            )
        )
    if model.acoustic_file_name is not None:
        artifacts.append(
            HarnessArtifact(
                id="acoustic",
                file_name=model.acoustic_file_name,
                remote_path=model.acoustic_remote_path,
                md5=model.acoustic_md5,
            )
        )

    download_sources: List[HarnessDownloadSource] = []
    if model.hf_repo:
        download_sources.append(
            HarnessDownloadSource(
                artifact_id="llm",
                type=HarnessDownloadSourceType.HUGGING_FACE,
                repo=model.hf_repo,
                branch=model.hf_branch,
                remote_path=model.gguf_remote_path,
            )
        )
        if model.mmproj_remote_path:
            download_sources.append(
                HarnessDownloadSource(
                    artifact_id="vision_projector",
                    type=HarnessDownloadSourceType.HUGGING_FACE,
                    repo=model.hf_repo,
                    branch=model.hf_branch,
                    remote_path=model.mmproj_remote_path,
                )
            )
        if model.acoustic_remote_path:
            download_sources.append(
                HarnessDownloadSource(
                    artifact_id="acoustic",
                    type=HarnessDownloadSourceType.HUGGING_FACE,
                    repo=model.hf_repo,
                    branch=model.hf_branch,
                    remote_path=model.acoustic_remote_path,
                )
            )
    if model.ms_repo:
        download_sources.append(
            HarnessDownloadSource(
                artifact_id="llm",
                type=HarnessDownloadSourceType.MODELSCOPE,
                repo=model.ms_repo,
                branch=model.ms_branch,
                remote_path=model.gguf_remote_path,
            )
        )
        if model.mmproj_remote_path:
            download_sources.append(
                HarnessDownloadSource(
                    artifact_id="vision_projector",
                    type=HarnessDownloadSourceType.MODELSCOPE,
                    repo=model.ms_repo,
                    branch=model.ms_branch,
                    remote_path=model.mmproj_remote_path,
                )
            )
        if model.acoustic_remote_path:
            download_sources.append(
                HarnessDownloadSource(
                    artifact_id="acoustic",
                    type=HarnessDownloadSourceType.MODELSCOPE,
                    repo=model.ms_repo,
                    branch=model.ms_branch,
                    remote_path=model.acoustic_remote_path,
                )
            )
    if model.direct_gguf_url:
        download_sources.append(
            HarnessDownloadSource(
                artifact_id="llm",
                type=HarnessDownloadSourceType.DIRECT,
                url=model.direct_gguf_url,
            )
        )
    if model.direct_mmproj_url:
        download_sources.append(
            HarnessDownloadSource(
                artifact_id="vision_projector",
                type=HarnessDownloadSourceType.DIRECT,
                url=model.direct_mmproj_url,
            )
        )
    if model.direct_acoustic_url:
        download_sources.append(
            HarnessDownloadSource(
                artifact_id="acoustic",
                type=HarnessDownloadSourceType.DIRECT,
                url=model.direct_acoustic_url,
            )
        )

    return HarnessModelSpec(
        id=model.id,
        display_name=model.display_name,
        family=infer_harness_model_family(model),
        capabilities=capabilities,
        artifacts=artifacts,
        download_sources=download_sources,
        runtime_hints=infer_runtime_hints(model),
    )


class HarnessModelRegistry:
    entries: List[HarnessModelEntry] = [
        HarnessModelEntry(model, model_to_harness_spec(model)) for model in AVAILABLE_MODELS
    ]
    default_entry: HarnessModelEntry = entries[0]

    @classmethod
    def available_entries(cls) -> List[HarnessModelEntry]:
        return list(cls.entries)

    @classmethod
    def available_model_infos(cls) -> List[ModelInfo]:
        return [entry.legacy_model_info for entry in cls.entries]

    @classmethod
    def available_specs(cls) -> List[HarnessModelSpec]:
        return [entry.spec for entry in cls.entries]

    @classmethod
    def find_entry(cls, model_id: str) -> Optional[HarnessModelEntry]:
        return next((entry for entry in cls.entries if entry.spec.id == model_id), None)

    @classmethod
    def find_legacy_model(cls, model_id: str) -> Optional[ModelInfo]:
        entry = cls.find_entry(model_id)
        return entry.legacy_model_info if entry else None

    @classmethod
    def find_spec(cls, model_id: str) -> Optional[HarnessModelSpec]:
        entry = cls.find_entry(model_id)
        return entry.spec if entry else None


class JsonPreferenceStore:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> Dict[str, object]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def write(self, data: Dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def get(self, key: str, default: object) -> object:
        return self.read().get(key, default)

    def set(self, key: str, value: object) -> None:
        data = self.read()
        data[key] = value
        self.write(data)


class LlamaModelStore:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.model_root = root_dir / MODEL_SUBDIR
        self.prefs = JsonPreferenceStore(root_dir / ".harness_state.json")

    def migrate_legacy_layout_if_needed(self) -> List[str]:
        events: List[str] = []
        if not self.model_root.exists():
            return events

        for model in HarnessModelRegistry.available_model_infos():
            target_dir = self.model_dir_for(model)
            flat_files = [self.model_root / model.gguf_file_name]
            if model.mmproj_file_name:
                flat_files.append(self.model_root / model.mmproj_file_name)

            if any(path.exists() for path in flat_files):
                target_dir.mkdir(parents=True, exist_ok=True)
                for src in flat_files:
                    dst = target_dir / src.name
                    if src.exists() and not dst.exists():
                        src.rename(dst)
                        events.append(f"migrated {src.name} -> {model.id}/{dst.name}")

            for old_name, new_name in LEGACY_FILE_RENAMES.get(model.id, []):
                src = target_dir / old_name
                dst = target_dir / new_name
                if src.exists() and not dst.exists():
                    src.rename(dst)
                    events.append(f"renamed {model.id}/{old_name} -> {new_name}")

            for name in STALE_MMPROJ_NAMES.get(model.id, []):
                for stale in [target_dir / name, target_dir / f"{name}.tmp"]:
                    if stale.exists():
                        stale.unlink()
                        events.append(f"purged stale {model.id}/{stale.name}")

        return events

    def get_selected_model(self) -> ModelInfo:
        default_id = HarnessModelRegistry.default_entry.spec.id
        model_id = str(self.prefs.get("selected_model_id", default_id))
        return HarnessModelRegistry.find_legacy_model(model_id) or HarnessModelRegistry.default_entry.legacy_model_info

    def set_selected_model(self, model_id: str) -> None:
        if HarnessModelRegistry.find_entry(model_id) is None:
            known = ", ".join(model.id for model in HarnessModelRegistry.available_model_infos())
            raise ValueError(f"Unknown model id: {model_id}. Known ids: {known}")
        self.prefs.set("selected_model_id", model_id)

    def mark_model_switched(self) -> None:
        self.prefs.set("model_switched", True)

    def consume_model_switched(self) -> bool:
        switched = bool(self.prefs.get("model_switched", False))
        if switched:
            self.prefs.set("model_switched", False)
        return switched

    def get_image_max_slice_nums(self) -> int:
        value = int(self.prefs.get("image_max_slice_nums", DEFAULT_IMAGE_SLICE))
        return max(MIN_IMAGE_SLICE, min(MAX_IMAGE_SLICE, value))

    def set_image_max_slice_nums(self, n: int) -> None:
        clamped = max(MIN_IMAGE_SLICE, min(MAX_IMAGE_SLICE, n))
        self.prefs.set("image_max_slice_nums", clamped)

    def model_dir_for(self, model: ModelInfo) -> Path:
        return self.model_root / model.id

    def get_selected_model_spec(self) -> HarnessModelSpec:
        model = self.get_selected_model()
        return HarnessModelRegistry.find_spec(model.id) or HarnessModelRegistry.default_entry.spec

    def get_selected_model_files(self) -> LlamaModelFiles:
        model = self.get_selected_model()
        spec = self.get_selected_model_spec()
        model_dir = self.model_dir_for(model)
        artifact_files: Dict[str, Path] = {"llm": model_dir / model.gguf_file_name}
        if model.mmproj_file_name:
            artifact_files["vision_projector"] = model_dir / model.mmproj_file_name
        if model.acoustic_file_name:
            artifact_files["acoustic"] = model_dir / model.acoustic_file_name
        return LlamaModelFiles(model=model, spec=spec, artifact_files=artifact_files)

    def get_selected_model_availability(self) -> HarnessModelAvailability:
        files = self.get_selected_model_files()
        gguf_missing = not files.artifact_files["llm"].exists()
        support_artifact_missing = any(
            not files.artifact_files.get(artifact.id, Path()).exists()
            for artifact in files.spec.artifacts
            if artifact.required and artifact.id != "llm"
        )
        return HarnessModelAvailability(
            model=files.model,
            gguf_missing=gguf_missing,
            support_artifact_missing=support_artifact_missing,
        )

    def is_selected_model_downloaded(self) -> bool:
        files = self.get_selected_model_files()
        return all(
            files.artifact_files.get(artifact.id, Path()).exists()
            for artifact in files.spec.artifacts
            if artifact.required
        )

    def selected_model_artifact_names(self) -> List[str]:
        return [artifact.file_name for artifact in self.get_selected_model_spec().artifacts]

    def delete_selected_model_files(self) -> bool:
        files = self.get_selected_model_files()
        deleted = False
        for path in files.artifact_files.values():
            if path.exists():
                path.unlink()
                deleted = True
        return deleted


class HarnessBackend:
    def __init__(self):
        self.state = LlamaState.INITIALIZED
        self.loaded_model_path: Optional[Path] = None
        self.loaded_mmproj_path: Optional[Path] = None
        self.image_max_slice_nums = DEFAULT_IMAGE_SLICE
        self._cancelled = False

    @property
    def is_vision_supported(self) -> bool:
        return self.loaded_mmproj_path is not None and self.loaded_mmproj_path.exists()

    @property
    def is_video_understanding_supported(self) -> bool:
        return self.is_vision_supported

    def load_model(self, model_path: Path, mmproj_path: Optional[Path] = None) -> None:
        self.state = LlamaState.LOADING_MODEL
        if not model_path.exists():
            self.state = LlamaState.ERROR
            raise FileNotFoundError(f"File not found: {model_path}")
        if mmproj_path is not None and not mmproj_path.exists():
            self.state = LlamaState.ERROR
            raise FileNotFoundError(f"File not found: {mmproj_path}")
        self.loaded_model_path = model_path
        self.loaded_mmproj_path = mmproj_path
        self.state = LlamaState.MODEL_READY

    def unload_model(self) -> None:
        self.state = LlamaState.UNLOADING_MODEL
        self.loaded_model_path = None
        self.loaded_mmproj_path = None
        self.state = LlamaState.INITIALIZED

    def prefill_image(self, image_data: bytes) -> None:
        if not self.is_vision_supported:
            raise RuntimeError("Vision projector is not loaded.")
        self.state = LlamaState.PREFILLING_IMAGE
        if not image_data:
            raise ValueError("image_data is empty")
        self.state = LlamaState.MODEL_READY

    def prefill_video_frames(
        self,
        frames: List[bytes],
        on_progress: Callable[[int, int], None] = lambda _current, _total: None,
    ) -> None:
        if not self.is_video_understanding_supported:
            raise RuntimeError("Video understanding is not supported by the loaded backend.")
        total = len(frames)
        for index, frame in enumerate(frames, start=1):
            if not frame:
                raise ValueError(f"frame {index} is empty")
            on_progress(index, total)

    def clear_context(self) -> None:
        self.state = LlamaState.MODEL_READY if self.loaded_model_path else LlamaState.INITIALIZED

    def set_image_max_slice_nums(self, n: int) -> None:
        self.image_max_slice_nums = max(MIN_IMAGE_SLICE, min(MAX_IMAGE_SLICE, n))

    def send_user_prompt(self, message: str, predict_length: int = DEFAULT_PREDICT_LENGTH) -> Iterator[str]:
        if self.state != LlamaState.MODEL_READY:
            raise RuntimeError(f"Model is not ready. Current state: {self.state.value}")
        self._cancelled = False
        self.state = LlamaState.GENERATING
        response = (
            f"[mock backend] model={self.loaded_model_path.name if self.loaded_model_path else 'none'} "
            f"predict_length={predict_length}: {message}"
        )
        for token in response.split(" "):
            if self._cancelled:
                break
            yield token + " "
        self.state = LlamaState.MODEL_READY

    def cancel_generation(self) -> None:
        self._cancelled = True

    def reset_to_initialized(self) -> None:
        self.loaded_model_path = None
        self.loaded_mmproj_path = None
        self.state = LlamaState.INITIALIZED

    def destroy(self) -> None:
        self.reset_to_initialized()
        self.state = LlamaState.UNINITIALIZED


class LlamaBackendAdapter(HarnessBackend):
    """Runnable stand-in for the Android adapter.

    The Kotlin adapter delegates to LlamaEngine and JNI. Outside Android, this
    subclass preserves adapter shape while using HarnessBackend's mock runtime.
    """


class LlamaDownloadManager:
    def __init__(self, model_store: LlamaModelStore):
        self.model_store = model_store

    def build_download_plan(self, model: Optional[ModelInfo] = None) -> List[DownloadCandidate]:
        model = model or self.model_store.get_selected_model()
        spec = HarnessModelRegistry.find_spec(model.id)
        if spec is None:
            raise ValueError(f"Unknown model: {model.id}")
        md5_by_artifact = {artifact.id: artifact.md5 for artifact in spec.artifacts}
        file_by_artifact = {artifact.id: artifact.file_name for artifact in spec.artifacts}

        candidates: List[DownloadCandidate] = []
        for source in spec.download_sources:
            url = source.url
            label = source.type.value
            if source.type == HarnessDownloadSourceType.HUGGING_FACE:
                url = f"https://huggingface.co/{source.repo}/resolve/{source.branch}/{source.remote_path}"
                label = "HuggingFace"
            elif source.type == HarnessDownloadSourceType.MODELSCOPE:
                url = f"https://www.modelscope.cn/models/{source.repo}/resolve/{source.branch}/{source.remote_path}"
                label = "ModelScope"
            elif source.type == HarnessDownloadSourceType.DIRECT:
                label = "Direct"
            if not url:
                continue
            candidates.append(
                DownloadCandidate(
                    artifact_id=source.artifact_id,
                    file_name=file_by_artifact[source.artifact_id],
                    source_label=label,
                    url=url,
                    md5=md5_by_artifact[source.artifact_id],
                )
            )
        return candidates

    def start_foreground_download(self) -> List[DownloadCandidate]:
        return self.build_download_plan()


class HarnessFacade:
    def __init__(
        self,
        root_dir: Path,
        model_store: Optional[LlamaModelStore] = None,
        backend: Optional[HarnessBackend] = None,
        download_manager: Optional[LlamaDownloadManager] = None,
    ):
        self.model_store = model_store or LlamaModelStore(root_dir)
        self.backend = backend or LlamaBackendAdapter()
        self.download_manager = download_manager or LlamaDownloadManager(self.model_store)

    @property
    def state(self) -> LlamaState:
        return self.backend.state

    @property
    def is_vision_supported(self) -> bool:
        return self.backend.is_vision_supported

    @property
    def is_video_understanding_supported(self) -> bool:
        return self.backend.is_video_understanding_supported

    def migrate_legacy_layout_if_needed(self) -> List[str]:
        return self.model_store.migrate_legacy_layout_if_needed()

    def get_selected_model(self) -> ModelInfo:
        return self.model_store.get_selected_model()

    def get_selected_model_spec(self) -> HarnessModelSpec:
        return self.model_store.get_selected_model_spec()

    def available_models(self) -> List[ModelInfo]:
        return HarnessModelRegistry.available_model_infos()

    def available_model_specs(self) -> List[HarnessModelSpec]:
        return HarnessModelRegistry.available_specs()

    def set_selected_model(self, model_id: str) -> None:
        self.model_store.set_selected_model(model_id)

    def mark_model_switched(self) -> None:
        self.model_store.mark_model_switched()

    def consume_model_switched(self) -> bool:
        return self.model_store.consume_model_switched()

    def is_selected_model_downloaded(self) -> bool:
        return self.model_store.is_selected_model_downloaded()

    def get_image_max_slice_nums(self) -> int:
        return self.model_store.get_image_max_slice_nums()

    def set_image_max_slice_nums(self, n: int) -> None:
        self.model_store.set_image_max_slice_nums(n)
        self.backend.set_image_max_slice_nums(n)

    def get_selected_model_availability(self) -> HarnessModelAvailability:
        return self.model_store.get_selected_model_availability()

    def load_selected_model(self) -> None:
        files = self.model_store.get_selected_model_files()
        llm_file = files.artifact_files.get("llm")
        if llm_file is None:
            raise RuntimeError(f"Missing llm artifact path for {files.model.id}")
        if not llm_file.exists():
            raise FileNotFoundError(f"File not found: {llm_file}")
        mmproj_file = files.artifact_files.get("vision_projector")
        if mmproj_file is not None and not mmproj_file.exists():
            mmproj_file = None
        self.backend.load_model(llm_file, mmproj_file)

    def unload_model(self) -> None:
        self.backend.unload_model()

    def clear_context(self) -> None:
        self.backend.clear_context()

    def prefill_image(self, image_data: bytes) -> None:
        self.backend.prefill_image(image_data)

    def prefill_video_frames(
        self,
        frames: List[bytes],
        on_progress: Callable[[int, int], None] = lambda _current, _total: None,
    ) -> None:
        self.backend.prefill_video_frames(frames, on_progress)

    def send_user_prompt(
        self,
        message: str,
        predict_length: int = DEFAULT_PREDICT_LENGTH,
    ) -> Iterator[str]:
        return self.backend.send_user_prompt(message, predict_length)

    def cancel_generation(self) -> None:
        self.backend.cancel_generation()

    def reset_to_initialized(self) -> None:
        self.backend.reset_to_initialized()

    def destroy(self) -> None:
        self.backend.destroy()

    def start_download_service(self) -> List[DownloadCandidate]:
        return self.download_manager.start_foreground_download()

    def selected_model_artifact_names(self) -> List[str]:
        return self.model_store.selected_model_artifact_names()

    def delete_selected_model_files(self) -> bool:
        return self.model_store.delete_selected_model_files()


def compute_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataclass_to_jsonable(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(dataclass_to_jsonable(item) for item in value)
    if isinstance(value, list):
        return [dataclass_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: dataclass_to_jsonable(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {key: dataclass_to_jsonable(item) for key, item in asdict(value).items()}
    return value


def print_json(value: object) -> None:
    print(json.dumps(dataclass_to_jsonable(value), indent=2, ensure_ascii=False))


def command_list(_facade: HarnessFacade, _args: argparse.Namespace) -> None:
    for spec in HarnessModelRegistry.available_specs():
        capabilities = ",".join(sorted(cap.value for cap in spec.capabilities))
        artifacts = ", ".join(artifact.file_name for artifact in spec.artifacts)
        print(f"{spec.id}\t{spec.display_name}\t{spec.family.value}\t{capabilities}\t{artifacts}")


def command_spec(_facade: HarnessFacade, args: argparse.Namespace) -> None:
    spec = HarnessModelRegistry.find_spec(args.model_id)
    if spec is None:
        raise SystemExit(f"Unknown model id: {args.model_id}")
    print_json(spec)


def command_select(facade: HarnessFacade, args: argparse.Namespace) -> None:
    previous = facade.get_selected_model().id
    facade.set_selected_model(args.model_id)
    if previous != args.model_id:
        facade.mark_model_switched()
    print(f"selected_model_id={facade.get_selected_model().id}")


def command_status(facade: HarnessFacade, _args: argparse.Namespace) -> None:
    files = facade.model_store.get_selected_model_files()
    availability = facade.get_selected_model_availability()
    print(f"selected={files.model.id} ({files.model.display_name})")
    print(f"state={facade.state.value}")
    print(f"image_max_slice_nums={facade.get_image_max_slice_nums()}")
    print(f"downloaded={availability.complete}")
    for artifact in files.spec.artifacts:
        path = files.artifact_files[artifact.id]
        status = "present" if path.exists() else "missing"
        md5_info = ""
        if path.exists() and artifact.md5:
            actual = compute_md5(path)
            md5_info = f" md5={'ok' if actual.lower() == artifact.md5.lower() else actual}"
        print(f"{artifact.id}: {status} {path}{md5_info}")


def command_download_plan(facade: HarnessFacade, _args: argparse.Namespace) -> None:
    plan = facade.start_download_service()
    if not plan:
        print("No download sources configured.")
        return
    grouped: Dict[str, List[DownloadCandidate]] = {}
    for candidate in plan:
        grouped.setdefault(candidate.file_name, []).append(candidate)
    for file_name, candidates in grouped.items():
        labels = "+".join(candidate.source_label for candidate in candidates)
        print(f"{file_name}: race {labels}")
        for candidate in candidates:
            md5 = f" md5={candidate.md5}" if candidate.md5 else ""
            print(f"  - {candidate.source_label}: {candidate.url}{md5}")


def command_migrate(facade: HarnessFacade, _args: argparse.Namespace) -> None:
    events = facade.migrate_legacy_layout_if_needed()
    if not events:
        print("No legacy files changed.")
        return
    for event in events:
        print(event)


def command_touch_demo_files(facade: HarnessFacade, _args: argparse.Namespace) -> None:
    files = facade.model_store.get_selected_model_files()
    for artifact in files.spec.artifacts:
        path = files.artifact_files[artifact.id]
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(f"demo artifact for {files.model.id}/{artifact.id}\n".encode("utf-8"))
            print(f"created {path}")
        else:
            print(f"exists {path}")


def command_load(facade: HarnessFacade, _args: argparse.Namespace) -> None:
    facade.load_selected_model()
    print(f"state={facade.state.value}")
    print(f"vision_supported={facade.is_vision_supported}")


def command_prompt(facade: HarnessFacade, args: argparse.Namespace) -> None:
    if facade.state != LlamaState.MODEL_READY:
        facade.load_selected_model()
    for chunk in facade.send_user_prompt(args.message, args.predict_length):
        print(chunk, end="")
    print()


def command_delete(facade: HarnessFacade, _args: argparse.Namespace) -> None:
    deleted = facade.delete_selected_model_files()
    print(f"deleted={deleted}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Runnable Python extraction of MiniCPM-V-demo-Android harness logic."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Root used for .harness_state.json and models/. Defaults to current directory.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List registered harness models.").set_defaults(func=command_list)

    spec = subparsers.add_parser("spec", help="Print one HarnessModelSpec as JSON.")
    spec.add_argument("model_id")
    spec.set_defaults(func=command_spec)

    select = subparsers.add_parser("select", help="Persist selected model id.")
    select.add_argument("model_id")
    select.set_defaults(func=command_select)

    subparsers.add_parser("status", help="Show selected model, artifact paths, and local availability.").set_defaults(
        func=command_status
    )
    subparsers.add_parser("download-plan", help="Show the selected model's download race candidates.").set_defaults(
        func=command_download_plan
    )
    subparsers.add_parser("migrate", help="Run legacy flat models/ migration and stale file cleanup.").set_defaults(
        func=command_migrate
    )
    subparsers.add_parser(
        "touch-demo-files",
        help="Create tiny placeholder files for the selected model so mock load/prompt can run.",
    ).set_defaults(func=command_touch_demo_files)
    subparsers.add_parser("load", help="Load selected model into the mock backend.").set_defaults(func=command_load)

    prompt = subparsers.add_parser("prompt", help="Run a prompt through the mock backend.")
    prompt.add_argument("message")
    prompt.add_argument("--predict-length", type=int, default=DEFAULT_PREDICT_LENGTH)
    prompt.set_defaults(func=command_prompt)

    subparsers.add_parser("delete", help="Delete selected model artifact files.").set_defaults(func=command_delete)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    facade = HarnessFacade(root)
    args.func(facade, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
