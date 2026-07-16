package com.example.minicpm_v_demo.harness

import com.example.minicpm_v_demo.LlamaState
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow

interface HarnessBackend {
    val state: StateFlow<LlamaState>
    val isVisionSupported: Boolean
    val isVideoUnderstandingSupported: Boolean

    suspend fun loadModel(modelPath: String, mmprojPath: String? = null)
    suspend fun unloadModel()
    suspend fun prefillImage(imageData: ByteArray)
    suspend fun prefillVideoFrames(
        frames: List<ByteArray>,
        onProgress: suspend (current: Int, total: Int) -> Unit = { _, _ -> }
    )
    suspend fun clearContext()
    suspend fun setImageMaxSliceNums(n: Int)
    fun sendUserPrompt(message: String, predictLength: Int): Flow<String>
    fun cancelGeneration()
    fun resetToInitialized()
    fun destroy()
}
