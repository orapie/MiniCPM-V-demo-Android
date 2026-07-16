package com.example.minicpm_v_demo.harness

import android.content.Context
import com.example.minicpm_v_demo.LlamaEngine
import com.example.minicpm_v_demo.LlamaState
import com.example.minicpm_v_demo.ModelDownloadService
import com.example.minicpm_v_demo.ModelInfo
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow
import java.io.File

data class HarnessModelAvailability(
    val model: ModelInfo,
    val ggufMissing: Boolean,
    val supportArtifactMissing: Boolean
)

class HarnessFacade private constructor(
    private val context: Context,
    private val backend: HarnessBackend
) {

    companion object {
        fun getInstance(context: Context): HarnessFacade =
            HarnessFacade(
                context = context.applicationContext,
                backend = LlamaBackendAdapter(context.applicationContext)
            )
    }

    val state: StateFlow<LlamaState>
        get() = backend.state

    val isVisionSupported: Boolean
        get() = backend.isVisionSupported

    val isVideoUnderstandingSupported: Boolean
        get() = backend.isVideoUnderstandingSupported

    fun migrateLegacyLayoutIfNeeded() {
        LlamaEngine.migrateLegacyLayoutIfNeeded(context)
    }

    fun getSelectedModel(): ModelInfo = LlamaEngine.getSelectedModel(context)

    fun getSelectedModelSpec(): HarnessModelSpec = getSelectedModel().toHarnessSpec()

    fun setSelectedModel(modelId: String) {
        LlamaEngine.setSelectedModel(context, modelId)
    }

    fun markModelSwitched() {
        LlamaEngine.markModelSwitched(context)
    }

    fun consumeModelSwitched(): Boolean = LlamaEngine.consumeModelSwitched(context)

    fun isSelectedModelDownloaded(): Boolean = LlamaEngine.modelsExist(context)

    fun getImageMaxSliceNums(): Int = LlamaEngine.getImageMaxSliceNums(context)

    suspend fun setImageMaxSliceNums(n: Int) {
        backend.setImageMaxSliceNums(n)
    }

    fun getSelectedModelAvailability(): HarnessModelAvailability {
        val model = getSelectedModel()
        val modelPath = File(LlamaEngine.modelPath(context))
        val ggufMissing = !modelPath.exists()
        val supportArtifactMissing = when {
            model.isTextOnly -> false
            model.isTts -> {
                val acousticPath = LlamaEngine.acousticPath(context)?.let(::File)
                acousticPath == null || !acousticPath.exists()
            }
            else -> {
                val mmprojPath = LlamaEngine.mmprojPath(context)?.let(::File)
                mmprojPath == null || !mmprojPath.exists()
            }
        }
        return HarnessModelAvailability(model, ggufMissing, supportArtifactMissing)
    }

    suspend fun loadSelectedModel() {
        val modelPath = File(LlamaEngine.modelPath(context))
        require(modelPath.exists()) { "File not found: ${modelPath.absolutePath}" }
        val mmprojArg = LlamaEngine.mmprojPath(context)?.takeIf { File(it).exists() }
        backend.loadModel(modelPath.absolutePath, mmprojArg)
    }

    suspend fun unloadModel() {
        backend.unloadModel()
    }

    suspend fun clearContext() {
        backend.clearContext()
    }

    suspend fun prefillImage(imageData: ByteArray) {
        backend.prefillImage(imageData)
    }

    suspend fun prefillVideoFrames(
        frames: List<ByteArray>,
        onProgress: suspend (current: Int, total: Int) -> Unit = { _, _ -> }
    ) {
        backend.prefillVideoFrames(frames, onProgress)
    }

    fun sendUserPrompt(
        message: String,
        predictLength: Int = LlamaEngine.DEFAULT_PREDICT_LENGTH
    ): Flow<String> = backend.sendUserPrompt(message, predictLength)

    fun cancelGeneration() {
        backend.cancelGeneration()
    }

    fun resetToInitialized() {
        backend.resetToInitialized()
    }

    fun destroy() {
        backend.destroy()
    }

    fun startDownloadService() {
        ModelDownloadService.start(context)
    }

    fun selectedModelArtifactNames(): List<String> =
        getSelectedModelSpec().artifacts.map { it.fileName }

    fun deleteSelectedModelFiles(): Boolean {
        val modelPath = File(LlamaEngine.modelPath(context))
        val mmprojPath = LlamaEngine.mmprojPath(context)?.let(::File)
        val acousticPath = LlamaEngine.acousticPath(context)?.let(::File)

        var deleted = false
        if (modelPath.exists() && modelPath.delete()) deleted = true
        if (mmprojPath?.exists() == true && mmprojPath.delete()) deleted = true
        if (acousticPath?.exists() == true && acousticPath.delete()) deleted = true
        return deleted
    }
}
