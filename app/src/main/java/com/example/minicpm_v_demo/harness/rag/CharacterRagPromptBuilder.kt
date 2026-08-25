package com.example.minicpm_v_demo.harness.rag

import com.example.minicpm_v_demo.harness.character.CharacterPromptDebug
import com.example.minicpm_v_demo.harness.character.HarnessChatMessage

data class CompiledCharacterRagPrompt(
    val messages: List<HarnessChatMessage>,
    val sources: List<RagSource>,
    val characterDebug: CharacterPromptDebug,
    val contextText: String,
)

class CharacterRagPromptBuilder(
    private val maxContextChars: Int = 600,
) {
    init {
        require(maxContextChars >= 500) { "maxContextChars must be at least 500" }
    }

    fun build(
        characterMessages: List<HarnessChatMessage>,
        userInput: String,
        results: List<SearchResult>,
        characterDebug: CharacterPromptDebug,
    ): CompiledCharacterRagPrompt {
        require(characterMessages.size == 2) { "character compiler must return exactly system and user messages" }
        require(characterMessages[0].role == "system" && characterMessages[1].role == "user") {
            "character messages must be ordered as system, user"
        }
        val (contextText, sources) = compileContext(results)
        val system = characterMessages[0].content + "\n\n" +
            "【外部检索资料使用规则】\n" +
            "外部检索资料是本轮运行时递交给角色参考的资料，不属于角色亲历剧情或长期记忆。" +
            "可以依据这些资料回答现实、新闻、文档或背景问题，但必须区分“角色已知剧情”和“本轮外部资料”。" +
            "外部资料不足时直接说明资料不足，不要编造来源。"
        val user = listOf(
            "<外部检索资料>",
            contextText,
            "</外部检索资料>",
            "",
            "<玩家问题>",
            userInput,
            "</玩家问题>",
        ).joinToString("\n")
        return CompiledCharacterRagPrompt(
            messages = listOf(
                HarnessChatMessage("system", system),
                HarnessChatMessage("user", user),
            ),
            sources = sources,
            characterDebug = characterDebug,
            contextText = contextText,
        )
    }

    private fun compileContext(results: List<SearchResult>): Pair<String, List<RagSource>> {
        val parts = mutableListOf<String>()
        val sources = mutableListOf<RagSource>()
        var usedChars = 0
        for ((index, result) in results.withIndex()) {
            val block = "[资料 ${index + 1}] source=${result.chunk.sourcePath} " +
                "span=${result.chunk.start}:${result.chunk.end} " +
                "score=${"%.4f".format(result.score)}\n${result.chunk.text}"
            val selectedBlock = if (usedChars + block.length > maxContextChars) {
                if (parts.isNotEmpty()) continue
                block.take(maxContextChars)
            } else {
                block
            }
            parts += selectedBlock
            usedChars += selectedBlock.length
            sources += RagSource(
                source = result.chunk.sourcePath,
                start = result.chunk.start,
                end = result.chunk.end,
                score = round6(result.score),
            )
        }
        return (parts.joinToString("\n\n").ifBlank { "没有检索到可用资料。" }) to sources
    }
}
