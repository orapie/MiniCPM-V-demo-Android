package com.example.minicpm_v_demo.harness.character

import com.example.minicpm_v_demo.harness.data.HarnessDataPaths

class CharacterPromptCompiler(
    private val loader: CharacterJsonLoader,
    private val retriever: KeywordStoryRetriever = KeywordStoryRetriever(),
    private val boundaryFilter: KnowledgeBoundaryFilter = KnowledgeBoundaryFilter(),
    private val memoryRetriever: MemoryRetriever = MemoryRetriever(),
) {
    private val events: List<StoryEvent> by lazy { loader.loadEvents() }
    private val eventsById: Map<String, StoryEvent> by lazy { events.associateBy { it.eventId } }
    private val template: String by lazy { loader.loadPromptTemplate() }

    fun availableCharacters(): List<CharacterCard> = loader.listCharacters()

    fun buildNpcPrompt(
        npcId: String,
        userInput: String,
        runtimeContext: RuntimeContext = RuntimeContext(),
    ): CompiledCharacterPrompt {
        require(userInput.isNotBlank()) { "userInput must not be empty" }
        require(runtimeContext.maxChars >= 400) { "maxChars must be at least 400" }
        val npc = loader.loadCharacter(npcId)
        val cutoff = runtimeContext.storyCutoff ?: npc.knowledgeScope.storyCutoff
        require(eventsById.containsKey(cutoff)) { "unknown story cutoff: $cutoff" }

        val candidates = retriever.retrieve(userInput, events, limit = maxOf(runtimeContext.topK * 2, 12))
        val (authorizedAll, decisions) = boundaryFilter.filter(candidates, npc, cutoff, events, userInput)
        val authorized = authorizedAll.take(runtimeContext.topK)
        val memories = memoryRetriever.retrieve(npc, authorized, events, cutoff, limit = 3)
        val memoryIds = memories.map { it.event.eventId }.toSet()
        val factCandidates = authorized.filter { it.event.eventId !in memoryIds }
        val relationships = selectRelationships(npc, userInput)
        val dynamicState = runtimeContext.dynamicState ?: npc.dynamicState

        val mandatory = linkedMapOf(
            "global_summary" to compileGlobalSummary(npc, cutoff),
            "core_personality" to compileCorePersonality(npc),
            "story_cutoff" to formatCutoff(cutoff),
            "dynamic_state" to compileDynamicState(dynamicState),
            "relevant_relationships" to "无。",
            "authorized_story_facts" to "本轮没有可授权且相关的剧情事实；未知时不要补全。",
            "retrieved_memories" to "无。",
            "conversation_summary" to runtimeContext.conversationSummary.trim().take(160).ifBlank { "无。" },
        )

        var content = render(mandatory)
        val optionalItems = mutableListOf<PromptCandidate>()
        relationships.forEach { relation ->
            optionalItems += PromptCandidate(
                section = "relevant_relationships",
                id = relation.targetName,
                text = "- ${relation.targetName}｜${relation.relationshipType}｜${relation.attitude}",
                priority = 2.0,
            )
        }
        factCandidates.forEach { item ->
            optionalItems += PromptCandidate(
                section = "authorized_story_facts",
                id = item.event.eventId,
                text = formatFact(item, npcId),
                priority = item.score + item.event.importance,
            )
        }
        memories.forEach { item ->
            optionalItems += PromptCandidate(
                section = "retrieved_memories",
                id = item.event.eventId,
                text = formatMemory(item),
                priority = item.score + 0.5,
            )
        }
        optionalItems.sortByDescending { it.priority }

        val selected = mutableListOf<SelectedPromptItem>()
        val dropped = mutableListOf<DroppedPromptItem>()
        val sectionLines = mutableMapOf(
            "relevant_relationships" to mutableListOf<String>(),
            "authorized_story_facts" to mutableListOf<String>(),
            "retrieved_memories" to mutableListOf<String>(),
        )
        for (item in optionalItems) {
            val proposedLines = sectionLines.mapValues { it.value.toMutableList() }.toMutableMap()
            proposedLines.getValue(item.section).add(item.text)
            val values = mandatory.toMutableMap()
            proposedLines.forEach { (section, lines) ->
                if (lines.isNotEmpty()) values[section] = lines.joinToString("\n")
            }
            val proposed = render(values)
            if (proposed.length <= runtimeContext.maxChars) {
                sectionLines.clear()
                sectionLines.putAll(proposedLines)
                content = proposed
                selected += SelectedPromptItem(item.section, item.id, round5(item.priority))
            } else {
                dropped += DroppedPromptItem(item.section, item.id, "character_budget")
            }
        }

        val mandatorySize = render(mandatory).length
        return CompiledCharacterPrompt(
            messages = listOf(
                HarnessChatMessage("system", content),
                HarnessChatMessage("user", userInput),
            ),
            debug = CharacterPromptDebug(
                npcId = npcId,
                storyCutoff = cutoff,
                maxChars = runtimeContext.maxChars,
                promptChars = content.length,
                mandatoryChars = mandatorySize,
                budgetExceededByMandatory = mandatorySize > runtimeContext.maxChars,
                selectedItems = selected,
                droppedItems = dropped,
                retrievalDecisions = decisions,
            ),
        )
    }

    private fun render(values: Map<String, String>): String {
        var rendered = template
        for ((key, value) in values) {
            rendered = rendered.replace("{{$key}}", value)
        }
        require(!rendered.contains("{{") && !rendered.contains("}}")) {
            "shared prompt contains an unresolved placeholder"
        }
        return rendered.trim()
    }

    private fun compileGlobalSummary(npc: CharacterCard, cutoff: String): String {
        val identity = npc.identity
        return listOf(
            "身份：我是${identity.name}（${identity.aliases.firstOrNull() ?: "无别名"}）。",
            "位置：${identity.worldviewPosition.take(48)}",
            "背景：" + identity.background.takeJoined(limit = 1, itemChars = 48),
            "目标：" + identity.coreMotivations.takeJoined(limit = 1, itemChars = 48),
            "当前剧情阶段：${formatCutoff(cutoff)}",
        ).joinToString("\n")
    }

    private fun compileCorePersonality(npc: CharacterCard): String {
        val identity = npc.identity
        return listOf(
            "价值观：" + identity.values.takeJoined(limit = 1, itemChars = 42),
            "表达：" + identity.speechStyle.takeJoined(limit = 1, itemChars = 42),
            "约束：" + identity.hardConstraints.takeJoined(limit = 1, itemChars = 56),
        ).joinToString("\n")
    }

    private fun compileDynamicState(state: DynamicState): String {
        val emotion = state.emotion
        return listOf(
            "地点：${state.scene.take(28)}",
            "任务：${state.questState.take(36)}",
            "目标：${state.currentGoal.take(36)}",
            "情绪：${emotion.label}；触发：${emotion.trigger.take(32)}",
        ).joinToString("\n")
    }

    private fun formatCutoff(cutoff: String): String {
        val event = eventsById.getValue(cutoff)
        return "$cutoff（叙事序号 ${event.timeIndex}）"
    }

    private fun formatFact(item: RetrievedEvent, npcId: String): String {
        val event = item.event
        val source = SourceLabels.getValue(event.knowledgeByCharacter.getValue(npcId).source)
        val certainty = if (event.confidence < 0.9) "可能/推断：" else ""
        return "- $certainty${event.fact}〔$source，可信度 ${"%.2f".format(event.confidence)}〕"
    }

    private fun formatMemory(item: RetrievedMemory): String {
        val source = SourceLabels.getValue(item.memory.source)
        val certainty = if (item.memory.source == "inferred") "我推断：" else ""
        return "- $certainty${item.event.fact}〔$source，记忆可信度 ${"%.2f".format(item.memory.confidence)}〕"
    }

    private fun selectRelationships(npc: CharacterCard, query: String): List<CharacterRelationship> {
        val selected = npc.relationships.filter { it.targetName in query }
        if (selected.isNotEmpty()) return selected
        return if (listOf("关系", "怎么看", "他", "祂", "他们").any { it in query }) {
            npc.relationships.take(2)
        } else {
            emptyList()
        }
    }

    private fun round5(value: Double): Double = kotlin.math.round(value * 100000.0) / 100000.0

    private data class PromptCandidate(
        val section: String,
        val id: String,
        val text: String,
        val priority: Double,
    )

    companion object {
        private val SourceLabels = mapOf(
            "direct" to "亲历",
            "witnessed" to "目击",
            "reported" to "听说",
            "inferred" to "推断",
        )

        private fun List<String>.takeJoined(limit: Int, itemChars: Int): String =
            take(limit)
                .joinToString("；") { it.take(itemChars) }
                .ifBlank { "无" }

        fun fromPaths(paths: HarnessDataPaths): CharacterPromptCompiler {
            return CharacterPromptCompiler(
                CharacterJsonLoader(
                    charactersDir = paths.charactersDir,
                    storyEventsFile = paths.storyEventsFile,
                    promptTemplateFile = java.io.File(paths.promptsDir, "roleplay_system.prompt"),
                ),
            )
        }
    }
}
