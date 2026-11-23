package com.raineworks.tvbridge

import com.raineworks.tvbridge.PairingCodes.Companion.CODE_TTL_MS
import com.raineworks.tvbridge.PairingCodes.Companion.FAILURE_WINDOW_MS
import com.raineworks.tvbridge.PairingCodes.Companion.LOCKOUT_MS
import com.raineworks.tvbridge.PairingCodes.Companion.MAX_ATTEMPTS
import com.raineworks.tvbridge.PairingCodes.Companion.MAX_FAILURES
import com.raineworks.tvbridge.PairingCodes.Companion.MAX_PENDING
import com.raineworks.tvbridge.PairingCodes.Companion.START_INTERVAL_MS
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** Pairing codes, their expiry and tries, and the lockout after wrong codes. */
class PairingCodesTest {
    private var now = 1_000_000L
    private val codes = PairingCodes(clock = { now })

    private fun wrong(code: PairingCodes.Code) = if (code.code == "000000") "000001" else "000000"

    @Test
    fun codeIsSixDigits() {
        repeat(20) { assertTrue(Regex("\\d{6}").matches(codes.start().code)) }
    }

    @Test
    fun rightCodePairsOnce() {
        val c = codes.start()
        assertTrue(codes.finish(c.id, c.code))
        assertFalse(codes.finish(c.id, c.code))
    }

    @Test
    fun rightCodeWithSpacesAroundPairs() {
        val c = codes.start()
        assertTrue(codes.finish(c.id, " ${c.code}\n"))
    }

    @Test
    fun wrongCodeIsRefused() {
        val c = codes.start()
        assertFalse(codes.finish(c.id, wrong(c)))
        assertFalse(codes.finish(c.id, ""))
        assertTrue(codes.finish(c.id, c.code))
    }

    @Test
    fun unknownPairingIsRefused() {
        val c = codes.start()
        assertFalse(codes.finish("not-a-pairing", c.code))
        assertFalse(codes.finish("", c.code))
    }

    @Test
    fun pairingOutOfTriesIsRefusedEvenWithTheRightCode() {
        val c = codes.start()
        repeat(MAX_ATTEMPTS) { assertFalse(codes.finish(c.id, wrong(c))) }
        assertFalse(codes.finish(c.id, c.code))
    }

    @Test
    fun codeExpires() {
        val kept = codes.start()
        val expired = codes.start()
        now += CODE_TTL_MS
        assertTrue(codes.finish(kept.id, kept.code))
        now += 1
        assertFalse(codes.finish(expired.id, expired.code))
    }

    @Test
    fun anotherPairingEvictsTheOldestWaiting() {
        val started = List(MAX_PENDING + 1) { codes.start() }
        assertFalse(codes.finish(started[0].id, started[0].code))
        started.drop(1).forEach { assertTrue(codes.finish(it.id, it.code)) }
    }

    @Test
    fun oneStartASecond() {
        assertTrue(codes.mayStart())
        assertFalse(codes.mayStart())
        now += START_INTERVAL_MS - 1
        assertFalse(codes.mayStart())
        now += 1
        assertTrue(codes.mayStart())
        assertFalse(codes.mayStart())
    }

    @Test
    fun tooManyWrongCodesLockPairing() {
        val waiting = codes.start()
        var wrongs = 0
        while (wrongs < MAX_FAILURES) {
            assertFalse(codes.locked())
            val c = codes.start()
            repeat(minOf(MAX_ATTEMPTS, MAX_FAILURES - wrongs)) {
                assertFalse(codes.finish(c.id, wrong(c)))
                wrongs++
            }
        }
        assertEquals(MAX_FAILURES, wrongs)
        assertTrue(codes.locked())
        // The codes waiting are dropped and no pairing starts.
        assertFalse(codes.finish(waiting.id, waiting.code))
        assertThrows(IllegalStateException::class.java) { codes.start() }

        now += LOCKOUT_MS - 1
        assertTrue(codes.locked())
        assertThrows(IllegalStateException::class.java) { codes.start() }

        now += 1
        assertFalse(codes.locked())
        val c = codes.start()
        assertTrue(codes.finish(c.id, c.code))
    }

    @Test
    fun wrongCodesOlderThanTheWindowDontCount() {
        var wrongs = 0
        while (wrongs < MAX_FAILURES - 1) {
            val c = codes.start()
            repeat(minOf(MAX_ATTEMPTS, MAX_FAILURES - 1 - wrongs)) {
                assertFalse(codes.finish(c.id, wrong(c)))
                wrongs++
            }
        }
        now += FAILURE_WINDOW_MS + 1
        val c = codes.start()
        assertFalse(codes.finish(c.id, wrong(c)))
        assertFalse(codes.locked())
        assertTrue(codes.finish(c.id, c.code))
    }
}
