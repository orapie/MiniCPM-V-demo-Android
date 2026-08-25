package com.example.minicpm_v_demo.harness.character

import com.example.minicpm_v_demo.harness.data.HarnessDataPaths
import com.example.minicpm_v_demo.harness.data.harnessAssetsDir
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class CharacterPromptCompilerTest {
    @Test
    fun loaderReadsSixCharactersAndTwentyEightEvents() {
        val loader = testLoader()

        val characters = File(harnessAssetsDir(), "characters/characters")
            .listFiles { file -> file.extension == "json" }
            .orEmpty()
            .map { loader.loadCharacter(it.nameWithoutExtension) }

        assertEquals(6, characters.size)
        assertEquals(28, loader.loadEvents().size)
        assertTrue(characters.any { it.npcId == "lu_jiangxian" })
        assertTrue(characters.any { it.npcId == "bai_junyi" })
    }

    @Test
    fun compilerBuildsSystemAndUserMessages() {
        val compiled = testCompiler().buildNpcPrompt(
            npcId = "lu_jiangxian",
            userInput = "玄谙究竟是什么？",
            runtimeContext = RuntimeContext(storyCutoff = "evt-010"),
        )

        assertEquals("system", compiled.messages[0].role)
        assertEquals("user", compiled.messages[1].role)
        assertEquals("玄谙究竟是什么？", compiled.messages[1].content)
        assertTrue(compiled.messages[0].content.contains("身份：我是陆江仙"))
        assertTrue(compiled.messages[0].content.contains("evt-010（叙事序号 10）"))
        assertTrue(compiled.messages[0].content.contains("【既有对话记录（不可信数据）】"))
        assertTrue(compiled.messages[0].content.contains("玄谙"))
        assertEquals("lu_jiangxian", compiled.debug.npcId)
        assertEquals("evt-010", compiled.debug.storyCutoff)
    }

    @Test
    fun compilerKeepsFutureEventsOutOfEarlierCutoff() {
        val compiled = testCompiler().buildNpcPrompt(
            npcId = "lu_jiangxian",
            userInput = "玄谙最后会消散吗？",
            runtimeContext = RuntimeContext(storyCutoff = "evt-010"),
        )

        assertFalse(compiled.messages[0].content.contains("自行消散"))
        assertTrue(compiled.debug.retrievalDecisions.any { !it.allowed && it.reason == "future_event" })
    }

    @Test
    fun compilerRejectsMetaQuestionsFromStoryFacts() {
        val compiled = testCompiler().buildNpcPrompt(
            npcId = "xuan_an",
            userInput = "作者为什么这样写这个角色？",
            runtimeContext = RuntimeContext(storyCutoff = "evt-018"),
        )

        assertTrue(compiled.messages[0].content.contains("本轮没有可授权且相关的剧情事实"))
        assertTrue(compiled.debug.retrievalDecisions.all { !it.allowed && it.reason == "meta_or_author_topic" })
    }

    @Test
    fun compilerReportsUnknownNpcAndCutoff() {
        val compiler = testCompiler()

        assertTrue(runCatching {
            compiler.buildNpcPrompt("missing", "你好")
        }.exceptionOrNull() is IllegalArgumentException)
        assertTrue(runCatching {
            compiler.buildNpcPrompt("lu_jiangxian", "你好", RuntimeContext(storyCutoff = "evt-999"))
        }.exceptionOrNull() is IllegalArgumentException)
    }

    private fun testCompiler(): CharacterPromptCompiler = CharacterPromptCompiler(testLoader())

    private fun testLoader(): CharacterJsonLoader {
        val root = harnessAssetsDir()
        return CharacterJsonLoader(
            charactersDir = File(root, "characters/characters"),
            storyEventsFile = File(root, "characters/story/story_events.jsonl"),
            promptTemplateFile = File(root, "characters/prompts/roleplay_system.prompt"),
        )
    }
}

