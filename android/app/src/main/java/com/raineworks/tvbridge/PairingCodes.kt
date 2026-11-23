package com.raineworks.tvbridge

import java.security.MessageDigest
import java.security.SecureRandom

/**
 * Pairing codes and the limits on guessing them, without Android, so
 * they're unit tested (PairingCodesTest). [Pairing] shows the codes and
 * issues the token; [ApiServer] answers 429 while [locked] or when
 * [mayStart] refuses, and 403 when [finish] does.
 *
 * - A code is six digits, good for five minutes and five tries.
 * - At most four pairings wait at once: a fifth evicts the oldest.
 * - Ten wrong codes within ten minutes, across pairings, lock pairing for
 *   ten minutes and drop every waiting code (a guess at every code takes ~1M).
 *
 * @param clock the time in milliseconds (the system's; tests pass their own).
 */
class PairingCodes(
    private val clock: () -> Long = System::currentTimeMillis,
    private val random: SecureRandom = SecureRandom(),
) {
    /** A pairing started: its [id], given to Home Assistant, and its [code], shown on the TV. */
    data class Code(val id: String, val code: String)

    private class Pending(val code: String, val expires: Long, var attempts: Int)

    private val pending = LinkedHashMap<String, Pending>()
    private val failures = ArrayDeque<Long>()
    private var lockedUntil = 0L
    private var lastStart: Long? = null

    /** One pairing started a second: no flood of codes on screen, or of pairings evicting a real one. */
    @Synchronized
    fun mayStart(): Boolean {
        val now = clock()
        val last = lastStart
        if (last != null && now - last < START_INTERVAL_MS) return false
        lastStart = now
        return true
    }

    /** Whether pairing is locked after too many wrong codes. */
    @Synchronized
    fun locked(): Boolean = clock() < lockedUntil

    /**
     * A new pairing's id and code.
     *
     * @throws IllegalStateException while pairing is [locked].
     */
    @Synchronized
    fun start(): Code {
        val now = clock()
        check(now >= lockedUntil) { "Too many wrong codes: try again later" }
        pending.entries.removeAll { it.value.expires < now }
        while (pending.size >= MAX_PENDING) pending.remove(pending.keys.first())
        val id = ByteArray(12).also { random.nextBytes(it) }.joinToString("") { "%02x".format(it) }
        val code = "%06d".format(random.nextInt(1_000_000))
        pending[id] = Pending(code, now + CODE_TTL_MS, 0)
        return Code(id, code)
    }

    /**
     * Whether [code] is the right one for pairing [id]: true once, and the
     * pairing is then done. False for an unknown or expired pairing, one out
     * of tries, or a wrong code (which counts towards the lock).
     */
    @Synchronized
    fun finish(id: String, code: String): Boolean {
        val entry = pending[id] ?: return false
        val now = clock()
        if (entry.expires < now || entry.attempts >= MAX_ATTEMPTS) {
            pending.remove(id)
            return false
        }
        entry.attempts++
        if (!MessageDigest.isEqual(entry.code.toByteArray(), code.trim().toByteArray())) {
            failures.addLast(now)
            while (failures.isNotEmpty() && failures.first() < now - FAILURE_WINDOW_MS) failures.removeFirst()
            if (failures.size >= MAX_FAILURES) {
                lockedUntil = now + LOCKOUT_MS
                failures.clear()
                pending.clear()
            }
            return false
        }
        pending.remove(id)
        return true
    }

    /** The limits, for [Pairing] and the tests. */
    companion object {
        const val START_INTERVAL_MS = 1000L
        const val CODE_TTL_MS = 5 * 60 * 1000L
        const val MAX_ATTEMPTS = 5
        const val MAX_PENDING = 4
        const val MAX_FAILURES = 10
        const val FAILURE_WINDOW_MS = 10 * 60 * 1000L
        const val LOCKOUT_MS = 10 * 60 * 1000L
    }
}
