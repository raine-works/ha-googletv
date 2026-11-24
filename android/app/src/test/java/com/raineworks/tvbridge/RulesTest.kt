package com.raineworks.tvbridge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

/** Whether a pop-up shows: the pop-ups switch first, then the inputs' and apps' switches. */
class RulesTest {
    private val apps = setOf("com.netflix.ninja")
    private val inputs = setOf("hdmi2")

    @Test
    fun popsUpWhenNothingBlocksIt() {
        assertNull(Rules.blockingRule(true, apps, inputs, "com.google.android.youtube.tv", "hdmi1"))
        assertNull(Rules.blockingRule(true, apps, inputs, null, null))
    }

    @Test
    fun aBlockedInputOrAppKeepsItOff() {
        assertEquals("input:hdmi2", Rules.blockingRule(true, apps, inputs, null, "hdmi2"))
        assertEquals("app:com.netflix.ninja", Rules.blockingRule(true, apps, inputs, "com.netflix.ninja", null))
        // The input on screen says first
        assertEquals("input:hdmi2", Rules.blockingRule(true, apps, inputs, "com.netflix.ninja", "hdmi2"))
    }

    @Test
    fun popUpsSwitchedOffKeepEveryOneOff() {
        assertEquals(Rules.ALL, Rules.blockingRule(false, emptySet(), emptySet(), null, null))
        assertEquals(Rules.ALL, Rules.blockingRule(false, apps, inputs, "com.netflix.ninja", "hdmi2"))
        assertEquals(Rules.ALL, Rules.blockingRule(false, apps, inputs, "com.google.android.youtube.tv", null))
    }

    @Test
    fun theSwitchIsABooleanOrAbsent() {
        assertNull(Rules.popups(null))
        assertEquals(true, Rules.popups(true))
        assertEquals(false, Rules.popups(false))
    }

    @Test
    fun anythingElseForTheSwitchIsRefused() {
        // "false" as a string mustn't read as on, nor 0 as off
        assertThrows(IllegalArgumentException::class.java) { Rules.popups("false") }
        assertThrows(IllegalArgumentException::class.java) { Rules.popups(0) }
        assertThrows(IllegalArgumentException::class.java) { Rules.popups(org.json.JSONObject.NULL) }
    }
}
