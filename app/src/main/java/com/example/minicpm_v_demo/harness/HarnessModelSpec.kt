package com.example.minicpm_v_demo.harness

import com.example.minicpm_v_demo.ModelInfo

enum class HarnessCapability {
    TEXT,
    VISION,
    VIDEO,
    TTS
}

data class HarnessArtifact(
    val id: String,
    val fileName: String,
    val required: Boolean = true
)

data class HarnessModelSpec(
    val id: String,
    val displayName: String,
    val capabilities: Set<HarnessCapability>,
    val artifacts: List<HarnessArtifact>
)

fun ModelInfo.toHarnessSpec(): HarnessModelSpec {
    val capabilities = linkedSetOf(HarnessCapability.TEXT)
    if (mmprojFileName != null) {
        capabilities += HarnessCapability.VISION
        if (id == "minicpm-v-4_6-instruct") {
            capabilities += HarnessCapability.VIDEO
        }
    }
    if (isTts) {
        capabilities += HarnessCapability.TTS
    }

    val artifacts = buildList {
        add(HarnessArtifact(id = "llm", fileName = ggufFileName))
        mmprojFileName?.let {
            add(HarnessArtifact(id = "vision_projector", fileName = it))
        }
        acousticFileName?.let {
            add(HarnessArtifact(id = "acoustic", fileName = it))
        }
    }

    return HarnessModelSpec(
        id = id,
        displayName = displayName,
        capabilities = capabilities,
        artifacts = artifacts
    )
}
