package com.example.minicpm_v_demo.harness

import android.content.Context
import com.example.minicpm_v_demo.LlamaEngine
import com.example.minicpm_v_demo.ModelInfo
import java.io.File

data class HarnessModelAvailability(
    val model: ModelInfo,
    val ggufMissing: Boolean,
    val supportArtifactMissing: Boolean
)

data class LlamaModelFiles(
    val model: ModelInfo,
    val ggufFile: File,
    val mmprojFile: File?,
    val acousticFile: File?
)

class LlamaModelStore(private val context: Context) {

    fun migrateLegacyLayoutIfNeeded() {
        LlamaEngine.migrateLegacyLayoutIfNeeded(context)
    }

    fun getSelectedModel(): ModelInfo = LlamaEngine.getSelectedModel(context)

    fun setSelectedModel(modelId: String) {
        LlamaEngine.setSelectedModel(context, modelId)
    }

    fun markModelSwitched() {
        LlamaEngine.markModelSwitched(context)
    }

    fun consumeModelSwitched(): Boolean = LlamaEngine.consumeModelSwitched(context)

    fun getImageMaxSliceNums(): Int = LlamaEngine.getImageMaxSliceNums(context)

    fun getSelectedModelSpec(): HarnessModelSpec = getSelectedModel().toHarnessSpec()

    fun getSelectedModelFiles(): LlamaModelFiles {
        val model = getSelectedModel()
        return LlamaModelFiles(
            model = model,
            ggufFile = File(LlamaEngine.modelPath(context)),
            mmprojFile = LlamaEngine.mmprojPath(context)?.let(::File),
            acousticFile = LlamaEngine.acousticPath(context)?.let(::File)
        )
    }

    fun getSelectedModelAvailability(): HarnessModelAvailability {
        val files = getSelectedModelFiles()
        val supportArtifactMissing = when {
            files.model.isTextOnly -> false
            files.model.isTts -> files.acousticFile?.exists() != true
            else -> files.mmprojFile?.exists() != true
        }
        return HarnessModelAvailability(
            model = files.model,
            ggufMissing = !files.ggufFile.exists(),
            supportArtifactMissing = supportArtifactMissing
        )
    }

    fun isSelectedModelDownloaded(): Boolean {
        val files = getSelectedModelFiles()
        val requiredArtifacts = getSelectedModelSpec().artifacts.filter { it.required }
        return requiredArtifacts.all { artifact ->
            when (artifact.id) {
                "llm" -> files.ggufFile.exists()
                "vision_projector" -> files.mmprojFile?.exists() == true
                "acoustic" -> files.acousticFile?.exists() == true
                else -> false
            }
        }
    }

    fun selectedModelArtifactNames(): List<String> =
        getSelectedModelSpec().artifacts.map { it.fileName }

    fun deleteSelectedModelFiles(): Boolean {
        val files = getSelectedModelFiles()
        var deleted = false
        if (files.ggufFile.exists() && files.ggufFile.delete()) deleted = true
        if (files.mmprojFile?.exists() == true && files.mmprojFile.delete()) deleted = true
        if (files.acousticFile?.exists() == true && files.acousticFile.delete()) deleted = true
        return deleted
    }
}
