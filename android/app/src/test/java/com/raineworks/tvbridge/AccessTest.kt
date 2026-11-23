package com.raineworks.tvbridge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.SecureRandom

/** The API's bearer-token check: only a token Home Assistant paired with gets in. */
class AccessTest {
    private val random = SecureRandom()
    private val token = Access.newToken(random)
    private val tokens = setOf(token, Access.newToken(random))

    @Test
    fun bearerTakesTheTokenFromTheHeader() {
        assertEquals(token, Access.bearer("Bearer $token"))
        assertEquals(token, Access.bearer("Bearer  $token "))
        assertNull(Access.bearer(null))
    }

    @Test
    fun pairedTokenGetsIn() {
        assertTrue(Access.isPaired(token, tokens))
        assertTrue(Access.isPaired(Access.bearer("Bearer $token"), tokens))
    }

    @Test
    fun missingOrEmptyTokenIsRefused() {
        assertFalse(Access.isPaired(null, tokens))
        assertFalse(Access.isPaired("", tokens))
        assertFalse(Access.isPaired(Access.bearer("Bearer "), tokens))
    }

    @Test
    fun anyTokenIsRefusedWhenNothingIsPaired() {
        assertFalse(Access.isPaired(token, emptySet()))
        assertFalse(Access.isPaired("", setOf("")))
    }

    @Test
    fun wrongTokenIsRefused() {
        assertFalse(Access.isPaired(Access.newToken(random), tokens))
    }

    @Test
    fun prefixOrExtensionOfAPairedTokenIsRefused() {
        assertFalse(Access.isPaired(token.dropLast(1), tokens))
        assertFalse(Access.isPaired(token.take(1), tokens))
        assertFalse(Access.isPaired(token + "A", tokens))
    }

    @Test
    fun newTokensAreUrlSafeUnpaddedAndDistinct() {
        val pattern = Regex("[A-Za-z0-9_-]{43}")
        repeat(20) { assertTrue(pattern.matches(Access.newToken(random))) }
        assertNotEquals(Access.newToken(random), Access.newToken(random))
    }
}
