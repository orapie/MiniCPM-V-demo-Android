package com.example.minicpm_v_demo.harness.rag

import com.example.minicpm_v_demo.harness.data.HarnessDataPaths

class RagSearchService(
    private val index: VectorIndex,
    private val embeddingModel: EmbeddingModel = HashEmbeddingModel(),
) {
    fun search(query: String, topK: Int = 5): List<SearchResult> {
        return index.search(query, embeddingModel, topK)
    }

    companion object {
        fun fromPaths(paths: HarnessDataPaths): RagSearchService {
            return RagSearchService(VectorIndex.load(paths.ragIndexFile))
        }
    }
}

